import logging
import uuid
import json
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from pathlib import Path
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
    Applies a patch to files in the repository workspace using `git apply`.

    Simplified implementation: stream the diff content to `git apply -` via stdin
    in a single `shell.run` call, requesting structured JSON output.
    """

    logger.info(f"Tool: apply_patch called for file hint: '{file_path_in_repo}'")
    logger.debug(f"Patch content received for '{file_path_in_repo}':\n{diff_content}")

    try:
        async with open_mcp_session() as session:
            # Stream diff via stdin, ask for JSON response
            shell_payload = {
                "command": "git apply --verbose -",
                "stdin": diff_content if diff_content.endswith("\n") else diff_content + "\n",
                "json": True,
                "cwd": str(settings.REPO_DIR),
            }
            logger.info("Applying patch via stdin with git apply …")

            def _normalize_shell_run_result(raw) -> dict:
                """Handle both new (dict) and legacy ([TextContent]) responses."""
                if isinstance(raw, dict):
                    return raw
                # Legacy: list with TextContent whose .text is JSON
                try:
                    from mcp.types import TextContent as _TC
                except Exception:
                    _TC = None
                if (
                    isinstance(raw, list)
                    and raw
                    and (hasattr(raw[0], "text") or (_TC and isinstance(raw[0], _TC)))
                ):
                    return json.loads(raw[0].text)
                raise TypeError(f"Unexpected shell.run result type: {type(raw)}")
            raw_result = await session.call_tool("shell.run", shell_payload)
            try:
                result = _normalize_shell_run_result(raw_result)
            except Exception as e:
                logger.error(f"Unable to parse shell.run response: {e}")
                return ApplyPatchOutput(
                    ok=False,
                    file_path_hint=file_path_in_repo,
                    message="Invalid response from shell.run for git apply",
                )

            # `json=True` means `result` should already be a plain dict
            if not isinstance(result, dict):
                logger.error("shell.run did not return a JSON dict as expected")
                return ApplyPatchOutput(
                    ok=False,
                    file_path_hint=file_path_in_repo,
                    message="Invalid response from shell.run for git apply",
                )

            shell_result = ShellRunResult(**result)

            if shell_result.return_code != 0:
                # Legacy compatibility: map permission errors to old fs.write failure message
                if "Permission denied" in (shell_result.stderr or ""):
                    legacy_msg = "MCP Error writing temporary patch file"
                    return ApplyPatchOutput(
                        ok=False,
                        file_path_hint=file_path_in_repo,
                        message=f"{legacy_msg}: {shell_result.stderr.strip()}",
                        details=shell_result,
                    )
                logger.error(
                    f"'git apply' failed for '{file_path_in_repo}'. Return code: {shell_result.return_code}. Stderr: {shell_result.stderr}"
                )
                return ApplyPatchOutput(
                    ok=False,
                    file_path_hint=file_path_in_repo,
                    message=f"'git apply' failed for {file_path_in_repo}. Error: {shell_result.stderr or 'Unknown error'}",
                    details=shell_result,
                )

            logger.info("Patch applied successfully.")
            return ApplyPatchOutput(
                ok=True,
                file_path_hint=file_path_in_repo,
                message="Patch applied successfully.",
                details=shell_result,
            )

    except (McpError, ToolError) as e:
        err_msg = getattr(e, "message", str(e))
        logger.error(f"MCP/Tool error during apply_patch: {err_msg}")
        return ApplyPatchOutput(ok=False, file_path_hint=file_path_in_repo, message=err_msg)
    except Exception as e:
        logger.error(f"Unexpected error during apply_patch: {e}", exc_info=True)
        return ApplyPatchOutput(
            ok=False,
            file_path_hint=file_path_in_repo,
            message=f"Unexpected error: {e}",
        )

