# tools/file_io_mcp_tools.py

import logging
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.tools import tool

# Correct imports based on official MCP documentation
from common.mcp_session import open_mcp_session
from fastmcp.exceptions import ToolError
from common.config import settings

logger = logging.getLogger(__name__)

# --- Pydantic Schemas for Tool Inputs ---

class ReadFileInput(BaseModel):
    path_in_repo: str = Field(description="The path to the file within the repository to read.")

class WriteFileOutput(BaseModel):
    ok: bool = Field(description="True if the file was written successfully, False otherwise.")
    path: str = Field(description="The path to the file that was written or attempted.")
    message: str = Field(description="A message indicating success or failure.")

class WriteFileInput(BaseModel):
    path_in_repo: str = Field(description="The path to the file within the repository to write.")
    content: str = Field(description="The content to write to the file.")

# --- Tool Implementations ---

@tool(args_schema=ReadFileInput)
async def read_file(path_in_repo: str) -> str:
    """
    Reads the entire content of a file from the repository workspace.
    The path should be relative to the repository root.
    """
    logger.info(f"Tool: read_file called for path_in_repo: '{path_in_repo}'")
    logger.debug(f"read_file: Using settings.REPO_DIR: '{settings.REPO_DIR}'")
    absolute_path_to_read = Path(settings.REPO_DIR) / path_in_repo
    logger.debug(f"read_file: Computed absolute_path_to_read: '{absolute_path_to_read}'")
    try:
        # The mock MCP server's fs.read tool operates relative to its own CWD.
        # The agent provides paths relative to the repo root.
        # We must resolve the path to be absolute for the mock server.
        async with open_mcp_session() as session:
            content = await session.call_tool("fs.read", {"path": str(absolute_path_to_read)})
            logger.debug(f"read_file: Raw content from session.call_tool('fs.read', path='{absolute_path_to_read}'): {content!r} (type: {type(content)})")

            # Detailed logging for debugging content structure
            if hasattr(content, 'content'):
                if content.content:
                    logger.debug(f"read_file: content.content is present. Type: {type(content.content)}, Value: {content.content}")
                    if isinstance(content.content, list):
                        logger.debug(f"read_file: content.content is a list. Length: {len(content.content)}")
                        if len(content.content) == 1:
                            logger.debug(f"read_file: content.content has 1 element. Element type: {type(content.content[0])}")
                        else:
                            logger.debug(f"read_file: content.content list length is not 1.")
                    else:
                        logger.debug(f"read_file: content.content is not a list.")
                else:
                    logger.debug(f"read_file: content.content is None or empty.")
            else:
                logger.debug(f"read_file: content does not have attribute 'content'.")

            if isinstance(content, list) and len(content) > 0 and hasattr(content[0], 'text'):
                # Content is expected to be a list, e.g., [TextContent(...)]
                # We extract the .text attribute from the first element.
                processed_content = content[0].text
                logger.debug(f"read_file: Extracted text from content[0].text: {processed_content!r}")
                return processed_content
            elif isinstance(content, str): # Should not happen based on docs, but as a fallback
                logger.warning(f"read_file: session.call_tool unexpectedly returned str, not List[Content]. Using as is.")
                return content
            else:
                logger.warning(f"read_file: session.call_tool returned unexpected content format: {content!r}. Returning empty string.")
                return ""
    except ToolError as e:
        # FastMCP client wraps server-side McpError in a ToolError.
        # We format this to match the expected test assertion.
        logger.error(f"MCP ToolError reading file '{path_in_repo}': {e}")
        return f"MCP Error reading file '{path_in_repo}': {e}"
    except Exception as e:
        # Catch any other unexpected errors.
        error_message = f"Unexpected error in read_file tool for '{path_in_repo}': {e}"
        logger.error(error_message, exc_info=True)
        return error_message

@tool(args_schema=WriteFileInput)
async def write_file(path_in_repo: str, content: str) -> WriteFileOutput:
    """
    Writes content to a file in the repository workspace, overwriting it if it exists.
    The path should be relative to the repository root.
    """
    logger.info(f"Tool: write_file called for path: {path_in_repo}")
    try:
        async with open_mcp_session() as session:
            await session.call_tool("fs.write",
                                    {"path": path_in_repo, "content": content})
            success_message = f"Successfully wrote {len(content)} bytes to '{path_in_repo}'."
            logger.info(success_message)
            return WriteFileOutput(ok=True, path=path_in_repo, message=success_message)
    except ToolError as e:
        # FastMCP client wraps server-side McpError in a ToolError.
        # We format this to match the expected test assertion.
        logger.error(f"MCP ToolError writing file '{path_in_repo}': {e}")
        return WriteFileOutput(
            ok=False,
            path=path_in_repo,
            message=f"MCP Error writing file '{path_in_repo}': {e}",
        )
    except Exception as e:
        # Catch any other unexpected errors.
        error_message = f"Unexpected error in write_file tool for '{path_in_repo}': {e}"
        logger.error(error_message, exc_info=True)
        return WriteFileOutput(
            ok=False,
            path=path_in_repo,
            message=error_message,
        )