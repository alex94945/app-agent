import pytest
import pytest_asyncio
import itertools
from pathlib import Path
import os
import threading
import uvicorn
from fastmcp import Client
import socket
import asyncio
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

async def _stream_and_log(stream: asyncio.StreamReader, logger: logging.Logger, log_prefix: str) -> str:
    """Reads from a stream line by line, logs each line, and returns the full content."""
    output_lines = []
    while not stream.at_eof():
        line = await stream.readline()
        if not line:
            break
        decoded_line = line.decode().rstrip()
        logger.info(f"{log_prefix}: {decoded_line}")
        output_lines.append(decoded_line)
    return "\n".join(output_lines)

@live_mcp_server.tool(name="shell.run")
async def actual_shell_run(command: str, cwd: Optional[str] = None, stdin: Optional[str] = None) -> _ShellRunOutput:
    """This is a real shell command executor that runs asynchronously and streams output."""
    logger = logging.getLogger("live_e2e.shell_tool")
    try:
        logger.info(f"shell.run executing: {command} in {cwd or '.'}")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,  # Always create a pipe for stdin
            cwd=cwd,
        )

        if process.stdin:
            if stdin:
                process.stdin.write(stdin.encode())
                await process.stdin.drain()
            # If no stdin is provided, close the pipe immediately.
            # This signals to the child process that it's running non-interactively.
            process.stdin.close()

        # Concurrently stream stdout and stderr
        stdout_task = asyncio.create_task(_stream_and_log(process.stdout, logger, "STDOUT"))
        stderr_task = asyncio.create_task(_stream_and_log(process.stderr, logger, "STDERR"))

        # Wait for the streams to be fully read, then wait for the process to finish.
        # This order avoids a deadlock where the process waits for pipes to be read
        # and the readers wait for the process to exit.
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        await process.wait()

        logger.info(f"shell.run finished: {command} with return code {process.returncode}")
        return _ShellRunOutput(
            stdout=stdout,
            stderr=stderr,
            return_code=process.returncode,
        )
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

def find_free_port():
    """Finds a free port on the host machine."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

@pytest_asyncio.fixture
async def live_mcp_client(request) -> Client:
    """Pytest fixture to run the live MCP server and yield a connected client."""
    host = "127.0.0.1"
    port = find_free_port()

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

    # Conditionally silence streaming logs if --streaming is not provided
    shell_logger = logging.getLogger("live_e2e.shell_tool")
    original_level = shell_logger.level
    if not request.config.getoption("--streaming"):
        shell_logger.setLevel(logging.CRITICAL)

    try:
        async with Client(live_mcp_server) as client:
            yield client
    finally:
        server.stop()
        # Restore original logging level
        shell_logger.setLevel(original_level)
