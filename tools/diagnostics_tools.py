# /tools/diagnostics_tools.py

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from common.config import settings
from agent.lsp_manager import get_lsp_manager

logger = logging.getLogger(__name__)

class DiagnosticsInput(BaseModel):
    file_path: Optional[str] = Field(
        default=None, 
        description="The path to a specific file to get diagnostics for. If project_subdirectory is provided, this path is relative to that subdirectory; otherwise, it's relative to the repository root. If None, returns for all files in the workspace."
    )
    project_subdirectory: Optional[str] = Field(default=None, description="Optional project subdirectory within the repository. If provided, this is the LSP workspace root, and file_path is relative to it.")

@tool(args_schema=DiagnosticsInput)
async def get_diagnostics(file_path: Optional[str] = None, project_subdirectory: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Gets diagnostic information (errors, warnings) for a specific file or the entire project
    from the Language Server Protocol (LSP).
    """
    # For now, our LSP is TypeScript-only.
    if file_path and not (file_path.endswith(".ts") or file_path.endswith(".tsx")):
        logger.warning(f"get_diagnostics called on unsupported file type: {file_path}. Returning empty list.")
        return []
    # Simple guard to avoid running on non-TS/JS files for now
    supported_suffixes = ['.ts', '.tsx', '.js', '.jsx']
    if file_path and Path(file_path).suffix not in supported_suffixes:
        logger.warning(f"get_diagnostics called on unsupported file type: {file_path}. Returning empty list.")
        return []
    repo_dir = Path(settings.REPO_DIR)
    workspace_path = repo_dir / project_subdirectory if project_subdirectory else repo_dir
    manager = await get_lsp_manager(str(workspace_path))
    if not manager.client or not manager.client.is_running:
        logger.info(f"LSP client for {workspace_path} not running, starting it for diagnostics.")
        await manager.start()

    if file_path:
        # Ensure file_path is relative to the workspace path for the LSP server
        absolute_file_path = workspace_path / file_path
        diagnostics = await manager.get_diagnostics(str(absolute_file_path))
    else:
        diagnostics = await manager.get_all_diagnostics()

    # The diagnostics from pygls are already in a serializable format (dicts)
    # so we can return them directly.
    logger.info(f"Retrieved {len(diagnostics)} diagnostics for {file_path or 'all files'} in {workspace_path}")
    return [diag.model_dump() for diag in diagnostics]

@tool(args_schema=DiagnosticsInput)
async def diagnose(file_path: Optional[str] = None, project_subdirectory: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Diagnoses issues, especially code errors, by retrieving diagnostic information from the Language Server.
    This tool is a proxy for get_diagnostics and is intended for use in self-healing loops.
    """
    logger.info(f"Tool: diagnose called for file_path: {file_path}, project_subdirectory: {project_subdirectory}")
    return await get_diagnostics.ainvoke({
        "file_path": file_path, 
        "project_subdirectory": project_subdirectory
    })

