import logging
from typing import Dict, Any, Optional
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.lsp_manager import get_lsp_manager
from common.config import settings

logger = logging.getLogger(__name__)

class LspInput(BaseModel):
    file_path: str = Field(description="The path to the file. If project_subdirectory is provided, this path is relative to that subdirectory; otherwise, it's relative to the repository root.")
    line: int = Field(description="The line number in the file (0-indexed).")
    character: int = Field(description="The character number in the line (0-indexed).")
    project_subdirectory: Optional[str] = Field(default=None, description="Optional project subdirectory within the repository. If provided, this is the LSP workspace root, and file_path is relative to it.")

@tool(args_schema=LspInput)
async def lsp_definition(file_path: str, line: int, character: int, project_subdirectory: Optional[str] = None) -> Dict[str, Any]:
    """Finds the definition of a symbol in the code using the Language Server."""
    repo_dir = Path(settings.REPO_DIR)
    workspace_path = repo_dir / project_subdirectory if project_subdirectory else repo_dir
    
    manager = await get_lsp_manager(workspace_path)
    await manager.start() # Ensure the LSP server is running
    
    # file_path is now relative to workspace_path as per LLM's instruction based on prompt
    absolute_file_path = workspace_path / file_path
    file_uri = absolute_file_path.as_uri()

    logger.info(f"Getting definition for {file_uri} (workspace: {workspace_path}) at {line}:{character}")
    return await manager.get_definition(file_uri, line, character)

@tool(args_schema=LspInput)
async def lsp_hover(file_path: str, line: int, character: int, project_subdirectory: Optional[str] = None) -> Dict[str, Any]:
    """Gets hover information for a symbol in the code using the Language Server."""
    repo_dir = Path(settings.REPO_DIR)
    workspace_path = repo_dir / project_subdirectory if project_subdirectory else repo_dir

    manager = await get_lsp_manager(workspace_path)
    await manager.start() # Ensure the LSP server is running

    # file_path is now relative to workspace_path as per LLM's instruction based on prompt
    absolute_file_path = workspace_path / file_path
    file_uri = absolute_file_path.as_uri()

    logger.info(f"Getting hover for {file_uri} (workspace: {workspace_path}) at {line}:{character}")
    return await manager.get_hover(file_uri, line, character)

class LspWorkspaceConfigInput(BaseModel):
    project_subdirectory: Optional[str] = Field(default=None, description="Optional project subdirectory within the repository. If provided, this is the LSP workspace root.")

@tool(args_schema=LspWorkspaceConfigInput)
async def lsp_workspace_config_check(project_subdirectory: Optional[str] = None) -> str:
    """Checks for workspace configuration changes (e.g., tsconfig.json updates) and restarts the LSP server if necessary."""
    repo_dir = Path(settings.REPO_DIR)
    workspace_path = repo_dir / project_subdirectory if project_subdirectory else repo_dir
    
    manager = await get_lsp_manager(str(workspace_path)) # Ensure workspace_path is string for manager key
    await manager.start() # Ensure the LSP server is running before checking config

    logger.info(f"Checking workspace config for {workspace_path} and restarting LSP if needed.")
    await manager.check_and_restart_on_tsconfig_update()
    return f"LSP workspace config check complete for {workspace_path}. Server restarted if tsconfig.json was updated."
