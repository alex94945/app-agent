import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

class RunShellInput(BaseModel):
    command: str = Field(description="The shell command to execute.")
    working_directory_relative_to_repo: Optional[str] = Field(
        default=None, 
        description="The directory within the repo to run the command from."
    )

@tool(args_schema=RunShellInput)
def run_shell(command: str, working_directory_relative_to_repo: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes a shell command in the repository workspace.
    (STUB IMPLEMENTATION FOR TESTING)
    """
    logger.info(f"Tool STUB: run_shell called with command: '{command}' in dir: '{working_directory_relative_to_repo}'")
    # Return a mock successful response
    return {
        "stdout": f"Mock output for command: {command}",
        "stderr": "",
        "return_code": 0
    }
