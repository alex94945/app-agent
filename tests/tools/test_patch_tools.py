import pytest
import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch, AsyncMock
from tools.shell_mcp_tools import run_shell

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

    # Mock the sequence of shell commands that apply_patch will run
    patch_client.call_tool = AsyncMock(side_effect=[
        # 1. git apply --check -> success
        {"stdout": "", "stderr": "", "return_code": 0},
        # 2. git apply -> success
        {"stdout": "", "stderr": "", "return_code": 0},
        # 3. git add -> success
        {"stdout": "", "stderr": "", "return_code": 0},
    ])

    # 2. Call Tool
    with patch('tools.shell_mcp_tools.open_mcp_session', new=lambda: mock_mcp_session_cm(patch_client)):
        result = await apply_patch.ainvoke({
            "file_path_in_repo": "test.txt",
            "diff_content": DIFF_CONTENT_SUCCESS
        })

    # 3. Assertions
    assert isinstance(result, ApplyPatchOutput)
    assert result.ok is True
    assert "patch applied successfully" in result.message.lower()
    # We can't verify file content because the actual git commands are mocked.
    # The goal here is to test the apply_patch logic, not the git tool itself.
    assert patch_client.call_tool.call_count == 3

@pytest.mark.asyncio
async def test_apply_patch_git_failure(patch_client, git_repo, monkeypatch):
    """Tests that apply_patch handles a failure from the 'git apply' command."""
    # 1. Setup
    monkeypatch.setattr('common.config.settings.REPO_DIR', git_repo)

    # Mock a successful git add, followed by a failed git apply --check
    patch_client.call_tool = AsyncMock(side_effect=[
        # 1. git add --all -> success
        {"stdout": "", "stderr": "", "return_code": 0},
        # 2. git apply --check -> failure
        {"stdout": "", "stderr": "error: patch failed...", "return_code": 1},
    ])

    # 2. Call Tool with a patch that will fail
    with patch('tools.shell_mcp_tools.open_mcp_session', new=lambda: mock_mcp_session_cm(patch_client)):
        result = await apply_patch.ainvoke({
            "file_path_in_repo": "test.txt",
            "diff_content": DIFF_CONTENT_FAILURE
        })

    # 3. Assertions
    assert isinstance(result, ApplyPatchOutput)
    assert result.ok is False
    assert "patch check failed" in result.message.lower()
    assert "error: patch failed" in result.message.lower()
    assert patch_client.call_tool.call_count == 2

@pytest.mark.asyncio
async def test_apply_patch_fs_write_error(patch_client, git_repo, monkeypatch):
    """
    apply_patch must return ok=False if its shell layer surprises it with an FS-write error.
    """
    # 1. Repo workspace
    monkeypatch.setattr("common.config.settings.REPO_DIR", git_repo)

    # 2. Inject fault at the *actual* dependency: session.call_tool(...)
    from unittest.mock import AsyncMock, patch as patch_ctx

    # make every shell.run call explode
    patch_client.call_tool = AsyncMock(side_effect=Exception("Injected Fault"))

    with patch_ctx(
        "tools.shell_mcp_tools.open_mcp_session",
        new=lambda: mock_mcp_session_cm(patch_client),
    ):
        result = await apply_patch.ainvoke(
            {
                "file_path_in_repo": "test.txt",
                "diff_content": DIFF_CONTENT_SUCCESS,
            }
        )

    # 3. Assertions
    assert result.ok is False
    assert "Injected Fault" in result.message

    
    # Reset permissions so tmp_path cleanup works
    git_repo.chmod(0o755)
