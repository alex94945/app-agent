# tests/conftest.py


import sys
from pathlib import Path

# Add the project root directory to the system path to ensure
# modules like 'common' and 'agent' can be imported in tests.
# The project root is two levels up from this file (tests/conftest.py).

def pytest_addoption(parser):
    parser.addoption(
        "--save-app",
        action="store_true",
        default=False,
        help="Save the generated E2E app to ./workspace_dev instead of a temp directory.",
    )
    parser.addoption(
        "--streaming",
        action="store_true",
        default=False,
        help="Enable streaming output for live E2E shell commands.",
    )
    # Add --prompts option only if not already added by a sub-package conftest
    try:
        parser.addoption(
            "--prompts",
            action="append",
            default=[],
            help="Comma-separated list of prompts (or @path/to/file.txt) to feed the live E2E test",
        )
    except ValueError:
        # Option already registered (e.g., by tests/live_e2e/conftest.py). Ignore.
        pass

project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import pytest_asyncio # Added for async fixtures
import asyncio
from typing import AsyncIterator, Optional, List
from contextlib import asynccontextmanager
from unittest.mock import patch

from fastmcp import Client, FastMCP
from pydantic import BaseModel, Field
from mcp.shared.exceptions import McpError, ErrorData

# Custom MCP Error Codes (integers)
RESOURCE_NOT_FOUND_CODE = -32010
IS_A_DIRECTORY_ERROR_CODE = -32011
PERMISSION_DENIED_CODE = -32012
NOT_A_DIRECTORY_CODE = -32013
GENERIC_TOOL_ERROR_CODE = -32003 # Consistent with other tests


# --- Helper Functions ---

@asynccontextmanager
async def mock_mcp_session_cm(client_to_yield: Client) -> AsyncIterator[Client]:
    """
    A reusable async context manager to mock common.mcp_session.open_mcp_session.

    Yields the provided FastMCP client instance.
    """
    yield client_to_yield



@pytest.fixture(scope="session")
def agent_graph_fixture():
    """
    Returns a factory that builds and compiles the agent graph with optional custom tools.
    Usage: agent_graph = agent_graph_fixture(tools=...) in tests.
    """
    from functools import partial
    from agent.agent_graph import planner_reason_step, tool_executor_step, build_agent_graph

    def _build_agent_graph_with_tools(tools: list) -> "StateGraph":
        """
        Builds the agent graph with a custom set of tools.
        This replaces the default planner and tool executor with instrumented versions.
        It's a bit of a hack, but it allows us to test the graph with a controlled
        set of tools without rewriting the graph construction logic.
        """
        # Use functools.partial to create new functions with the 'tools_for_test'
        # argument already filled in. This is the modern way to configure nodes
        # without modifying them after they've been added to the graph.
        mock_planner = partial(planner_reason_step, tools_for_test=tools)
        mock_executor = partial(tool_executor_step, tools_for_test=tools)

        # Build the graph, but replace the node functions with our partials.
        # This is a bit of a workaround to avoid rewriting the graph builder.
        graph = build_agent_graph()
        graph.nodes['planner'] = mock_planner
        graph.nodes['tool_executor'] = mock_executor
        return graph

    return _build_agent_graph_with_tools


@pytest.fixture
def fix_cycle_tracker():
    """Provides a default FixCycleTracker instance for tests."""
    from agent.executor.fix_cycle import FixCycleTracker
    return FixCycleTracker()


# --- Pydantic Schemas for Tool Outputs ---

class _ShellRunOutput(BaseModel):
    stdout: str
    stderr: str
    return_code: int

class _DirEntry(BaseModel):
    name: str
    type: str  # "file" or "directory"


# --- Pytest Plugins --- 

# This was moved from tests/integration/conftest.py to fix a pytest collection error.
# It ensures that integration-specific fixtures are loaded correctly.
pytest_plugins = ["tests.integration.pytest_plugins"]

# --- FastMCP Server for File I/O Tools ---

def build_file_io_tools_server() -> FastMCP:
    server = FastMCP("FileToolsTestServer")

    @server.tool(name="fs.read")
    async def actual_fs_read(path: str) -> str:
        try:
            # Use asyncio.to_thread to run synchronous file I/O in a separate thread
            content = await asyncio.to_thread(Path(path).read_text, encoding='utf-8')
            return content
        except FileNotFoundError:
            raise McpError(ErrorData(code=RESOURCE_NOT_FOUND_CODE, message=f"File not found: {path}"))
        except Exception as e:
            raise McpError(ErrorData(code=GENERIC_TOOL_ERROR_CODE, message=f"Error reading file {path}: {str(e)}"))

    @server.tool(name="fs.write")
    async def actual_fs_write(path: str, content: str) -> None:
        try:
            target_path = Path(path)
            # Ensure parent directory exists
            await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target_path.write_text, content, encoding='utf-8')
            return None  # MCP fs.write usually returns no content on success
        except IsADirectoryError as e:
            raise McpError(ErrorData(code=IS_A_DIRECTORY_ERROR_CODE, message=f"Error writing file {path}: {str(e)}"))
        except Exception as e:
            raise McpError(ErrorData(code=GENERIC_TOOL_ERROR_CODE, message=f"Error writing file {path}: {str(e)}"))

    @server.tool(name="fs.list_dir")
    async def actual_fs_list_dir(path: str) -> List[_DirEntry]:
        try:
            dir_path = Path(path)
            if not await asyncio.to_thread(dir_path.exists):
                raise McpError(ErrorData(code=RESOURCE_NOT_FOUND_CODE, message=f"Directory not found: {path}"))
            if not await asyncio.to_thread(dir_path.is_dir):
                raise McpError(ErrorData(code=NOT_A_DIRECTORY_CODE, message=f"Path is not a directory: {path}"))

            entries = []
            # Path.iterdir() is synchronous, so wrap it
            for item in await asyncio.to_thread(list, dir_path.iterdir()): # list() to exhaust iterator in thread
                item_type = "directory" if await asyncio.to_thread(item.is_dir) else "file"
                entries.append(_DirEntry(name=item.name, type=item_type))
            return entries
        except PermissionError as e:
            raise McpError(ErrorData(code=PERMISSION_DENIED_CODE, message=f"Permission denied: {path}"))
        except McpError: # Re-raise McpErrors directly
            raise
        except Exception as e:
            raise McpError(ErrorData(code=GENERIC_TOOL_ERROR_CODE, message=f"Error listing directory {path}: {str(e)}"))

    return server

# --- Pytest Fixture for the File I/O Client ---

@pytest_asyncio.fixture
async def file_io_client() -> AsyncIterator[Client]:
    server = build_file_io_tools_server()
    async with Client(server) as c:
        yield c


# --- FastMCP Server for Patch Tools ---

def build_patch_tools_server() -> FastMCP:
    """Builds a FastMCP server with the tools needed for apply_patch."""
    server = FastMCP("PatchToolsTestServer")

    # --- Tool Implementations (reused from other builders for consistency) ---

    @server.tool(name="fs.write")
    async def actual_fs_write(path: str, content: str) -> None:
        try:
            target_path = Path(path)
            await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target_path.write_text, content, encoding='utf-8')
            return None
        except IsADirectoryError as e:
            raise McpError(ErrorData(code=IS_A_DIRECTORY_ERROR_CODE, message=f"Error writing file {path}: {str(e)}"))
        except Exception as e:
            raise McpError(ErrorData(code=GENERIC_TOOL_ERROR_CODE, message=f"Error writing file {path}: {str(e)}"))

    @server.tool(name="fs.remove")
    async def actual_fs_remove(path: str) -> None:
        try:
            await asyncio.to_thread(Path(path).unlink)
            return None
        except FileNotFoundError:
            # This is not a critical error for cleanup, but we raise for testability
            raise McpError(ErrorData(code=RESOURCE_NOT_FOUND_CODE, message=f"File not found for removal: {path}"))
        except Exception as e:
            raise McpError(ErrorData(code=GENERIC_TOOL_ERROR_CODE, message=f"Error removing file {path}: {str(e)}"))

    @server.tool(name="shell.run")
    async def actual_shell_run(command: str, cwd: Optional[str] = None, stdin: Optional[str] = None, json: bool = False):
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            stdout_bytes, stderr_bytes = await proc.communicate(input=stdin.encode() if stdin else None)

            stdout = stdout_bytes.decode().strip() if stdout_bytes else ""
            stderr = stderr_bytes.decode().strip() if stderr_bytes else ""
            return_code = proc.returncode if proc.returncode is not None else -1

            result_obj = _ShellRunOutput(stdout=stdout, stderr=stderr, return_code=return_code)
            if json:
                return result_obj.model_dump()
            return result_obj
        except Exception as e:
            return _ShellRunOutput(
                stdout="",
                stderr=f"Error in actual_shell_run: {str(e)}",
                return_code=-1
            )

    return server

# --- Pytest Fixture for the Shell Client ---

@pytest_asyncio.fixture
async def shell_client() -> AsyncIterator[Client]:
    """Yields a FastMCP Client connected to a server with a shell.run tool using _ShellRunOutput schema."""
    server = FastMCP("ShellToolsTestServer")

    @server.tool(name="shell.run")
    async def actual_shell_run(command: str, cwd: Optional[str] = None, stdin: Optional[str] = None, json: bool = False):
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            stdout_bytes, stderr_bytes = await proc.communicate(input=stdin.encode() if stdin else None)
            stdout = stdout_bytes.decode().strip() if stdout_bytes else ""
            stderr = stderr_bytes.decode().strip() if stderr_bytes else ""
            return_code = proc.returncode if proc.returncode is not None else -1
            result_obj = _ShellRunOutput(stdout=stdout, stderr=stderr, return_code=return_code)
            if json:
                return result_obj.model_dump()
            return result_obj
        except Exception as e:
            return _ShellRunOutput(
                stdout="",
                stderr=f"Error in actual_shell_run: {str(e)}",
                return_code=-1
            )
    async with Client(server) as c:
        yield c

# --- Pytest Fixture for the Patch Client ---

@pytest_asyncio.fixture
async def patch_client() -> AsyncIterator[Client]:
    server = build_patch_tools_server()
    async with Client(server) as c:
        yield c

