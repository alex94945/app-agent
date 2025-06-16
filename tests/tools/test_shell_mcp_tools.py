from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from tools.shell_mcp_tools import run_shell
from mcp.shared.exceptions import McpError, ErrorData

@pytest.mark.asyncio
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_run_shell_success(mock_http_client, mock_client_session):
    """Tests that run_shell successfully executes a command and returns the result."""
    # 1. Setup Mocks
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)
    
    mock_session_instance = AsyncMock()
    # The real mcp shell.run returns an object with these attributes
    mock_run_result = MagicMock()
    mock_run_result.stdout = "hello world"
    mock_run_result.stderr = ""
    mock_run_result.return_code = 0
    mock_session_instance.shell.run.return_value = mock_run_result
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await run_shell.ainvoke({"command": "echo 'hello world'"})
    
    # 3. Assertions
    mock_session_instance.shell.run.assert_awaited_once_with(command="echo 'hello world'", cwd=".")
    assert result["return_code"] == 0
    assert result["stdout"] == "hello world"
    assert result["stderr"] == ""

@pytest.mark.asyncio
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_run_shell_command_failure(mock_http_client, mock_client_session):
    """Tests that run_shell correctly captures output for a failing command."""
    # 1. Setup Mocks
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)
    
    mock_session_instance = AsyncMock()
    mock_run_result = MagicMock()
    mock_run_result.stdout = ""
    mock_run_result.stderr = "ls: no such file or directory: non_existent_file"
    mock_run_result.return_code = 1
    mock_session_instance.shell.run.return_value = mock_run_result
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await run_shell.ainvoke({"command": "ls non_existent_file"})
    
    # 3. Assertions
    mock_session_instance.shell.run.assert_awaited_once_with(command="ls non_existent_file", cwd=".")
    assert result["return_code"] == 1
    assert result["stdout"] == ""
    assert "no such file or directory" in result["stderr"]

@pytest.mark.asyncio
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_run_shell_mcp_error(mock_http_client, mock_client_session):
    """Tests that run_shell handles an underlying MCPError gracefully."""
    # 1. Setup Mocks
    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)
    
    mock_session_instance = AsyncMock()
    error_data = ErrorData(code=-32003, message="Execution environment not available")
    mock_session_instance.shell.run.side_effect = McpError(error_data)
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance
    
    # 2. Call Tool
    result = await run_shell.ainvoke({"command": "some command"})
    
    # 3. Assertions
    assert result["return_code"] == -1
    assert result["stdout"] == ""
    assert "MCP Error running command" in result["stderr"]
    assert "Execution environment not available" in result["stderr"]
