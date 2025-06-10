import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
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

# --- Tool Implementation ---

@tool(args_schema=RunShellInput)
async def run_shell(command: str, working_directory_relative_to_repo: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes a shell command in the repository workspace.
    Returns a dictionary with stdout, stderr, and the return code.
    """
    logger.info(f"Tool: run_shell called with command: '{command}' in dir: '{working_directory_relative_to_repo}'")
    try:
        async with streamablehttp_client(base_url=settings.MCP_SERVER_URL) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                # The MCP shell.run method executes the command
                result = await session.shell.run(
                    command=command,
                    cwd=working_directory_relative_to_repo or "."
                )
                # The result object is expected to have stdout, stderr, and return_code attributes
                return {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "return_code": result.return_code
                }
    except McpError as e:
        error_message = f"MCP Error running command '{command}': {e}"
        logger.error(error_message)
        return {"stdout": "", "stderr": error_message, "return_code": -1}
    except Exception as e:
        error_message = f"Failed to execute run_shell tool for command '{command}': {e}"
        logger.error(error_message, exc_info=True)
        return {"stdout": "", "stderr": error_message, "return_code": -1}
