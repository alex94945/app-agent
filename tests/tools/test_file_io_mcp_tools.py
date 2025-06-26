import pytest
import asyncio
from unittest.mock import patch

# Import the tool functions and the helper from conftest
from tools.file_io_mcp_tools import read_file, write_file, WriteFileOutput
from tests.conftest import mock_mcp_session_cm

# All tests are async
pytestmark = pytest.mark.asyncio


async def test_read_file_success(file_io_client, tmp_path, monkeypatch):
    """Tests that read_file successfully reads content using the file_io_client."""
    # 1. Setup: Create a test file in a temporary repo directory
    repo_path = tmp_path
    monkeypatch.setattr('common.config.settings.REPO_DIR', str(repo_path))

    test_file_path = repo_path / "test_read.txt"
    expected_content = "Hello from fastmcp!"
    await asyncio.to_thread(test_file_path.write_text, expected_content)

    # 2. Call Tool: Use the in-memory client by patching open_mcp_session
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        result = await read_file.ainvoke({"path_in_repo": "test_read.txt"})

    # 3. Assertions: Check if the content matches
    assert result == expected_content


async def test_read_file_mcp_error_not_found(file_io_client, tmp_path, monkeypatch):
    """Tests that read_file handles McpError (FileNotFound) from file_io_client."""
    # 1. Setup: Configure the repo directory
    repo_path = tmp_path
    monkeypatch.setattr('common.config.settings.REPO_DIR', str(repo_path))

    # 2. Call Tool: Attempt to read a non-existent file
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        result = await read_file.ainvoke({"path_in_repo": "non_existent_file.txt"})

    # 3. Assertions: Check for the formatted error string
    assert isinstance(result, str)
    assert 'MCP Error' in result
    assert 'File not found' in result


async def test_write_file_success(file_io_client, tmp_path, monkeypatch):
    """Tests that write_file successfully writes content using the file_io_client."""
    # 1. Setup: Configure the repo directory
    repo_path = tmp_path
    monkeypatch.setattr('common.config.settings.REPO_DIR', str(repo_path))

    relative_path = "test_write.txt"
    output_file_path = repo_path / relative_path
    content_to_write = "Content written by fastmcp!"

    # 2. Call Tool: Use the in-memory client to write the file
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        result = await write_file.ainvoke(
            {
                "path_in_repo": relative_path,
                "content": content_to_write
            }
        )

    # 3. Assertions: Check the tool's return value and the file on disk
    assert isinstance(result, WriteFileOutput)
    assert result.ok is True
    assert result.path == relative_path
    assert f"Successfully wrote {len(content_to_write)} bytes" in result.message
    assert await asyncio.to_thread(output_file_path.read_text) == content_to_write


async def test_write_file_mcp_error_is_a_directory(file_io_client, tmp_path, monkeypatch):
    """Tests write_file handling McpError when trying to write to a directory."""
    # 1. Setup: Create a directory where we'll try to write a file
    repo_path = tmp_path
    monkeypatch.setattr('common.config.settings.REPO_DIR', str(repo_path))

    relative_path = "a_directory"
    target_dir_path = repo_path / relative_path
    await asyncio.to_thread(target_dir_path.mkdir)

    # 2. Call Tool: Attempt to write to the directory path
    with patch('tools.file_io_mcp_tools.open_mcp_session', return_value=mock_mcp_session_cm(file_io_client)):
        result = await write_file.ainvoke(
            {
                "path_in_repo": relative_path,
                "content": "test content"
            }
        )

    # 3. Assertions: Check for the formatted error object
    assert isinstance(result, WriteFileOutput)
    assert result.ok is False
    assert result.path == relative_path
    assert 'MCP Error' in result.message
    assert 'Is a directory' in result.message
