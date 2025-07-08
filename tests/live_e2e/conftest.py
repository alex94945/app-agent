import pytest
import itertools
from pathlib import Path
import os
import threading
import uvicorn
import subprocess
from typing import Optional, List
import logging

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from common.config import get_settings
from tests.conftest import _ShellRunOutput

# This is a special, "fully real" MCP server for the live E2E test.
# Its tool implementations use real subprocesses and file system access, not mocks.
live_mcp_server = FastMCP(name="Live-E2E-MCP-Server")

# --- Tool Output Schemas ---


class _DirEntry(BaseModel):
    name: str
    type: str  # "file" or "directory"

# --- Real Tool Implementations ---

@live_mcp_server.tool(name="shell.run")
async def actual_shell_run(command: str, cwd: Optional[str] = None, stdin: Optional[str] = None) -> _ShellRunOutput:
    """This is a real shell command executor. It runs in the test's CWD."""
    logger = logging.getLogger("live_e2e.shell_tool")
    try:
        # subprocess.run resolves `cwd` relative to the current process's CWD.
        # Since the server is now function-scoped, this will be the correct temp dir.
        process = subprocess.run(
            command, shell=True, check=False, capture_output=True, text=True, cwd=cwd, input=stdin
        )
        logger.info(f"shell.run executed: {command} in {cwd or '.'}")
        return _ShellRunOutput(stdout=process.stdout, stderr=process.stderr, return_code=process.returncode)
    except Exception as e:
        logger.error(f"shell.run FAILED: {command} with exception: {e}")
        return _ShellRunOutput(stdout="", stderr=str(e), return_code=-1)

@live_mcp_server.tool(name="fs.write")
async def actual_fs_write(path: str, content: str) -> None:
    """This is a real file writer. It writes to the test's CWD."""
    logger = logging.getLogger("live_e2e.fs_tool")
    try:
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding='utf-8')
        logger.info(f"fs.write succeeded for path: {target_path.resolve()}")
    except Exception as e:
        logger.error(f"fs.write FAILED for path: {path}: {e}")
        raise  # Re-raise to let the agent handle the error

@live_mcp_server.tool(name="fs.read")
async def actual_fs_read(path: str) -> str:
    """This is a real file reader. It reads from the test's CWD."""
    logger = logging.getLogger("live_e2e.fs_tool")
    try:
        content = Path(path).read_text(encoding='utf-8')
        logger.info(f"fs.read succeeded for path: {Path(path).resolve()}")
        return content
    except Exception as e:
        logger.error(f"fs.read FAILED for path: {path}: {e}")
        raise

@live_mcp_server.tool(name="fs.list_dir")
async def actual_fs_list_dir(path: str) -> List[_DirEntry]:
    """This is a real directory lister. It lists from the test's CWD."""
    logger = logging.getLogger("live_e2e.fs_tool")
    try:
        dir_path = Path(path)
        entries = [_DirEntry(name=item.name, type="directory" if item.is_dir() else "file") for item in dir_path.iterdir()]
        logger.info(f"fs.list_dir succeeded for path: {dir_path.resolve()}")
        return entries
    except Exception as e:
        logger.error(f"fs.list_dir FAILED for path: {path}: {e}")
        raise

# --- Pytest Parametrization --- 

# The --prompts option is now registered in tests/conftest.py, so we don't
# need to register it again here.


def _load_prompts(raw: str) -> list[str]:
    """Loads prompts from a string, handling file paths prefixed with @."""
    if raw.startswith("@"):
        try:
            return [p.strip() for p in Path(raw[1:]).read_text().splitlines() if p.strip()]
        except FileNotFoundError:
            pytest.fail(f"Prompt file not found at: {raw[1:]}")
    return [p.strip() for p in raw.split(",") if p.strip()]

def pytest_generate_tests(metafunc: pytest.Metafunc):
    """Dynamically parametrizes tests that use the 'prompt' fixture."""
    if "prompt" in metafunc.fixturenames:
        cli_values = metafunc.config.getoption("--prompts")
        loaded_prompts = list(itertools.chain.from_iterable(_load_prompts(v) for v in cli_values)) if cli_values else ["Create a hello world app"]
        metafunc.parametrize("prompt", loaded_prompts)

# --- Function-Scoped Live MCP Server Fixture ---

@pytest.fixture
def live_mcp_server_fixture(request):
    """Starts a live, real MCP server for each E2E test function."""
    host = "127.0.0.1"
    port = 7802
    os.environ["MCP_SERVER_URL"] = f"http://{host}:{port}/mcp"
    get_settings().MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]

    class UvicornTestServer(uvicorn.Server):
        _startup_done = threading.Event()
        def __init__(self, app, host, port):
            super().__init__(config=uvicorn.Config(app, host=host, port=port, log_config=None))
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            self._startup_done.set()
        def run_in_thread(self):
            self._thread = threading.Thread(target=self.run)
            self._thread.daemon = True
            self._thread.start()
            self._startup_done.wait()
        def stop(self):
            self.should_exit = True
            if hasattr(self, "_thread"):
                self._thread.join(timeout=5)

    server = UvicornTestServer(app=live_mcp_server.http_app(), host=host, port=port)
    server.run_in_thread()
    yield
    server.stop()
