# tests/conftest.py

import sys
from pathlib import Path

# Add the project root directory to the system path to ensure
# modules like 'common' and 'agent' can be imported in tests.
# The project root is two levels up from this file (tests/conftest.py).
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import pytest_asyncio # Added for async fixtures
import asyncio
from typing import AsyncIterator, Optional

from fastmcp import Client # Import Client from fastmcp as per documentation
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# --- Pydantic Schema for the server-side 'shell.run' tool output --- 

class _ShellRunOutput(BaseModel):
    stdout: str = Field(description="The standard output of the command.")
    stderr: str = Field(description="The standard error of the command.")
    return_code: int = Field(description="The return code of the command.")

# --- FastMCP Server for Shell Tools ---

def build_shell_tools_server() -> FastMCP:
    server = FastMCP("ShellToolsTestServer")

    @server.tool(name="shell.run")
    async def actual_shell_run(command: str, cwd: Optional[str] = None) -> _ShellRunOutput:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            
            # Ensure stdout/stderr are strings even if empty
            stdout = stdout_bytes.decode().strip() if stdout_bytes else ""
            stderr = stderr_bytes.decode().strip() if stderr_bytes else ""
            return_code = proc.returncode if proc.returncode is not None else -1 # Ensure return_code is int

            return _ShellRunOutput(
                stdout=stdout,
                stderr=stderr,
                return_code=return_code
            )
        except Exception as e:
            # Log the exception and return an error structure
            # This helps in debugging issues with the subprocess itself
            return _ShellRunOutput(
                stdout="",
                stderr=f"Error in actual_shell_run: {str(e)}",
                return_code=-1 # Indicate an error in the tool execution
            )

    return server

# --- Pytest Fixture for the Shell Client ---

@pytest_asyncio.fixture
async def shell_client() -> AsyncIterator[Client]:
    server = build_shell_tools_server()
    async with Client(server) as c: # Uses in-memory FastMCPTransport
        yield c

