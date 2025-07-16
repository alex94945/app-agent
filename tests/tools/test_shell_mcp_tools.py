from unittest.mock import patch, MagicMock, AsyncMock
import pytest
import json

from tools.shell_mcp_tools import run_shell
from mcp.shared.exceptions import McpError, ErrorData

from contextlib import asynccontextmanager # Added for mocking context

@pytest.mark.asyncio
async def test_run_shell_success(shell_client, tmp_path, monkeypatch):
    """Tests that run_shell successfully executes a command and returns the result."""
    # 1. Setup: Configure the repository directory for this test
    monkeypatch.setattr('common.config.settings.REPO_DIR', tmp_path)

    # Create an async context manager that yields the shell_client
    @asynccontextmanager
    async def mock_open_mcp_session_ctx():
        yield shell_client

    # 2. Call Tool by invoking the run_shell wrapper
    # Mock the behavior of the session's call_tool method
    shell_client.call_tool = AsyncMock(return_value={
        "stdout": "hello world\n",
        "stderr": "",
        "return_code": 0
    })

    # Patch open_mcp_session to use our mocked client
    with patch('tools.shell_mcp_tools.open_mcp_session', return_value=mock_open_mcp_session_ctx()):
        result = await run_shell.ainvoke({"command": "echo 'hello world'"})

    # 3. Assertions
    shell_client.call_tool.assert_awaited_once_with(
        "shell.run", 
        arguments={'command': "echo 'hello world'", 'cwd': str(tmp_path)}
    )
    assert result.ok is True
    assert result.return_code == 0
    assert result.stdout == "hello world\n"
    assert result.stderr == ""
    assert result.command_executed == "echo 'hello world'"

@pytest.mark.asyncio
async def test_run_shell_command_failure(shell_client): # Use shell_client fixture
    """Tests that run_shell correctly captures output for a failing command."""
    # 1. No Mocks needed for ClientSession or streamablehttp_client directly here

    @asynccontextmanager
    async def mock_open_mcp_session_ctx():
        yield shell_client

    # Mock the behavior of the session's call_tool method for a failed command
    shell_client.call_tool = AsyncMock(return_value={
        "stdout": "",
        "stderr": "ls: cannot access 'non_existent_file': No such file or directory",
        "return_code": 2
    })

    # 2. Call Tool by invoking the run_shell wrapper
    with patch('tools.shell_mcp_tools.open_mcp_session', return_value=mock_open_mcp_session_ctx()):
        result = await run_shell.ainvoke({"command": "ls non_existent_file"})

    # 3. Assertions
    assert result.ok is False
    assert result.return_code == 2
    assert result.stdout == ""
    assert "No such file or directory" in result.stderr
    assert result.command_executed == "ls non_existent_file"

@pytest.mark.asyncio
async def test_run_shell_mcp_error(shell_client, monkeypatch): # Add monkeypatch
    """Tests that run_shell handles an underlying MCPError gracefully."""
    # 1. Configure shell_client.call_tool to raise McpError
    error_data = ErrorData(code=-32003, message="Execution environment not available")
    mcp_error_to_raise = McpError(error_data)

    async def mock_call_tool(*args, **kwargs):
        raise mcp_error_to_raise

    monkeypatch.setattr(shell_client, 'call_tool', mock_call_tool)

    @asynccontextmanager
    async def mock_open_mcp_session_ctx():
        yield shell_client

    # 2. Call Tool
    command_to_run = "some command"
    with patch('tools.shell_mcp_tools.open_mcp_session', return_value=mock_open_mcp_session_ctx()):
        result = await run_shell.ainvoke({"command": command_to_run})
    
    # 3. Assertions
    assert result.ok is False
    assert result.return_code == -1
    assert result.stdout == ""
    # Check the full formatted error message from run_shell's McpError handler
    expected_stderr = f"MCP Error running command '{command_to_run}': {mcp_error_to_raise}"
    assert result.stderr == expected_stderr
    assert result.command_executed == command_to_run
