# /tools/diagnostics_tools.py

import logging
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.lsp_manager import get_lsp_manager
from common.config import settings

logger = logging.getLogger(__name__)

class DiagnosticsInput(BaseModel):
    file_path_in_repo: Optional[str] = Field(
        default=None, 
        description="The path to a specific file to get diagnostics for. If None, returns for all files."
    )

@tool(args_schema=DiagnosticsInput)
async def get_diagnostics(file_path_in_repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gets diagnostic information (errors, warnings) for files from the Language Server."""
    repo_path = str(settings.REPO_DIR)
    manager = await get_lsp_manager(repo_path)
    await manager.start() # Ensure the LSP server is running

    if file_path_in_repo:
        logger.info(f"Getting diagnostics for: {file_path_in_repo}")
        full_path = f"{repo_path}/{file_path_in_repo}"
        return await manager.get_diagnostics(full_path)
    else:
        logger.info("Getting all diagnostics.")
        return await manager.get_all_diagnostics()
