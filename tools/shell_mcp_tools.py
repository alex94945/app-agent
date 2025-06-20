import logging
import json
from typing import Dict, Any, Optional
from pathlib import Path # Added Path import
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
    stdin: Optional[str] = Field(
        default=None,
        description="Content to be passed to the command's standard input."
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
async def run_shell(command: str, working_directory_relative_to_repo: Optional[str] = None, stdin: Optional[str] = None) -> RunShellOutput:
    """
    Executes a shell command in the repository workspace.
    Returns a dictionary with stdout, stderr, and the return code.
    """
    logger.info(f"Tool: run_shell called with command: '{command}' in dir: '{working_directory_relative_to_repo}'")
    try:
        settings = get_settings()
        repo_dir = Path(settings.REPO_DIR) # Ensure repo_dir is a Path object
        absolute_cwd = str(repo_dir)
        if working_directory_relative_to_repo:
            absolute_cwd = str(repo_dir / working_directory_relative_to_repo)
        mcp_args = {"command": command, "cwd": absolute_cwd}
        if stdin is not None:
            mcp_args["stdin"] = stdin
        async with open_mcp_session() as session:
            mcp_result = await session.call_tool("shell.run", arguments=mcp_args)

            # Normalize response for FastMCP ≥2.8 (CallToolResult) and older formats
            def _normalize_shell_run_result(raw):
                """Return a dict with stdout/stderr/return_code keys."""
                # Case 0: We already have the desired dict
                if isinstance(raw, dict) and {"stdout", "stderr", "return_code"}.issubset(raw.keys()):
                    return raw

                # Case 1: New FastMCP BaseModel wrapper
                if hasattr(raw, "model_dump"):
                    raw_dict = raw.model_dump(exclude_none=True)
                    if {"stdout", "stderr", "return_code"}.issubset(raw_dict.keys()):
                        return raw_dict
                    # If this is CallToolResult, drill down
                    if "content" in raw_dict and isinstance(raw_dict["content"], list):
                        raw = raw_dict["content"]
                    else:
                        logger.error("Unknown keys in model_dump result: %s", raw_dict.keys())
                        raise McpError(ErrorData(code=-32003, message="Unexpected shell.run result format"))

                # Case 2: List of TextContent
                if isinstance(raw, list) and raw:
                    first = raw[0]
                    try:
                        if hasattr(first, "text"):
                            return json.loads(first.text)
                        if isinstance(first, dict) and "text" in first:
                            return json.loads(first["text"])
                    except Exception as e:
                        logger.error("Failed to decode TextContent text as JSON: %s", e)
                        raise

                # Unsupported format
                logger.error("Unhandled shell.run result format: %s", type(raw))
                raise McpError(ErrorData(code=-32003, message="Unexpected shell.run result format"))

            try:
                result_data = _normalize_shell_run_result(mcp_result)
            except Exception as e:
                raise


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
