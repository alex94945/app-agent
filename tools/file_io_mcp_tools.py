# tools/file_io_mcp_tools.py

import logging
from pydantic import BaseModel, Field
from langchain_core.tools import tool

# The library is installed as 'mcp-client' and imported as 'mcp'
from mcp import Client, exceptions as mcp_exceptions
from common.config import settings

logger = logging.getLogger(__name__)

# --- Pydantic Schemas for Tool Inputs ---

class ReadFileInput(BaseModel):
    path_in_repo: str = Field(description="The path to the file within the repository to read.")

class WriteFileInput(BaseModel):
    path_in_repo: str = Field(description="The path to the file within the repository to write.")
    content: str = Field(description="The content to write to the file.")

# --- Tool Implementations ---

@tool(args_schema=ReadFileInput)
def read_file(path_in_repo: str) -> str:
    """
    Reads the entire content of a file from the repository workspace.
    The path should be relative to the repository root.
    """
    logger.info(f"Tool: read_file called for path: {path_in_repo}")
    try:
        # Initialize the client with the base_url from settings
        client = Client(base_url=settings.MCP_SERVER_URL)
        # The path is relative to the REPO_DIR configured on the MCP server
        content = client.fs.read(path=path_in_repo)
        return content
    except mcp_exceptions.MCPError as e:
        error_message = f"MCP Error reading file '{path_in_repo}': {e}"
        logger.error(error_message)
        return error_message
    except Exception as e:
        error_message = f"Failed to execute read_file tool for '{path_in_repo}': {e}"
        logger.error(error_message, exc_info=True)
        return error_message

@tool(args_schema=WriteFileInput)
def write_file(path_in_repo: str, content: str) -> str:
    """
    Writes content to a file in the repository workspace, overwriting it if it exists.
    The path should be relative to the repository root.
    """
    logger.info(f"Tool: write_file called for path: {path_in_repo}")
    try:
        # Initialize the client with the base_url from settings
        client = Client(base_url=settings.MCP_SERVER_URL)
        # The path is relative to the REPO_DIR configured on the MCP server
        client.fs.write(path=path_in_repo, content=content)
        if response.get("error"):
            error_message = f"MCP Error writing file '{path_in_repo}': {response['error']}"
            logger.error(error_message)
            return error_message
        
        success_message = f"Successfully wrote {len(content)} bytes to '{path_in_repo}'."
        logger.info(success_message)
        return success_message

    except Exception as e:
        error_message = f"Failed to execute write_file tool for '{path_in_repo}': {e}"
        logger.error(error_message, exc_info=True)
        return error_message