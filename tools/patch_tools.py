import logging
import re
from pathlib import Path
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from tools.shell_mcp_tools import run_shell

logger = logging.getLogger(__name__)


class ApplyPatchOutput(BaseModel):
    ok: bool = Field(description="True if the patch was applied successfully, False otherwise.")
    message: str = Field(description="A summary message indicating success or failure.")


class ApplyPatchInput(BaseModel):
    """Input for the apply_patch tool."""
    file_path_in_repo: str = Field(
        description="A representative file path for the patch, used for logging. The patch content itself determines which files are modified.",
    )
    diff_content: str = Field(description="The content of the diff/patch to apply, in unidiff format.")


@tool(args_schema=ApplyPatchInput)
async def apply_patch(file_path_in_repo: str, diff_content: str) -> ApplyPatchOutput:
    """
    Applies a patch to files in the repository workspace using a robust, git-based workflow.
    This tool first stages all files (including new ones), then checks the patch,
    and finally applies it. It uses stdin to avoid temporary files.
    """
    logger.info(f"Tool: apply_patch called for file hint: '{file_path_in_repo}'")

    try:
        # Ensure diff content ends with a newline for git apply robustness
        if not diff_content.endswith("\n"):
            diff_content += "\n"

        # The LLM can generate unreliable index lines; remove them to improve robustness.
        diff_content = re.sub(r"^index .*\n", "", diff_content, flags=re.MULTILINE)
        
        # Determine the correct working directory and patch stripping level.
        path_parts = Path(file_path_in_repo).parts
        project_subdirectory = None
        p_level = 0
        if len(path_parts) > 1:
            project_subdirectory = path_parts[0]
            # The diff paths are relative to the repo root, e.g., "my-app/src/file.ts".
            # When we run git apply inside "my-app", we need to strip "my-app/"
            p_level = 1
        
        logger.info(f"Determined project_subdirectory: '{project_subdirectory}', p-level: {p_level}")

        # 1. Make git aware of all files, including new ones, and stage their content.
        # This command must run inside the subdirectory where the .git folder is.
        add_result = await run_shell.ainvoke({
            "command": "git add --all", 
            "working_directory_relative_to_repo": project_subdirectory
        })
        if not add_result.ok:
            return ApplyPatchOutput(ok=False, message=f"Failed to stage files for patching: {add_result.stderr}")

        # 2. Dry-run the patch via stdin to check for validity.
        # Use -p<n> to strip leading path components from the diff.
        check_command = f"git apply -p{p_level} --check --whitespace=nowarn -"
        check_result = await run_shell.ainvoke({
            "command": check_command, 
            "stdin": diff_content, 
            "working_directory_relative_to_repo": project_subdirectory
        })

        if not check_result.ok:
            return ApplyPatchOutput(ok=False, message=f"Patch check failed: {check_result.stderr}")

        # 3. Apply the patch for real using stdin, updating the index and working directory.
        apply_command = f"git apply -p{p_level} --index --verbose --whitespace=nowarn -"
        apply_result = await run_shell.ainvoke({
            "command": apply_command, 
            "stdin": diff_content, 
            "working_directory_relative_to_repo": project_subdirectory
        })

        if not apply_result.ok:
            return ApplyPatchOutput(ok=False, message=f"Patch application failed: {apply_result.stderr}")

        logger.info(f"Patch applied successfully to '{file_path_in_repo}'.")
        return ApplyPatchOutput(ok=True, message=f"Patch applied successfully to '{file_path_in_repo}'.")
    except Exception as e:
        logger.error(f"Unexpected error during apply_patch: {e}", exc_info=True)
        return ApplyPatchOutput(
            ok=False,
            message=f"Unexpected error: {e}",
        )

