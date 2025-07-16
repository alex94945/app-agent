import logging
import json
import shlex
from typing import Dict, Any, Optional, Union
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field
from langchain_core.tools import tool

from mcp import ClientSession
from common.mcp_session import open_mcp_session
from mcp.shared.exceptions import McpError, ErrorData
from common.config import get_settings
from agent.pty.manager import get_pty_manager

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
    pty: bool = Field(
        default=False,
        description="If true, run the command in a pseudo-terminal (PTY) to stream output. This is for long-running processes like dev servers or build scripts."
    )
    task_name: Optional[str] = Field(
        default=None,
        description="A descriptive name for the task, used for logging and UI display when pty=True."
    )

# --- Pydantic Schema for Tool Output ---

class RunShellOutput(BaseModel):
    ok: bool = Field(description="True if the command executed successfully (return code 0), False otherwise.")
    return_code: int = Field(description="The return code of the command.")
    stdout: str = Field(description="The standard output of the command.")
    stderr: str = Field(description="The standard error of the command.")
    command_executed: str = Field(description="The command that was executed.")

class PTYTask(BaseModel):
    """Represents a handle to a task running in a PTY."""
    task_id: UUID = Field(description="The unique ID of the PTY task.")
    type: str = Field(default="pty_task", description="The type of the output.")

# --- Tool Implementation ---

@tool(args_schema=RunShellInput)
async def run_shell(
    command: str, 
    working_directory_relative_to_repo: Optional[str] = None, 
    stdin: Optional[str] = None, 
    pty: bool = False, 
    task_name: Optional[str] = None,
) -> Union[RunShellOutput, PTYTask]:
    """
    Executes a shell command in the repository workspace.
    Returns a dictionary with stdout, stderr, and the return code.
    """
    logger.info(f"Tool: run_shell called with command: '{command}' in dir: '{working_directory_relative_to_repo}' pty={pty}")
    settings = get_settings()
    repo_dir = Path(settings.REPO_DIR)
    absolute_cwd = str(repo_dir)
    if working_directory_relative_to_repo:
        absolute_cwd = str(repo_dir / working_directory_relative_to_repo)

    if pty:
        pty_manager = get_pty_manager()
        task_id = await pty_manager.spawn(
            command=shlex.split(command),
            cwd=absolute_cwd,
            task_name=task_name or command,
        )
        return PTYTask(task_id=task_id)

    # --- Legacy MCP-based execution for non-PTY calls ---
    try:
        mcp_args = {"command": command, "cwd": absolute_cwd}
        if stdin is not None:
            mcp_args["stdin"] = stdin
        async with open_mcp_session() as session:
            mcp_result = await session.call_tool("shell.run", arguments=mcp_args)

            # Normalize response for FastMCP ≥2.8 (CallToolResult) and older formats
            def _normalize_shell_run_result(raw):
                """Return a dict with stdout/stderr/return_code keys."""
                # Modern fastmcp clients return a CallToolResult object.
                if hasattr(raw, 'result'):
                    raw = raw.result

                # The result itself might be a Pydantic model.
                if hasattr(raw, 'model_dump'):
                    raw = raw.model_dump()

                if isinstance(raw, dict) and {"stdout", "stderr", "return_code"}.issubset(raw.keys()):
                    return raw

                # Fallback for older formats (e.g., list of TextContent with JSON)
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

                # If we still haven't found the right format, raise an error.
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
