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
    # Determine the absolute path for the workspace repository
    # This assumes the script is run from a location where this relative path is valid.
    # In the context of the agent, this path is configured to be correct.
    repo_root = Path.cwd() / 'workspace_dev'

    logger.info(f"Tool: apply_patch called for file hint: '{file_path_in_repo}'")

    if not diff_content:
        return ApplyPatchOutput(ok=False, message='Patch content is empty.')

    # Clean up patch content
    diff_content = diff_content.strip().replace('\r\n', '\n') + '\n'
    diff_content = re.sub(r"^index .*$\n", "", diff_content, flags=re.MULTILINE)

    # Check if this is a new file patch
    is_new_file = diff_content.startswith('--- /dev/null')

    if is_new_file:
        try:
            # Extract the new file path from the '+++' line
            match = re.search(r'^\+\+\+ b/(.*)$', diff_content, re.MULTILINE)
            if not match:
                return ApplyPatchOutput(ok=False, message="Could not parse new file path from patch.")
            
            new_file_path_str = match.group(1)
            new_file_path = repo_root / new_file_path_str

            # Create parent directories if they don't exist
            new_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Extract the content to be written
            lines = diff_content.split('\n')
            # Skip header lines (---, +++, @@)
            content_lines = [line[1:] for line in lines if line.startswith('+') and not line.startswith('+++')]
            file_content = '\n'.join(content_lines) + '\n'

            # Write the content to the new file
            with open(new_file_path, 'w') as f:
                f.write(file_content)

            logger.info(f"Successfully created new file via patch: {new_file_path_str}")
            return ApplyPatchOutput(ok=True, message=f"Successfully created new file: {new_file_path_str}")
        except Exception as e:
            logger.error(f"Error creating new file from patch: {e}", exc_info=True)
            return ApplyPatchOutput(ok=False, message=f"Error creating new file from patch: {e}")

    # If it's not a new file, proceed with the existing git apply logic
    try:
        # Always run git commands from the repository root and use -p1 strip level.
        git_cwd = None  # Run at repo root
        p_level = 1

        # 1. Make git aware of all files, including new ones, and stage their content.
        add_result = await run_shell.ainvoke({
            "command": "git add --all",
            "working_directory_relative_to_repo": git_cwd
        })
        if not add_result.ok:
            return ApplyPatchOutput(ok=False, message=f"Failed to stage files for patching: {add_result.stderr}")

        # 2. Dry-run the patch via stdin to check for validity.
        check_command = f"git apply -p{p_level} --check --whitespace=nowarn -"
        check_result = await run_shell.ainvoke({
            "command": check_command,
            "stdin": diff_content,
            "working_directory_relative_to_repo": git_cwd
        })

        if not check_result.ok:
            return ApplyPatchOutput(ok=False, message=f"Patch check failed: {check_result.stderr}")

        # 3. Apply the patch for real using stdin, updating the index and working directory.
        apply_command = f"git apply -p{p_level} --index --verbose --whitespace=nowarn -"
        apply_result = await run_shell.ainvoke({
            "command": apply_command,
            "stdin": diff_content,
            "working_directory_relative_to_repo": git_cwd
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
    """Applies a git-style patch to the workspace.

    Args:
        file_path_in_repo: A representative file path for the patch, used for logging. The patch content itself determines which files are modified.
        diff_content: The content of the diff/patch to apply, in unidiff format.
    """
    logger.info(f"Tool: apply_patch called for file hint: '{file_path_in_repo}'")

    if not diff_content:
        return ApplyPatchOutput(ok=False, message='Patch content is empty.')

    try:
        # Clean up patch content to avoid common errors from LLM generation.
        # - Strip leading/trailing whitespace.
        # - Ensure it ends with a single newline.
        # - Remove git's internal `index` lines, which can be unreliable.
        diff_content = diff_content.strip() + '\n'
        diff_content = re.sub(r"^index .*$\n", "", diff_content, flags=re.MULTILINE)

        # Always run git commands from the repository root and use -p1 strip level.
        git_cwd = None  # Run at repo root
        p_level = 1

        # 1. Make git aware of all files, including new ones, and stage their content.
        add_result = await run_shell.ainvoke({
            "command": "git add --all",
            "working_directory_relative_to_repo": git_cwd
        })
        if not add_result.ok:
            return ApplyPatchOutput(ok=False, message=f"Failed to stage files for patching: {add_result.stderr}")

        # 2. Dry-run the patch via stdin to check for validity.
        check_command = f"git apply -p{p_level} --check --whitespace=nowarn -"
        check_result = await run_shell.ainvoke({
            "command": check_command,
            "stdin": diff_content,
            "working_directory_relative_to_repo": git_cwd
        })

        if not check_result.ok:
            return ApplyPatchOutput(ok=False, message=f"Patch check failed: {check_result.stderr}")

        # 3. Apply the patch for real using stdin, updating the index and working directory.
        apply_command = f"git apply -p{p_level} --index --verbose --whitespace=nowarn -"
        apply_result = await run_shell.ainvoke({
            "command": apply_command,
            "stdin": diff_content,
            "working_directory_relative_to_repo": git_cwd
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
