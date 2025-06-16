# tests/integration/conftest.py
import logging
import asyncio
import os
import threading
from pathlib import Path

import pytest
import uvicorn
from mcp.server.fastmcp.server import FastMCP

# Create a new FastMCP server instance for testing.
# We will define our own simple versions of the 'fs' and 'shell' tools
# to make the tests hermetic and avoid dependency issues.
mcp_server = FastMCP(name="Test-MCP-Server")


@mcp_server.tool(name="fs.read")
def fs_read(path: str, cwd: str | None = None) -> str:
    """Mock tool to read a file's content."""
    full_path = Path(cwd) / path if cwd else Path(path)
    return full_path.read_text()


@mcp_server.tool(name="fs.write")
def fs_write(path: str, content: str, cwd: str | None = None) -> None:
    """Mock tool to write content to a file."""
    full_path = Path(cwd) / path if cwd else Path(path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)


@mcp_server.tool(name="shell.run")
async def shell_run(command: str, cwd: str | None = None) -> dict:
    """Mock tool to run a shell command."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "returncode": proc.returncode,
    }


class UvicornTestServer(uvicorn.Server):
    """Uvicorn server that runs in a separate thread."""

    def __init__(self, app, host='127.0.0.1', port=7800):
        self._startup_done = threading.Event()
        super().__init__(config=uvicorn.Config(app, host=host, port=port))

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
        self._thread.join()


@pytest.fixture(scope="session", autouse=True)
def configure_logging():
    """Configure global DEBUG logging for the test session."""
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s:%(lineno)d %(message)s", force=True)
    logging.debug("Logging configured to DEBUG level for integration tests.")


@pytest.fixture(scope="session", autouse=True)
def mcp_server_fixture(request):
    """Starts a mock MCP server for the test session."""
    # Use a different port to avoid conflicts with default
    host = "127.0.0.1"
    port = 7801 
    os.environ["MCP_SERVER_URL"] = f"http://{host}:{port}/mcp"
    # Ensure the common.config.settings object reflects the test server URL as well
    from common.config import settings as _settings
    _settings.MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]

    app = mcp_server.streamable_http_app()
    server = UvicornTestServer(app=app, host=host, port=port)
    server.run_in_thread()

    yield

    server.stop()
