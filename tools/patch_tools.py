import logging
import uuid
from typing import Dict, Any, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from common.config import settings
from common.mcp_session import open_mcp_session
from mcp.shared.exceptions import McpError

logger = logging.getLogger(__name__)


class ApplyPatchOutputDetails(BaseModel):
    stdout: str
    stderr: str
    return_code: int

class ApplyPatchOutput(BaseModel):
    ok: bool = Field(description="True if the patch was applied successfully, False otherwise.")
    file_path_hint: str = Field(description="The file path hint provided in the input.")
    message: str = Field(description="A summary message indicating success or failure.")
    details: Optional[ApplyPatchOutputDetails] = Field(default=None, description="Detailed output from the git apply command if it was run.")

class ApplyPatchInput(BaseModel):
    """Input for the apply_patch tool."""
    # Note: file_path_in_repo is kept for consistency with the plan, but git apply
    # determines the file from the diff content itself.
    file_path_in_repo: str = Field(
        description="The path to the file to be patched. This is often descriptive, as the patch content itself specifies the file paths."
    )
    diff_content: str = Field(description="The content of the diff/patch to apply.")


@tool(args_schema=ApplyPatchInput)
async def apply_patch(file_path_in_repo: str, diff_content: str) -> ApplyPatchOutput:
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
    # Initialize parts of the output structure
    final_ok = False
    final_message = ""
    git_apply_details: Optional[ApplyPatchOutputDetails] = None
    
    try:
        async with open_mcp_session() as session:
            # 1. Write the diff content to a temporary file in the repo
            try:
                await session.call_tool("fs.write", {"path": temp_patch_filename, "content": diff_content})
                logger.info(f"Wrote patch content to temporary file: {temp_patch_filename}")
            except McpError as e:
                error_message = f"MCP Error writing temporary patch file '{temp_patch_filename}': {e}"
                logger.error(error_message)
                return ApplyPatchOutput(ok=False, file_path_hint=file_path_in_repo, message=error_message)

            # 2. Apply the patch using git
            command = f"git apply --unsafe-paths --inaccurate-eof {temp_patch_filename}"
            try:
                git_mcp_result = await session.call_tool("shell.run", {"command": command, "cwd": "."})
                git_apply_details = ApplyPatchOutputDetails(
                    stdout=git_mcp_result.stdout,
                    stderr=git_mcp_result.stderr,
                    return_code=git_mcp_result.return_code
                )
                if git_mcp_result.return_code == 0:
                    final_ok = True
                    final_message = f"Patch applied successfully to '{file_path_in_repo}'."
                else:
                    final_message = f"'git apply' failed with return code {git_mcp_result.return_code}. See details."
                    logger.warning(final_message)

            except McpError as e:
                error_message = f"MCP Error running 'git apply' for patch '{temp_patch_filename}': {e}"
                logger.error(error_message)
                final_message = error_message

            # 3. Clean up the temporary patch file
            try:
                await session.call_tool("fs.remove", {"path": temp_patch_filename})
                logger.info(f"Removed temporary patch file: {temp_patch_filename}")
            except McpError as e:
                # Log the cleanup error, but don't fail the whole operation since the patch may have succeeded.
                logger.warning(f"MCP Error removing temporary patch file '{temp_patch_filename}': {e}")
                if final_ok:
                    final_message += f" (Warning: failed to remove temporary patch file: {e})"

    except Exception as e:
        final_message = f"An unexpected error occurred during apply_patch: {e}"
        logger.error(final_message, exc_info=True)

    return ApplyPatchOutput(
        ok=final_ok,
        file_path_hint=file_path_in_repo,
        message=final_message,
        details=git_apply_details
    )

