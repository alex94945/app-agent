import pytest
from pathlib import Path
import json
from unittest.mock import patch, AsyncMock, MagicMock, call

from tools.patch_tools import apply_patch
from mcp.shared.exceptions import McpError, ErrorData

DIFF_CONTENT = """--- a/test.txt
+++ b/test.txt
@@ -1 +1 @@
-hello
+hello world
"""

@pytest.mark.asyncio
@patch('tools.patch_tools.uuid.uuid4')
@patch('mcp.ClientSession')
@patch('mcp.client.streamable_http.streamablehttp_client')
@patch('common.config.settings')
async def test_apply_patch_success(mock_uuid, mock_mcp_client_session, mock_streamable_http, mock_actual_settings):
    """Tests that apply_patch successfully writes, applies, and removes a patch."""
    # 1. Setup Mocks
    mock_actual_settings.REPO_DIR = Path('.')
    mock_uuid.return_value = 'test-uuid'
    temp_patch_filename = ".tmp.apply_patch.test-uuid.patch"

    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_streamable_http.return_value.__aenter__.return_value = (mock_reader, mock_writer, None)

    mock_session_instance = AsyncMock()
    mock_git_result = MagicMock()
    mock_git_result.isError = False
    mock_git_content_item = MagicMock()
    mock_git_content_item.text = json.dumps({
        "stdout": "", 
        "stderr": "", 
        "return_code": 0
    })
    mock_git_result.content = [mock_git_content_item]
    # The tool makes three calls: fs.write, shell.run, fs.remove
    mock_session_instance.call_tool.side_effect = [None, mock_git_result, None]
    mock_mcp_client_session.return_value.__aenter__.return_value = mock_session_instance

    # 2. Call Tool
    result = await apply_patch.ainvoke({
        "file_path_in_repo": "test.txt",
        "diff_content": DIFF_CONTENT
    })

    # 3. Assertions
    expected_calls = [
        call("fs.write", {"path": temp_patch_filename, "content": DIFF_CONTENT}),
        call("shell.run", {"command": f"git apply --unsafe-paths --inaccurate-eof {temp_patch_filename}", "cwd": "."}),
        call("fs.remove", {"path": temp_patch_filename})
    ]
    mock_session_instance.call_tool.assert_has_awaits(expected_calls)
    assert result.ok is True
    assert result.details.return_code == 0

@pytest.mark.asyncio
@patch('tools.patch_tools.uuid.uuid4')
@patch('mcp.ClientSession')
@patch('mcp.client.streamable_http.streamablehttp_client')
@patch('common.config.settings')
async def test_apply_patch_git_failure(mock_uuid, mock_mcp_client_session, mock_streamable_http, mock_actual_settings):
    """Tests that apply_patch handles a failure from the 'git apply' command."""
    # 1. Setup Mocks
    mock_actual_settings.REPO_DIR = Path('.')
    mock_uuid.return_value = 'test-uuid'
    temp_patch_filename = ".tmp.apply_patch.test-uuid.patch"

    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_streamable_http.return_value.__aenter__.return_value = (mock_reader, mock_writer, None)

    mock_session_instance = AsyncMock()
    mock_git_result = MagicMock()
    mock_git_result.isError = False
    mock_git_content_item = MagicMock()
    mock_git_content_item.text = json.dumps({
        "stdout": "", 
        "stderr": "error: patch failed", 
        "return_code": 1
    })
    mock_git_result.content = [mock_git_content_item]
    mock_session_instance.call_tool.side_effect = [None, mock_git_result, None]
    mock_mcp_client_session.return_value.__aenter__.return_value = mock_session_instance

    # 2. Call Tool
    result = await apply_patch.ainvoke({
        "file_path_in_repo": "test.txt",
        "diff_content": DIFF_CONTENT
    })

    # 3. Assertions
    assert result.ok is False
    assert result.details.return_code == 1
    assert "patch failed" in result.details.stderr
    # Ensure cleanup still happens
    mock_session_instance.call_tool.assert_any_await("fs.remove", {"path": temp_patch_filename})

@pytest.mark.asyncio
@patch('tools.patch_tools.uuid.uuid4')
@patch('mcp.ClientSession')
@patch('mcp.client.streamable_http.streamablehttp_client')
@patch('common.config.settings')
async def test_apply_patch_mcp_write_error(mock_uuid, mock_mcp_client_session, mock_streamable_http, mock_actual_settings):
    """Tests that apply_patch handles an MCPError during the file write step."""
    # 1. Setup Mocks
    mock_actual_settings.REPO_DIR = Path('.')
    mock_uuid.return_value = 'test-uuid'
    temp_patch_filename = ".tmp.apply_patch.test-uuid.patch"

    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_streamable_http.return_value.__aenter__.return_value = (mock_reader, mock_writer, None)

    mock_session_instance = AsyncMock()
    error_data = ErrorData(code=-32001, message="Permission denied")
    mock_session_instance.call_tool.side_effect = McpError(error_data)
    mock_mcp_client_session.return_value.__aenter__.return_value = mock_session_instance

    # 2. Call Tool
    result = await apply_patch.ainvoke({
        "file_path_in_repo": "test.txt",
        "diff_content": DIFF_CONTENT
    })

    # 3. Assertions
    assert result.ok is False
    assert "MCP Error writing temporary patch file" in result.message
    # Ensure only the first call (fs.write) was made
    mock_session_instance.call_tool.assert_awaited_once_with("fs.write", {"path": temp_patch_filename, "content": DIFF_CONTENT})
