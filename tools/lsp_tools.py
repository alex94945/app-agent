import logging
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Pydantic Schemas for Tool Inputs ---

class LspInput(BaseModel):
    file_path_in_repo: str = Field(description="The path to the file within the repository.")
    line: int = Field(description="The line number in the file (0-indexed).")
    character: int = Field(description="The character number in the line (0-indexed).")

class DiagnosticsInput(BaseModel):
    file_path_in_repo: Optional[str] = Field(
        default=None, 
        description="The path to a specific file to get diagnostics for. If None, returns for all files."
    )

# --- Tool Implementations (Stubs) ---

@tool(args_schema=LspInput)
async def lsp_definition(file_path_in_repo: str, line: int, character: int) -> Dict[str, Any]:
    """
    (STUB) Finds the definition of a symbol in the code.
    """
    logger.info(f"(STUB) lsp_definition called for {file_path_in_repo}:{line}:{character}")
    return {
        "uri": f"file://{file_path_in_repo}",
        "range": {
            "start": {"line": line, "character": character},
            "end": {"line": line, "character": character + 5}
        },
        "comment": "This is a stubbed response."
    }

@tool(args_schema=LspInput)
async def lsp_hover(file_path_in_repo: str, line: int, character: int) -> Dict[str, Any]:
    """
    (STUB) Gets hover information for a symbol in the code.
    """
    logger.info(f"(STUB) lsp_hover called for {file_path_in_repo}:{line}:{character}")
    return {
        "contents": [
            {"language": "typescript", "value": "(STUB) const mySymbol: string"},
            "This is a stubbed hover response."
        ]
    }

@tool(args_schema=DiagnosticsInput)
async def get_diagnostics(file_path_in_repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    (STUB) Gets diagnostic information (errors, warnings) for files.
    """
    logger.info(f"(STUB) get_diagnostics called for: {file_path_in_repo or 'all files'}")
    # Return an empty list as per the implementation plan for the stub.
    return []
