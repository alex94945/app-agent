import pytest
from unittest.mock import patch, AsyncMock, MagicMock

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
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_apply_patch_success(mock_http_client, mock_client_session, mock_uuid):
    """Tests that apply_patch successfully writes, applies, and removes a patch."""
    # 1. Setup Mocks
    mock_uuid.return_value = 'test-uuid'
    temp_patch_filename = ".tmp.apply_patch.test-uuid.patch"

    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)

    mock_session_instance = AsyncMock()
    mock_git_result = MagicMock()
    mock_git_result.stdout = ""
    mock_git_result.stderr = ""
    mock_git_result.return_code = 0
    mock_session_instance.shell.run.return_value = mock_git_result
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance

    # 2. Call Tool
    result = await apply_patch.ainvoke({
        "file_path_in_repo": "test.txt",
        "diff_content": DIFF_CONTENT
    })

    # 3. Assertions
    mock_session_instance.fs.write.assert_awaited_once_with(path=temp_patch_filename, content=DIFF_CONTENT)
    mock_session_instance.shell.run.assert_awaited_once_with(
        command=f"git apply --unsafe-paths --inaccurate-eof {temp_patch_filename}",
        cwd="."
    )
    mock_session_instance.fs.remove.assert_awaited_once_with(path=temp_patch_filename)
    assert result["return_code"] == 0

@pytest.mark.asyncio
@patch('tools.patch_tools.uuid.uuid4')
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_apply_patch_git_failure(mock_http_client, mock_client_session, mock_uuid):
    """Tests that apply_patch handles a failure from the 'git apply' command."""
    # 1. Setup Mocks
    mock_uuid.return_value = 'test-uuid'
    temp_patch_filename = ".tmp.apply_patch.test-uuid.patch"

    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)

    mock_session_instance = AsyncMock()
    mock_git_result = MagicMock()
    mock_git_result.stdout = ""
    mock_git_result.stderr = "error: patch failed"
    mock_git_result.return_code = 1
    mock_session_instance.shell.run.return_value = mock_git_result
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance

    # 2. Call Tool
    result = await apply_patch.ainvoke({
        "file_path_in_repo": "test.txt",
        "diff_content": DIFF_CONTENT
    })

    # 3. Assertions
    assert result["return_code"] == 1
    assert "patch failed" in result["stderr"]
    # Ensure cleanup still happens
    mock_session_instance.fs.remove.assert_awaited_once_with(path=temp_patch_filename)

@pytest.mark.asyncio
@patch('tools.patch_tools.uuid.uuid4')
@patch('common.mcp_session.ClientSession')
@patch('common.mcp_session.streamablehttp_client')
async def test_apply_patch_mcp_write_error(mock_http_client, mock_client_session, mock_uuid):
    """Tests that apply_patch handles an MCPError during the file write step."""
    # 1. Setup Mocks
    mock_uuid.return_value = 'test-uuid'

    mock_reader, mock_writer = AsyncMock(), AsyncMock()
    mock_http_client.return_value.__aenter__.return_value = (mock_reader, mock_writer)

    mock_session_instance = AsyncMock()
    error_data = ErrorData(code=-32001, message="Permission denied")
    mock_session_instance.fs.write.side_effect = McpError(error_data)
    mock_client_session.return_value.__aenter__.return_value = mock_session_instance

    # 2. Call Tool
    result = await apply_patch.ainvoke({
        "file_path_in_repo": "test.txt",
        "diff_content": DIFF_CONTENT
    })

    # 3. Assertions
    assert result["return_code"] == -1
    assert "MCP Error writing temporary patch file" in result["stderr"]
    # Ensure shell.run and fs.remove were not called
    mock_session_instance.shell.run.assert_not_called()
    mock_session_instance.fs.remove.assert_not_called()
