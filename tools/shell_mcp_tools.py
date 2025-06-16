import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from mcp import ClientSession
from common.mcp_session import open_mcp_session
from mcp.shared.exceptions import McpError
from common.config import settings

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
        async with open_mcp_session() as session:
            result = await session.call_tool(
                "shell.run",
                arguments={
                    "command": command,
                    "cwd": working_directory_relative_to_repo or "."
                }
            )
        return RunShellOutput(
            ok=result.return_code == 0,
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
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
