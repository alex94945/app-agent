import pytest
import tempfile
from pathlib import Path
import json
import asyncio

# --- File Contents for the test project ---

PACKAGE_JSON_CONTENT = {
  "name": "test-project",
  "version": "1.0.0",
  "scripts": {
    "lint": "eslint src/index.ts"
  },
  "devDependencies": {
    "eslint": "^8.57.0",
    "@typescript-eslint/eslint-plugin": "^7.13.1",
    "@typescript-eslint/parser": "^7.13.1",
    "typescript": "^5.4.5"
  }
}

ESLINTRC_CONTENT = {
  "root": True,
  "parser": "@typescript-eslint/parser",
  "plugins": ["@typescript-eslint/eslint-plugin"],
  "extends": [
    "plugin:@typescript-eslint/recommended"
  ],
  "rules": {
    "@typescript-eslint/no-unused-vars": "error"
  }
}

TS_CODE_WITH_LINT_ERROR = "const unusedVar = 42;"


@pytest.fixture
def linting_project():
    """Creates a temporary TS project with a linting error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        src_path = repo_path / "src"
        src_path.mkdir()

        (repo_path / "package.json").write_text(json.dumps(PACKAGE_JSON_CONTENT, indent=2))
        (repo_path / ".eslintrc.json").write_text(json.dumps(ESLINTRC_CONTENT, indent=2))
        (src_path / "index.ts").write_text(TS_CODE_WITH_LINT_ERROR)
        
        yield repo_path


@pytest.mark.asyncio
async def test_linting_error_self_healing_environment(linting_project):
    """Tests that the environment for self-healing is set up correctly."""
    repo_path = linting_project
    
    # 1. Install dependencies
    proc_install = await asyncio.create_subprocess_shell(
        "npm install", 
        cwd=repo_path, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr_install = await proc_install.communicate()
    assert proc_install.returncode == 0, f"npm install failed: {stderr_install.decode()}"

    # 2. Run lint and expect it to fail
    proc_lint_fail = await asyncio.create_subprocess_shell(
        "npm run lint", 
        cwd=repo_path, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.PIPE
    )
    stdout_fail, _ = await proc_lint_fail.communicate()
    assert proc_lint_fail.returncode != 0, "npm run lint should have failed but it passed"
    assert "'unusedVar' is assigned a value but never used" in stdout_fail.decode()

    # 3. Manually fix the file
    fixed_code = "// The unused variable has been removed"
    (repo_path / "src" / "index.ts").write_text(fixed_code)

    # 4. Run lint again and expect it to pass
    proc_lint_pass = await asyncio.create_subprocess_shell(
        "npm run lint", 
        cwd=repo_path, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr_pass = await proc_lint_pass.communicate()
    assert proc_lint_pass.returncode == 0, f"npm run lint failed after fix: {stderr_pass.decode()}"

    # This test confirms the environment is correct for the agent to work in.
    # The next step is to have the agent perform these fixes.
    pytest.skip("Skipping full agent test until the agent runner is integrated.")
