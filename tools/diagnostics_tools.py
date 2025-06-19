# /tools/diagnostics_tools.py

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
import asyncio

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from common.config import settings
from agent.lsp_manager import get_lsp_manager
from lsprotocol import types as lsp_types # Removed converters import

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

    # Always ensure the manager is running
    if not manager.client or manager.client.stopped:
        logger.info(f"LSP client for {workspace_path} not running, starting it.")
        await manager.start()
        await asyncio.sleep(1) # Give it a moment to initialize

    if file_path:
        # Ensure file_path is relative to the workspace path for the LSP server
        absolute_file_path = workspace_path / file_path
        
        # Explicitly tell the server to open the document to trigger analysis
        await manager.open_document(str(absolute_file_path))
        
        # Give the server a moment to process the didOpen and generate diagnostics
        await asyncio.sleep(1) # Increased from 0.5 to 1, consider making configurable or dynamic
        
        # Wait for diagnostics to be published
        await manager.wait_for_diagnostics(str(absolute_file_path), timeout=10.0)

        diagnostic_objects = await manager.get_diagnostics(str(absolute_file_path))
    else:
        # This branch might be less reliable without opening specific files, but we'll keep it.
        diagnostic_objects = await manager.get_all_diagnostics()

    # Convert Diagnostic Pydantic models to JSON-serializable dictionaries
    serializable_diagnostics = []
    for d in diagnostic_objects:
        if isinstance(d, lsp_types.Diagnostic):
            try:
                raw_dump = d.model_dump(mode='json')
                clean_dump = _to_json_safe(raw_dump)
                serializable_diagnostics.append(clean_dump)
            except Exception as e:
                logger.error(f"Error serializing or sanitizing a diagnostic object: {d}. Error: {e}")
                # Optionally, append a placeholder or skip
        else:
            logger.warning(f"Skipping non-Diagnostic object in diagnostics list: {type(d)}")

    logger.info(f"Retrieved {len(serializable_diagnostics)} serializable diagnostics for {file_path or 'all files'} in {workspace_path}")

    if logger.isEnabledFor(logging.DEBUG):
        try:
            import json, itertools
            preview = list(itertools.islice(serializable_diagnostics, 3))
            logger.debug("Sanitized diagnostics preview:\n%s", json.dumps(preview, indent=2))
        except Exception as e:
            logger.debug("Could not preview sanitized diagnostics: %s", e)

    return serializable_diagnostics

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


def _to_json_safe(obj, _path="root"):
    """
    Recursively convert any object to something that survives json.dumps.
    Non-serialisable objects become their repr(); lists / dicts are
    walked depth-first to strip surprises such as asyncio.StreamReader.
    """
    import json, typing, collections.abc, datetime, decimal, uuid # type: ignore
    basic = (str, int, float, bool, type(None))
    if isinstance(obj, basic):
        return obj
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, (decimal.Decimal, uuid.UUID)):
        return str(obj)
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_to_json_safe(i, f"{_path}[]") for i in obj]
    if isinstance(obj, dict):
        return {k: _to_json_safe(v, f"{_path}.{k}") for k, v in obj.items()}
    # Anything else → string fallback **with type hint** so it’s inspectable later
    logger.warning(f"_to_json_safe: Replaced non-serializable object of type {type(obj).__name__} at path {_path} with its string representation.")
    return f"<<non-serialisable:{type(obj).__name__} at {_path}>>"

