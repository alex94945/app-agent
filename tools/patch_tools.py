import logging
import uuid
import json
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from common.config import settings
from common.mcp_session import open_mcp_session
from mcp.shared.exceptions import McpError
from mcp.types import TextContent
from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


class ShellRunResult(BaseModel):
    stdout: str
    stderr: str
    return_code: int


class ApplyPatchOutput(BaseModel):
    ok: bool = Field(description="True if the patch was applied successfully, False otherwise.")
    file_path_hint: str = Field(description="The file path hint provided in the input.")
    message: str = Field(description="A summary message indicating success or failure.")
    details: Optional[ShellRunResult] = Field(default=None, description="Detailed output from the git apply command if it was run.")


class ApplyPatchInput(BaseModel):
    """Input for the apply_patch tool."""
    file_path_in_repo: str = Field(
        description="The path to the file to be patched. This is often descriptive, as the patch content itself specifies the file paths."
    )
    diff_content: str = Field(description="The content of the diff/patch to apply.")


@tool(args_schema=ApplyPatchInput)
async def apply_patch(file_path_in_repo: str, diff_content: str) -> ApplyPatchOutput:
    """
    Applies a patch to files in the repository workspace using 'git apply'.

    This tool writes the provided diff content to a temporary file, applies it
    using 'git apply', and then removes the temporary file.
    """
    logger.info(f"Tool: apply_patch called for file hint: '{file_path_in_repo}'")
    temp_patch_path = settings.REPO_DIR / f".tmp.apply_patch.{uuid.uuid4()}.patch"
    temp_patch_filename = str(temp_patch_path)
    shell_result = None

    try:
        async with open_mcp_session() as session:
            # 1. Write the diff content to a temporary file
            try:
                await session.call_tool("fs.write", {"path": temp_patch_filename, "content": diff_content})
                logger.info(f"Wrote patch content to temporary file: {temp_patch_filename}")
            except (McpError, ToolError) as e:
                error_message = e.message if hasattr(e, 'message') else e.args[0]
                logger.error(f"MCP Error writing temporary patch file: {error_message}")
                return ApplyPatchOutput(
                    ok=False,
                    file_path_hint=file_path_in_repo,
                    message=f"MCP Error writing temporary patch file: {error_message}"
                )

            # 2. Apply the patch using git
            try:
                git_mcp_result = await session.call_tool(
                    "shell.run",
                    {
                        "command": f"git apply --unsafe-paths {temp_patch_filename}",
                        "cwd": str(settings.REPO_DIR),
                    },
                )
                if not git_mcp_result or not isinstance(git_mcp_result[0], TextContent):
                    raise McpError(message="Invalid response from shell.run for git apply")

                shell_run_output = json.loads(git_mcp_result[0].text)
                shell_result = ShellRunResult(**shell_run_output)

                if shell_result.return_code != 0:
                    return ApplyPatchOutput(
                        ok=False,
                        file_path_hint=file_path_in_repo,
                        message=f"'git apply' failed for {file_path_in_repo}. Review the file and try again.",
                        details=shell_result,
                    )

            except (McpError, ToolError) as e:
                error_message = e.message if hasattr(e, 'message') else e.args[0]
                return ApplyPatchOutput(
                    ok=False,
                    file_path_hint=file_path_in_repo,
                    message=f"MCP Error applying patch: {error_message}",
                )

            # 3. Clean up the temporary patch file (finally block ensures this runs)
            finally:
                try:
                    await session.call_tool("fs.remove", {"path": temp_patch_filename})
                    logger.info(f"Removed temporary patch file: {temp_patch_filename}")
                except (McpError, ToolError) as e:
                    logger.warning(f"Failed to remove temporary patch file '{temp_patch_filename}': {e}")

        return ApplyPatchOutput(
            ok=True,
            file_path_hint=file_path_in_repo,
            message=f"Patch applied successfully to '{file_path_in_repo}'.",
            details=shell_result,
        )

    except Exception as e:
        logger.error(f"An unexpected error occurred during apply_patch: {e}", exc_info=True)
        return ApplyPatchOutput(
            ok=False,
            file_path_hint=file_path_in_repo,
            message=f"An unexpected error occurred during apply_patch: {e}",
        )

