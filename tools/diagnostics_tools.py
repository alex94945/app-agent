# /tools/diagnostics_tools.py

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools.shell_mcp_tools import run_shell
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
    """Gets diagnostic information for a file using CLI tools (flake8 or tsc). Falls back to empty list if no issues."""
    repo_dir = Path(settings.REPO_DIR)
    workspace_path = repo_dir / project_subdirectory if project_subdirectory else repo_dir

    diagnostics: List[Dict[str, Any]] = []
    if not file_path:
        return diagnostics  # Only single-file diagnostics supported in this lightweight path

    rel_cwd = str(workspace_path.relative_to(repo_dir)) if workspace_path != repo_dir else "."
    file_suffix = Path(file_path).suffix

    if file_suffix == ".py":
        cmd = f"flake8 {file_path}"
    elif file_suffix == ".ts":
        cmd = "tsc --noEmit --project tsconfig.json"
    else:
        # Unsupported extension
        return diagnostics

    shell_out = await run_shell.ainvoke({
        "command": cmd,
        "working_directory_relative_to_repo": rel_cwd,
    })

    if shell_out.ok:
        # No diagnostics
        return diagnostics

    output_lines = (shell_out.stdout or shell_out.stderr).splitlines()
    for line in output_lines:
        if file_suffix == ".py":
            # flake8 format: path:line:col: code message
            parts = line.split(":", 3)
            if len(parts) >= 4:
                diagnostics.append({
                    "file": parts[0].strip(),
                    "line": int(parts[1]),
                    "column": int(parts[2]),
                    "message": parts[3].strip(),
                })
        else:
            # crude parse for tsc output lines containing the file name
            if ".ts" in line:
                diagnostics.append({"message": line.strip()})
    return diagnostics

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

