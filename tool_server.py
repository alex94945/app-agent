# tool_server.py
import asyncio
import logging
import os
from pathlib import Path


from mcp.server.fastmcp.server import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s:%(lineno)d - %(message)s")
logger = logging.getLogger(__name__)

# Get the workspace directory from environment variables, default to a local directory
REPO_DIR = Path(os.environ.get("REPO_DIR", "./workspace_dev"))

# Get host and port from environment variables or use defaults
host = os.environ.get("MCP_SERVER_HOST", "127.0.0.1")
port = int(os.environ.get("MCP_SERVER_PORT", 8080))

# Create a new FastMCP server instance, passing server config to the constructor
# as per the solution found in the Render community forum.
mcp_server = FastMCP(name="Production-MCP-Server", host=host, port=port)

from typing import List
from pydantic import BaseModel, Field

# --- Tool Schemas ---

class DirEntry(BaseModel):
    name: str
    type: str  # "file" or "directory"

class ShellRunOutput(BaseModel):
    stdout: str
    stderr: str
    return_code: int

# --- Tool Implementations ---

async def _stream_and_log(stream: asyncio.StreamReader, log_prefix: str) -> str:
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

@mcp_server.tool(name="fs.read")
async def fs_read(path: str) -> str:
    """This is a real file reader. It reads from the test's CWD."""
    try:
        full_path = REPO_DIR / path
        content = full_path.read_text(encoding='utf-8')
        logger.info(f"fs.read succeeded for path: {full_path.resolve()}")
        return content
    except Exception as e:
        logger.error(f"fs.read FAILED for path: {path}: {e}")
        raise

@mcp_server.tool(name="fs.write")
async def fs_write(path: str, content: str) -> None:
    """This is a real file writer. It writes to the test's CWD."""
    try:
        full_path = REPO_DIR / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')
        logger.info(f"fs.write succeeded for path: {full_path.resolve()}")
    except Exception as e:
        logger.error(f"fs.write FAILED for path: {path}: {e}")
        raise

@mcp_server.tool(name="fs.list_dir")
async def fs_list_dir(path: str) -> List[DirEntry]:
    """This is a real directory lister. It lists from the test's CWD."""
    try:
        full_path = REPO_DIR / path
        entries = [DirEntry(name=item.name, type="directory" if item.is_dir() else "file") for item in full_path.iterdir()]
        logger.info(f"fs.list_dir succeeded for path: {full_path.resolve()}")
        return entries
    except Exception as e:
        logger.error(f"fs.list_dir FAILED for path: {path}: {e}")
        raise

@mcp_server.tool(name="shell.run")
async def shell_run(command: str, cwd: str | None = None, stdin: str | None = None) -> ShellRunOutput:
    """This is a real shell command executor that runs asynchronously and streams output."""
    try:
        absolute_cwd = REPO_DIR / cwd if cwd else REPO_DIR
        logger.info(f"shell.run executing: {command} in {absolute_cwd}")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=absolute_cwd,
        )

        if process.stdin:
            if stdin:
                process.stdin.write(stdin.encode())
                await process.stdin.drain()
            process.stdin.close()

        stdout_task = asyncio.create_task(_stream_and_log(process.stdout, "STDOUT"))
        stderr_task = asyncio.create_task(_stream_and_log(process.stderr, "STDERR"))

        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        await process.wait()

        logger.info(f"shell.run finished: {command} with return code {process.returncode}")
        return ShellRunOutput(
            stdout=stdout,
            stderr=stderr,
            return_code=process.returncode,
        )
    except Exception as e:
        logger.error(f"shell.run FAILED: {command} with exception: {e}")
        return ShellRunOutput(stdout="", stderr=str(e), return_code=-1)


# --- Main Execution ---

if __name__ == "__main__":
    logger.info(f"Starting MCP Tool Server at http://{host}:{port}")
    logger.info(f"Workspace (REPO_DIR): {REPO_DIR.resolve()}")

    # The run() method simply starts the server with the specified transport.
    # Configuration is handled in the FastMCP constructor.
    mcp_server.run(transport="streamable-http")
