import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch
from contextlib import asynccontextmanager

from tools.file_io_mcp_tools import read_file, write_file, WriteFileOutput
from mcp.shared.exceptions import McpError

# Helper async context manager to mock open_mcp_session
@asynccontextmanager
async def mock_mcp_session_cm(client_to_yield):
    """Yields the provided client instance within an async context."""
    yield client_to_yield

@pytest.mark.asyncio
async def test_read_file_success(file_io_client, tmp_path, monkeypatch):
    """Tests that read_file successfully reads content using the file_io_client."""
    # 1. Setup
    test_file = tmp_path / "test_read.txt"
    expected_content = "Hello from fastmcp!"
    await asyncio.to_thread(test_file.write_text, expected_content)
    monkeypatch.setattr('common.config.settings.REPO_DIR', tmp_path)

    # 2. Call Tool via .ainvoke()
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        # read_file returns a string, which LangChain wraps. We assert against the raw string.
        result = await read_file.ainvoke({"path_in_repo": "test_read.txt"})
    
    # 3. Assertions
    assert result == expected_content

@pytest.mark.asyncio
async def test_read_file_mcp_error_not_found(file_io_client, tmp_path, monkeypatch):
    """Tests that read_file handles McpError (FileNotFound) from file_io_client."""
    # 1. Setup
    monkeypatch.setattr('common.config.settings.REPO_DIR', tmp_path)

    # 2. Call Tool via .ainvoke()
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        # The tool returns a formatted error string.
        result = await read_file.ainvoke({"path_in_repo": "non_existent_file.txt"})
    
    # 3. Assertions
    assert isinstance(result, str)
    # The tool catches the ToolError and formats a user-friendly string.
    assert 'MCP Error' in result
    assert 'File not found' in result

@pytest.mark.asyncio
async def test_write_file_success(file_io_client, tmp_path):
    """Tests that write_file successfully writes content using the file_io_client."""
    # 1. Setup
    output_file = tmp_path / "test_write.txt"
    content_to_write = "Content written by fastmcp!"

    # 2. Call Tool via .ainvoke()
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        # write_file returns a Pydantic model, which is passed through by .ainvoke()
        result = await write_file.ainvoke({"path_in_repo": str(output_file), "content": content_to_write})
    
    # 3. Assertions
    assert isinstance(result, WriteFileOutput)
    assert result.ok is True
    assert result.path == str(output_file)
    assert f"Successfully wrote {len(content_to_write)} bytes" in result.message
    
    # Verify file content on disk
    assert await asyncio.to_thread(output_file.read_text) == content_to_write

@pytest.mark.asyncio
async def test_write_file_mcp_error_is_a_directory(file_io_client, tmp_path):
    """Tests write_file handling McpError when trying to write to a directory."""
    # 1. Setup
    target_dir = tmp_path / "a_directory"
    await asyncio.to_thread(target_dir.mkdir)

    # 2. Call Tool via .ainvoke()
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        result = await write_file.ainvoke({"path_in_repo": str(target_dir), "content": "test content"})

    # 3. Assertions
    assert isinstance(result, WriteFileOutput)
    assert isinstance(result, WriteFileOutput)
    assert result.ok is False
    assert result.path == str(target_dir)
    # The tool catches the ToolError and formats a user-friendly string.
    assert 'MCP Error' in result.message
    assert 'Is a directory' in result.message
