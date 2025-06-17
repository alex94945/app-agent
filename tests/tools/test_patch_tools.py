import pytest
import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

from tools.patch_tools import apply_patch, ApplyPatchOutput
from tests.conftest import mock_mcp_session_cm

# --- Test Data ---

DIFF_CONTENT_SUCCESS = """--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,1 @@
-hello
+hello world
"""

DIFF_CONTENT_FAILURE = """--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,1 @@
-this will not apply
+because the original content is wrong
"""

# --- Fixtures ---

@pytest.fixture
def git_repo(tmp_path: Path):
    """Creates a temporary git repository for testing."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    # Run git commands synchronously for setup
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    
    # Create and commit an initial file
    test_file = repo_path / "test.txt"
    test_file.write_text("hello\n")
    subprocess.run(["git", "add", "test.txt"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_path, check=True)
    
    return repo_path

# --- Tests ---

@pytest.mark.asyncio
async def test_apply_patch_success(patch_client, git_repo, monkeypatch):
    """Tests a successful patch application using a real git repo."""
    # 1. Setup
    monkeypatch.setattr('common.config.settings.REPO_DIR', git_repo)
    test_file = git_repo / "test.txt"

    # 2. Call Tool
    with patch('tools.patch_tools.open_mcp_session', return_value=mock_mcp_session_cm(patch_client)):
        result = await apply_patch.ainvoke({
            "file_path_in_repo": "test.txt",
            "diff_content": DIFF_CONTENT_SUCCESS
        })

    # 3. Assertions
    assert isinstance(result, ApplyPatchOutput)
    assert result.ok is True
    assert result.details.return_code == 0
    assert "Patch applied successfully" in result.message
    
    # Verify the file content has changed
    modified_content = await asyncio.to_thread(test_file.read_text)
    assert modified_content == "hello world\n"

@pytest.mark.asyncio
async def test_apply_patch_git_failure(patch_client, git_repo, monkeypatch):
    """Tests that apply_patch handles a failure from the 'git apply' command."""
    # 1. Setup
    monkeypatch.setattr('common.config.settings.REPO_DIR', git_repo)

    # 2. Call Tool with a patch that will fail
    with patch('tools.patch_tools.open_mcp_session', return_value=mock_mcp_session_cm(patch_client)):
        result = await apply_patch.ainvoke({
            "file_path_in_repo": "test.txt",
            "diff_content": DIFF_CONTENT_FAILURE
        })

    # 3. Assertions
    assert isinstance(result, ApplyPatchOutput)
    assert result.ok is False
    assert result.details.return_code != 0
    assert "'git apply' failed" in result.message
    assert "error: patch failed" in result.details.stderr

@pytest.mark.asyncio
async def test_apply_patch_fs_write_error(patch_client, git_repo, monkeypatch):
    """Tests that apply_patch handles an error during the initial fs.write call."""
    # 1. Setup
    monkeypatch.setattr('common.config.settings.REPO_DIR', git_repo)
    
    # Make the repo directory read-only to cause a write error
    # The temporary patch file is written to the root of the repo dir
    git_repo.chmod(0o555)

    # 2. Call Tool
    with patch('tools.patch_tools.open_mcp_session', return_value=mock_mcp_session_cm(patch_client)):
        result = await apply_patch.ainvoke({
            "file_path_in_repo": "test.txt",
            "diff_content": DIFF_CONTENT_SUCCESS
        })

    # 3. Assertions
    assert isinstance(result, ApplyPatchOutput)
    assert result.ok is False
    assert "MCP Error writing temporary patch file" in result.message
    assert "Permission denied" in result.message
    
    # Reset permissions so tmp_path cleanup works
    git_repo.chmod(0o755)
