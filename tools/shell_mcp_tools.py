import logging
import json
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from mcp import ClientSession
from common.mcp_session import open_mcp_session
from mcp.shared.exceptions import McpError, ErrorData
from common.config import get_settings

logger = logging.getLogger(__name__)

# --- Pydantic Schema for Tool Input ---

class RunShellInput(BaseModel):
    command: str = Field(description="The shell command to execute.")
    working_directory_relative_to_repo: Optional[str] = Field(
        default=None, 
        description="The directory within the repo to run the command from. Defaults to the repo root."
    )

# --- Pydantic Schema for Tool Output ---

class RunShellOutput(BaseModel):
    ok: bool = Field(description="True if the command executed successfully (return code 0), False otherwise.")
    return_code: int = Field(description="The return code of the command.")
    stdout: str = Field(description="The standard output of the command.")
    stderr: str = Field(description="The standard error of the command.")
    command_executed: str = Field(description="The command that was executed.")

# --- Tool Implementation ---

@tool(args_schema=RunShellInput)
async def run_shell(command: str, working_directory_relative_to_repo: Optional[str] = None) -> RunShellOutput:
    """
    Executes a shell command in the repository workspace.
    Returns a dictionary with stdout, stderr, and the return code.
    """
    logger.info(f"Tool: run_shell called with command: '{command}' in dir: '{working_directory_relative_to_repo}'")
    try:
        settings = get_settings()
        repo_dir = settings.REPO_DIR
        absolute_cwd = str(repo_dir)
        if working_directory_relative_to_repo:
            absolute_cwd = str(repo_dir / working_directory_relative_to_repo)
        async with open_mcp_session() as session:
            mcp_result = await session.call_tool(
                "shell.run",
                arguments={"command": command, "cwd": absolute_cwd},
            )

            # mcp_result is a list of content items from FastMCP, e.g., [TextContent(...)]
            # It could be empty if the tool returns nothing, or if there's an issue
            # not caught by ToolError during the call_tool execution itself.
            if not mcp_result or not isinstance(mcp_result, list) or len(mcp_result) == 0:
                logger.error("MCP tool 'shell.run' returned no content or unexpected format.")
                # Raise McpError to be caught by the existing McpError handler below
                raise McpError(ErrorData(code=-32001, message="MCP tool 'shell.run' returned no content"))

            first_content_item = mcp_result[0]
            
            # FastMCP typically returns Pydantic models/dicts as JSON string in TextContent
            if not hasattr(first_content_item, 'text') or not first_content_item.text:
                logger.error("MCP tool 'shell.run' returned content item without text.")
                raise McpError(ErrorData(code=-32002, message="MCP tool 'shell.run' returned content item without text"))

            result_json_str = first_content_item.text
            # This result_json_str should be the JSON representation of _ShellRunOutput from conftest.py
            result_data = json.loads(result_json_str)

        return RunShellOutput(
            ok=result_data.get("return_code") == 0,
            return_code=result_data.get("return_code", -1),
            stdout=result_data.get("stdout", ""),
            stderr=result_data.get("stderr", ""),
            command_executed=command,
        )
    except McpError as e:
        error_message = f"MCP Error running command '{command}': {e}"
        logger.error(error_message)
        return RunShellOutput(
            ok=False,
            return_code=-1, 
            stdout="",
            stderr=error_message,
            command_executed=command
        )
    except Exception as e:
        error_message = f"Failed to execute run_shell tool for command '{command}': {e}"
        logger.error(error_message, exc_info=True)
        return RunShellOutput(
            ok=False,
            return_code=-1,
            stdout="",
            stderr=error_message,
            command_executed=command,
        )
