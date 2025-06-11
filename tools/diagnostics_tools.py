# /tools/diagnostics_tools.py

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.lsp_manager import get_lsp_manager
from common.config import settings

logger = logging.getLogger(__name__)

class DiagnosticsInput(BaseModel):
    file_path: Optional[str] = Field(
        default=None, 
        description="The path to a specific file to get diagnostics for. If project_subdirectory is provided, this path is relative to that subdirectory; otherwise, it's relative to the repository root. If None, returns for all files in the workspace."
    )
    project_subdirectory: Optional[str] = Field(default=None, description="Optional project subdirectory within the repository. If provided, this is the LSP workspace root, and file_path is relative to it.")

@tool(args_schema=DiagnosticsInput)
async def get_diagnostics(file_path: Optional[str] = None, project_subdirectory: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gets diagnostic information (errors, warnings) for files from the Language Server."""
    repo_dir = Path(settings.REPO_DIR)
    workspace_path = repo_dir / project_subdirectory if project_subdirectory else repo_dir

    manager = await get_lsp_manager(workspace_path)
    await manager.start() # Ensure the LSP server is running

    if file_path:
        # file_path is now relative to workspace_path as per LLM's instruction based on prompt
        absolute_file_path = workspace_path / file_path
        file_uri = absolute_file_path.as_uri()
        logger.info(f"Getting diagnostics for {file_uri} (workspace: {workspace_path})")
        return await manager.get_diagnostics(file_uri)
    else:
        logger.info(f"Getting all diagnostics for workspace: {workspace_path}")
        return await manager.get_all_diagnostics()
