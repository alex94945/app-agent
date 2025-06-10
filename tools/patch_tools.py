import logging
import uuid
from typing import Dict, Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from common.config import settings
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

logger = logging.getLogger(__name__)


class ApplyPatchInput(BaseModel):
    """Input for the apply_patch tool."""
    # Note: file_path_in_repo is kept for consistency with the plan, but git apply
    # determines the file from the diff content itself.
    file_path_in_repo: str = Field(
        description="The path to the file to be patched. This is often descriptive, as the patch content itself specifies the file paths."
    )
    diff_content: str = Field(description="The content of the diff/patch to apply.")


@tool(args_schema=ApplyPatchInput)
async def apply_patch(file_path_in_repo: str, diff_content: str) -> Dict[str, Any]:
    """
    Applies a patch to files in the repository workspace using 'git apply'.

    This tool writes the provided diff content to a temporary file within the
    repository, applies it using 'git apply', and then removes the temporary
    file. The paths within the diff content must be relative to the repository root.

    TODO: Consider adding diff normalization logic here in the future to handle
    patches generated from different systems or with slight formatting variations.
    """
    logger.info(f"Tool: apply_patch called for file hint: '{file_path_in_repo}'")
    
    # Generate a unique name for the temporary patch file to avoid collisions.
    temp_patch_filename = f".tmp.apply_patch.{uuid.uuid4()}.patch"
    result = {}
    
    try:
        async with streamablehttp_client(base_url=settings.MCP_SERVER_URL) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                # 1. Write the diff content to a temporary file in the repo
                try:
                    await session.fs.write(path=temp_patch_filename, content=diff_content)
                    logger.info(f"Wrote patch content to temporary file: {temp_patch_filename}")
                except McpError as e:
                    error_message = f"MCP Error writing temporary patch file '{temp_patch_filename}': {e}"
                    logger.error(error_message)
                    return {"stdout": "", "stderr": error_message, "return_code": -1}

                # 2. Apply the patch using git
                # --unsafe-paths is needed if the patch tries to modify files outside the current dir
                # --inaccurate-eof is a common flag to handle patches from various sources
                command = f"git apply --unsafe-paths --inaccurate-eof {temp_patch_filename}"
                try:
                    git_result = await session.shell.run(command=command, cwd=".")
                    result = {
                        "stdout": git_result.stdout,
                        "stderr": git_result.stderr,
                        "return_code": git_result.return_code,
                    }
                    if git_result.return_code != 0:
                        logger.error(f"Error applying patch. Stderr: {git_result.stderr}")
                    else:
                        logger.info(f"Successfully applied patch for hint: {file_path_in_repo}")

                except McpError as e:
                    error_message = f"MCP Error running 'git apply': {e}"
                    logger.error(error_message)
                    result = {"stdout": "", "stderr": error_message, "return_code": -1}

                # 3. Clean up the temporary patch file
                try:
                    await session.fs.remove(path=temp_patch_filename)
                    logger.info(f"Removed temporary patch file: {temp_patch_filename}")
                except McpError as e:
                    # Log the cleanup error, but don't overwrite the primary result
                    logger.warning(f"MCP Error removing temporary patch file '{temp_patch_filename}': {e}")

    except Exception as e:
        error_message = f"Failed to execute apply_patch tool for hint '{file_path_in_repo}': {e}"
        logger.error(error_message, exc_info=True)
        return {"stdout": "", "stderr": error_message, "return_code": -1}

    return result

