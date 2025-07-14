# tools/scaffold_tool.py
import logging
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from tools.shell_mcp_tools import run_shell, RunShellOutput

logger = logging.getLogger(__name__)

class ScaffoldProjectInput(BaseModel):
    project_name: str = Field(description="The name of the project to create, which will also be the directory name.")

class ScaffoldProjectOutput(BaseModel):
    ok: bool = Field(description="True if the scaffolding was successful, False otherwise.")
    project_subdirectory: str = Field(description="The name of the directory where the project was created.")
    message: str = Field(description="A summary of the result.")

@tool(args_schema=ScaffoldProjectInput)
async def scaffold_project(project_name: str) -> ScaffoldProjectOutput:
    """
    Creates a new Next.js project with a given name using the recommended settings.
    This should be the very first tool called when starting a new project.
    """
    logger.info(f"Tool: scaffold_project called for project_name: '{project_name}'")
    
    command = f"npx create-next-app@latest {project_name} --typescript --tailwind --eslint --app --src-dir --import-alias '@/*'"
    
    # We can call our existing run_shell tool internally
    shell_result: RunShellOutput = await run_shell.ainvoke({
        "command": command,
        # Scaffolding should always happen at the root of the workspace
        "working_directory_relative_to_repo": None 
    })

    if not shell_result.ok:
        return ScaffoldProjectOutput(
            ok=False,
            project_subdirectory=project_name,
            message=f"Failed to scaffold project. Stderr: {shell_result.stderr}"
        )

    return ScaffoldProjectOutput(
        ok=True,
        project_subdirectory=project_name,
        message=f"Project '{project_name}' scaffolded successfully."
    )