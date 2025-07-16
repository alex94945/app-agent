"""A tool for initializing a new project from a template directory."""

import shutil
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# NOTE: These paths should ideally be loaded from a central configuration.
# For now, they are defined here relative to the project root.
WORKSPACE_ROOT = Path("./workspace_dev")
TEMPLATES_ROOT = Path("./templates")


class TemplateInitArgs(BaseModel):
    """Arguments for initializing a project from a template."""
    project_name: str = Field(description="The name of the new project directory to create.")
    template_name: str = Field(default="nextjs-base", description="The name of the template to use.")


@tool(args_schema=TemplateInitArgs)
def template_init(project_name: str, template_name: str = "nextjs-base") -> str:
    """
    Initializes a new project by copying a template directory.

    This tool copies a specified template from the `templates` directory into
    the workspace, creating a new project directory. It is the first step
    in setting up a new project.

    Args:
        project_name: The name of the new project directory to create.
        template_name: The name of the template to use (default: 'nextjs-base').

    Returns:
        The absolute path to the newly created project directory.

    Raises:
        FileNotFoundError: If the specified template directory does not exist.
        FileExistsError: If the destination project directory already exists.
    """
    template_dir = TEMPLATES_ROOT / template_name
    destination_dir = WORKSPACE_ROOT / project_name

    if not template_dir.is_dir():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    if destination_dir.exists():
        raise FileExistsError(f"Project directory already exists: {destination_dir}")

    shutil.copytree(template_dir, destination_dir)
    return str(destination_dir.resolve())
