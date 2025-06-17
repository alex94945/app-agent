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
    repo_dir = Path(os.environ.get("REPO_DIR", "."))
    # The agent provides paths relative to the repo root.
    full_path = repo_dir / path
    return full_path.read_text()


@mcp_server.tool(name="fs.write")
def fs_write(path: str, content: str, cwd: str | None = None) -> None:
    """Mock tool to write content to a file."""
    repo_dir = Path(os.environ.get("REPO_DIR", "."))
    # The agent provides paths relative to the repo root.
    full_path = repo_dir / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)


@mcp_server.tool(name="fs.remove")
def fs_remove(path: str, cwd: str | None = None) -> None:
    """Mock tool to remove a file."""
    repo_dir = Path(os.environ.get("REPO_DIR", "."))
    full_path = repo_dir / path
    if full_path.exists() and full_path.is_file():
        full_path.unlink()


@mcp_server.tool(name="shell.run")
async def shell_run(command: str, cwd: str | None = None) -> dict:
    """Mock tool to run a shell command."""
    repo_dir = Path(os.environ.get("REPO_DIR", "."))
    # The `cwd` passed by the agent is relative to the repo_dir
    absolute_cwd = repo_dir / cwd if cwd and cwd != "." else repo_dir

    # Ensure the directory exists
    absolute_cwd.mkdir(parents=True, exist_ok=True)

    try:
        # Create a mutable copy of the environment to modify the PATH
        env = os.environ.copy()

        # Add local binaries to the PATH for this command execution
        # This allows finding binaries like `tsc`, `eslint`, `flake8` etc.
        paths_to_add = []
        
        # For Node projects
        node_bin_path = absolute_cwd / "node_modules" / ".bin"
        if node_bin_path.is_dir():
            paths_to_add.append(str(node_bin_path))

        # For Python projects
        venv_bin_path = absolute_cwd / ".venv" / "bin"
        if venv_bin_path.is_dir():
            paths_to_add.append(str(venv_bin_path))
        
        if paths_to_add:
            current_path = env.get("PATH", "")
            # Prepend local paths to prioritize them
            env["PATH"] = os.pathsep.join(paths_to_add) + os.pathsep + current_path

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(absolute_cwd),  # Must be a string
            env=env,  # Pass the modified environment
        )
        stdout, stderr = await proc.communicate()
        return {
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
            "return_code": proc.returncode,
        }
    except FileNotFoundError as e:
        return {
            "stdout": "",
            "stderr": f"Command not found: {e}",
            "return_code": 127,  # Standard exit code for command not found
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
    # Set the root logger to DEBUG to capture everything
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)-8s %(name)s:%(lineno)d - %(message)s", force=True)
    # But quiet down the noisiest third-party libraries to avoid flooding the output
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
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
