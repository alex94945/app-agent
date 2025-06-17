from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import pytest

from tools.file_io_mcp_tools import read_file, write_file, WriteFileOutput
from mcp.shared.exceptions import McpError, ErrorData

@pytest.mark.asyncio
@patch('mcp.ClientSession')
@patch('mcp.client.streamable_http.streamablehttp_client')
@patch('common.config.settings')
async def test_read_file_success(mock_mcp_client_session, mock_streamable_http, mock_actual_settings):
    """Tests that read_file successfully calls the MCP client and returns content."""
    # 1. Setup Mocks
    mock_actual_settings.REPO_DIR = Path('.')
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_streamable_http.return_value.__aenter__.return_value = (mock_reader, mock_writer, None)
    
    mock_session_instance = AsyncMock()
    mock_session_instance.call_tool.return_value = "Hello, world!"
    mock_mcp_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await read_file.ainvoke({"path_in_repo": "test.txt"})
    
    # 3. Assertions
    mock_session_instance.call_tool.assert_awaited_once_with("fs.read", {"path": "test.txt"})
    assert result == "Hello, world!"

@pytest.mark.asyncio
@patch('mcp.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_read_file_mcp_error(mock_http_client, mock_client_session):
    """Tests that read_file handles an MCPError gracefully."""
    # 1. Setup Mock
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer, None)
    
    mock_session_instance = AsyncMock()
    error_data = ErrorData(code=-32001, message="File not found")
    mock_session_instance.call_tool.side_effect = McpError(error_data)
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await read_file.ainvoke({"path_in_repo": "not_found.txt"})
    
    # 3. Assertions
    assert "MCP Error reading file" in result
    assert "File not found" in result

@pytest.mark.asyncio
@patch('mcp.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_write_file_success(mock_http_client, mock_client_session):
    """Tests that write_file successfully calls the MCP client."""
    # 1. Setup Mock
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer, None)
    
    mock_session_instance = AsyncMock()
    mock_session_instance.call_tool.return_value = None  # fs.write returns nothing on success
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    file_content = "This is a test."
    result = await write_file.ainvoke({"path_in_repo": "new_file.txt", "content": file_content})
    
    # 3. Assertions
    mock_session_instance.call_tool.assert_awaited_once_with(
        "fs.write",
        {"path": "new_file.txt", "content": file_content}
    )
    assert result.ok is True
    assert isinstance(result, WriteFileOutput)
    assert "Successfully wrote" in result.message

@pytest.mark.asyncio
@patch('mcp.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_write_file_mcp_error(mock_http_client, mock_client_session):
    """Tests that write_file handles an MCPError gracefully."""
    # 1. Setup Mock
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer, None)
    
    mock_session_instance = AsyncMock()
    error_data = ErrorData(code=-32002, message="Permission denied")
    mock_session_instance.call_tool.side_effect = McpError(error_data)
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await write_file.ainvoke({"path_in_repo": "protected/file.txt", "content": "test"})
    
    # 3. Assertions
    assert result.ok is False
    assert "MCP Error writing file" in result.message
    assert "Permission denied" in result.message
