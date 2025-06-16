from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from tools.file_io_mcp_tools import read_file, write_file
# We need to import the exception class to mock it being raised
from mcp.shared.exceptions import McpError, ErrorData

@pytest.mark.asyncio
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_read_file_success(mock_http_client, mock_client_session):
    """Tests that read_file successfully calls the MCP client and returns content."""
    # 1. Setup Mocks for async context managers
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)
    
    mock_session_instance = AsyncMock()
    mock_session_instance.fs.read.return_value = "Hello, world!"
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await read_file.ainvoke({"path_in_repo": "test.txt"})
    
    # 3. Assertions
    mock_http_client.assert_called_once()
    mock_client_session.assert_called_once()
    mock_session_instance.fs.read.assert_awaited_once_with(path="test.txt")
    assert result == "Hello, world!"

@pytest.mark.asyncio
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_read_file_mcp_error(mock_http_client, mock_client_session):
    """Tests that read_file handles an MCPError gracefully."""
    # 1. Setup Mock to raise an MCPError
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)
    
    mock_session_instance = AsyncMock()
    # McpError expects an ErrorData object, not a string
    error_data = ErrorData(code=-32001, message="File not found")
    mock_session_instance.fs.read.side_effect = McpError(error_data)
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await read_file.ainvoke({"path_in_repo": "not_found.txt"})
    
    # 3. Assertions
    assert "MCP Error reading file" in result
    assert "File not found" in result

@pytest.mark.asyncio
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_write_file_success(mock_http_client, mock_client_session):
    """Tests that write_file successfully calls the MCP client."""
    # 1. Setup Mock
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)
    
    mock_session_instance = AsyncMock()
    mock_session_instance.fs.write.return_value = None # write is an async method
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    file_content = "This is a test."
    result = await write_file.ainvoke({"path_in_repo": "new_file.txt", "content": file_content})
    
    # 3. Assertions
    mock_http_client.assert_called_once()
    mock_client_session.assert_called_once()
    mock_session_instance.fs.write.assert_awaited_once_with(path="new_file.txt", content=file_content)
    assert "Successfully wrote" in result
    assert str(len(file_content)) in result

@pytest.mark.asyncio
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_write_file_mcp_error(mock_http_client, mock_client_session):
    """Tests that write_file handles an MCPError gracefully."""
    # 1. Setup Mock to raise an MCPError
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)
    
    mock_session_instance = AsyncMock()
    error_data = ErrorData(code=-32002, message="Permission denied")
    mock_session_instance.fs.write.side_effect = McpError(error_data)
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await write_file.ainvoke({"path_in_repo": "protected/file.txt", "content": "test"})
    
    # 3. Assertions
    assert "MCP Error writing file" in result
    assert "Permission denied" in result
