import logging
from typing import Dict, Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.lsp_manager import get_lsp_manager
from common.config import settings

logger = logging.getLogger(__name__)

class LspInput(BaseModel):
    file_path_in_repo: str = Field(description="The path to the file within the repository.")
    line: int = Field(description="The line number in the file (0-indexed).")
    character: int = Field(description="The character number in the line (0-indexed).")

@tool(args_schema=LspInput)
async def lsp_definition(file_path_in_repo: str, line: int, character: int) -> Dict[str, Any]:
    """Finds the definition of a symbol in the code using the Language Server."""
    repo_path = str(settings.REPO_DIR)
    manager = get_lsp_manager(repo_path)
    full_path = f"{repo_path}/{file_path_in_repo}"
    logger.info(f"Getting definition for {full_path}:{line}:{character}")
    return await manager.get_definition(full_path, line, character)

@tool(args_schema=LspInput)
async def lsp_hover(file_path_in_repo: str, line: int, character: int) -> Dict[str, Any]:
    """Gets hover information for a symbol in the code using the Language Server."""
    repo_path = str(settings.REPO_DIR)
    manager = get_lsp_manager(repo_path)
    full_path = f"{repo_path}/{file_path_in_repo}"
    logger.info(f"Getting hover for {full_path}:{line}:{character}")
    return await manager.get_hover(full_path, line, character)
