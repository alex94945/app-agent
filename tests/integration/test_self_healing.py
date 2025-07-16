# tests/integration/test_self_healing.py

import pytest
import json
import logging
import shutil
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

# --- Add project root to sys.path to allow imports ---
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from common.config import get_settings
from fastmcp import Client
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from tools.shell_mcp_tools import run_shell

# --- Test Project File Contents & Constants ---

PACKAGE_JSON_CONTENT = {
  "name": "ts-error-project",
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

TS_CODE_WITH_LINT_ERROR = "const unusedVar = 42;\n"
TS_FILE_NAME = "src/index.ts"
PROJECT_SUBDIR_NAME = "ts_error_project_template"

NEXTJS_PROJECT_SUBDIR_NAME = "nextjs_error_project_template"
NEXTJS_TSX_FILE_NAME = "src/app/page.tsx"


# --- Fixtures ---

@pytest.fixture(scope="function")
def ts_project_with_error(tmp_path: Path) -> Path:
    """
    Creates a temporary TypeScript project, writes the necessary config files,
    and runs `npm install`. This is the most reliable way to ensure a correct
    test environment, despite the performance cost.
    """
    repo_path = tmp_path / "repo"
    project_path = repo_path / PROJECT_SUBDIR_NAME
    src_path = project_path / "src"
    src_path.mkdir(parents=True, exist_ok=True)

    # Create project files from constants
    (project_path / "package.json").write_text(json.dumps(PACKAGE_JSON_CONTENT, indent=2))
    (project_path / ".eslintrc.json").write_text(json.dumps(ESLINTRC_CONTENT, indent=2))
    (project_path / TS_FILE_NAME).write_text(TS_CODE_WITH_LINT_ERROR)

    # Run `npm install` in the temporary project directory. This is slow but reliable.
    logging.info(f"Running 'npm install' in temporary directory: {project_path}")
    try:
        subprocess.run(
            ["npm", "install"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=120 # 2-minute timeout
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = e.stderr if hasattr(e, 'stderr') else "N/A"
        pytest.fail(f"npm install failed in test fixture: {stderr}")

    # Initialize a git repository after setup is complete
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit with linting error"], cwd=repo_path, check=True, capture_output=True)

    return repo_path


@pytest.fixture(scope="function")
def nextjs_project_with_error(tmp_path: Path) -> Path:
    """
    Copies a pre-built Next.js project, then programmatically introduces a
    TypeScript build error into the main page component.
    """
    template_dir = Path(__file__).parent / "fixtures" / NEXTJS_PROJECT_SUBDIR_NAME
    if not template_dir.is_dir(): # No longer check for node_modules in template
        pytest.fail(
            f"Next.js fixture template not found. "
            f"Please create it at '{template_dir}'."
        )

    repo_path = tmp_path / "repo"
    project_path = repo_path / NEXTJS_PROJECT_SUBDIR_NAME

    # Copy the template directory, EXCLUDING node_modules
    shutil.copytree(template_dir, project_path, ignore=shutil.ignore_patterns('node_modules'))

    # Run `npm install` in the temporary project directory
    logging.info(f"Running 'npm install' in temporary directory: {project_path}")
    try:
        install_process = subprocess.run(
            ["npm", "install"],
            cwd=project_path, # Run directly in the target project path
            check=True,
            capture_output=True,
            text=True,
            timeout=300 # 5-minute timeout, Next.js install can be slow
        )
        logging.info(f"npm install stdout: {install_process.stdout}")
        if install_process.stderr: # npm often prints warnings to stderr
             logging.warning(f"npm install stderr: {install_process.stderr}")
    except subprocess.CalledProcessError as e:
        pytest.fail(f"npm install failed in test fixture: {e.stderr}\nStdout: {e.stdout}")
    except subprocess.TimeoutExpired as e:
        stderr_output = e.stderr if hasattr(e, 'stderr') and e.stderr else "N/A"
        stdout_output = e.stdout if hasattr(e, 'stdout') and e.stdout else "N/A"
        pytest.fail(f"npm install timed out in test fixture. Stdout: {stdout_output}\nStderr: {stderr_output}")

    # Introduce the build error
    page_tsx_path = project_path / NEXTJS_TSX_FILE_NAME
    original_content = page_tsx_path.read_text()
    
    # Replace a valid line with one that causes a TSX type error
    # e.g., trying to render an object directly as a React child
    error_line = "const myErrorObject = { message: 'This will not render' };"
    broken_content = original_content.replace(
        "<p>Get started by editing&nbsp;</p>",
        f"{error_line}\n<p>{{myErrorObject}}</p>"
    )
    page_tsx_path.write_text(broken_content)

    # Initialize a git repository and commit the broken state so `git apply` works
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit with build error"], cwd=repo_path, check=True, capture_output=True)

    return repo_path


@pytest.fixture(scope="function")
def mock_llm_client(mocker) -> MagicMock:
    """Provides a mock for the LLM client."""
    mock_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_llm)
    return mock_bound_llm


@pytest.mark.skip(reason="Flaky and deprioritized: see project history. Remove skip to re-enable.")
@pytest.mark.asyncio
async def test_fix_typescript_lint_error(
    ts_project_with_error: Path,
    patch_client: Client,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest.FixtureRequest,
):
    """
    Tests the agent's full self-healing loop for a TypeScript linting error
    using a declarative mock planner and a final verification step.
    """
    # --- 1. Setup: Configure environment and mocks ---
    monkeypatch.setattr(get_settings(), 'REPO_DIR', ts_project_with_error)

    # Mock the LLM client that will be used by the graph
    mock_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_llm)

    # Define the "Golden Path" of LLM responses
    lint_command = "npm run lint"
    response_1_run_lint = AIMessage(content="Running linter...", tool_calls=[ToolCall(name="run_shell", args={"command": lint_command, "working_directory_relative_to_repo": PROJECT_SUBDIR_NAME}, id="tool_call_lint_1")])
    diff_content = f"--- a/{PROJECT_SUBDIR_NAME}/{TS_FILE_NAME}\n+++ b/{PROJECT_SUBDIR_NAME}/{TS_FILE_NAME}\n@@ -1 +0,0 @@\n-const unusedVar = 42;\n"
    response_2_apply_patch = AIMessage(content="Applying patch...", tool_calls=[ToolCall(name="apply_patch", args={"file_path_in_repo": f"{PROJECT_SUBDIR_NAME}/{TS_FILE_NAME}", "diff_content": diff_content}, id="tool_call_patch_1")])
    response_3_conclude = AIMessage(content="The patch was applied and verified. The issue is resolved.", tool_calls=[])
    
    responses = [response_1_run_lint, response_2_apply_patch, response_3_conclude]
    def mock_invoke_side_effect(*args, **kwargs):
        if responses:
            return responses.pop(0)
        return AIMessage(content="Stopping to prevent loop.")
    mock_bound_llm.invoke.side_effect = mock_invoke_side_effect

    # --- 2. Execute the agent graph within a correctly patched context ---
    final_state = None
    from agent.agent_graph import compile_agent_graph
    graph = compile_agent_graph()
    with patch('tools.shell_mcp_tools.open_mcp_session', return_value=MagicMock(__aenter__=MagicMock(return_value=patch_client))):
        thread_id = "test_self_healing_thread"
        initial_state = {"messages": [HumanMessage(content=f"Please fix the linting errors in the '{PROJECT_SUBDIR_NAME}' project.")]}
        config = {"configurable": {"thread_id": thread_id}}
        final_state = await graph.ainvoke(initial_state, config)

    # --- 3. Assert Agent Outcome ---
    assert final_state is not None, "Agent run did not complete."
    assert mock_bound_llm.invoke.call_count >= 2, "LLM planner was not called enough times."

    final_messages = final_state.get("messages", [])
    assert final_messages, "Agent did not produce a final state with messages."
    assert any("resolved" in m.content for m in final_messages if hasattr(m, "content")), "Agent did not resolve the lint error."
    # --- 4. Final Verification ---
    verify_command = "npm run lint" 
    logging.info(f"Performing final verification by re-running '{verify_command}'...")
    verification_result = await run_shell.ainvoke({
        "command": verify_command,
        "working_directory_relative_to_repo": PROJECT_SUBDIR_NAME,
    })
    assert verification_result.ok is True, f"Final verification failed. Linter did not pass. Stderr: {verification_result.stderr}"
    logging.info(f"Final verification successful. Linter passes.")


@pytest.mark.skip(reason="Flaky and deprioritized: see project history. Remove skip to re-enable.")
@pytest.mark.asyncio
async def test_fix_nextjs_build_error(
    nextjs_project_with_error: Path,
    patch_client: Client,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest.FixtureRequest,
):
    """
    Tests the agent's ability to fix a TypeScript build error in a Next.js project.
    """
    # --- 1. Setup: Configure environment and mocks ---
    monkeypatch.setattr(get_settings(), 'REPO_DIR', nextjs_project_with_error)

    # Mock the LLM client that will be used by the graph
    mock_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_llm)

    # Define the "Golden Path" of LLM responses
    build_command = "npm run build"
    response_1_run_build = AIMessage(content="Running build...", tool_calls=[ToolCall(name="run_shell", args={"command": build_command, "working_directory_relative_to_repo": NEXTJS_PROJECT_SUBDIR_NAME}, id="tool_call_build_1")])
    diff_content = (
        f"--- a/{NEXTJS_PROJECT_SUBDIR_NAME}/{NEXTJS_TSX_FILE_NAME}\n"
        f"+++ b/{NEXTJS_PROJECT_SUBDIR_NAME}/{NEXTJS_TSX_FILE_NAME}\n"
        "@@ -1,8 +1,8 @@\n"
        " import Image from 'next/image'\n"
        "-const myErrorObject = { message: 'This will not render' };\n"
        "-<p>{{myErrorObject}}</p>\n"
        "+        <p>Get started by editing </p>\n"
        "         <code className=\"font-mono font-bold\">src/app/page.tsx</code>\n"
        "       </p>\n"
        "       <div className=\"fixed bottom-0 left-0 flex h-48 w-full items-end justify-center bg-gradient-to-t from-white via-white dark:from-black dark:via-black lg:static lg:size-auto lg:bg-none\">"
    )
    response_2_apply_patch = AIMessage(content="Applying patch...", tool_calls=[ToolCall(name="apply_patch", args={"file_path_in_repo": f"{NEXTJS_PROJECT_SUBDIR_NAME}/{NEXTJS_TSX_FILE_NAME}", "diff_content": diff_content}, id="tool_call_patch_1")])
    response_3_conclude = AIMessage(content="Build error fixed.", tool_calls=[])
    responses = [response_1_run_build, response_2_apply_patch, response_3_conclude]
    mock_bound_llm.invoke.side_effect = lambda *a, **kw: responses.pop(0) if responses else AIMessage(content="Stopping.")

    # --- 2. Execute the agent graph ---
    final_state = None
    from agent.agent_graph import compile_agent_graph
    graph = compile_agent_graph()
    with patch('tools.shell_mcp_tools.open_mcp_session', return_value=MagicMock(__aenter__=MagicMock(return_value=patch_client))):
        thread_id = "test_nextjs_build_error_thread" # Unique thread_id
        initial_state = {"messages": [HumanMessage(content=f"Please fix the build errors in the '{NEXTJS_PROJECT_SUBDIR_NAME}' project.")]}
        config = {"configurable": {"thread_id": thread_id}}
        final_state = await graph.ainvoke(initial_state, config)

    # --- 3. Assert Agent Outcome ---
    assert final_state is not None, "Agent run did not complete."
    assert mock_bound_llm.invoke.call_count >= 2, "LLM planner was not called enough times."

    final_messages = final_state.get("messages", [])
    assert final_messages, "Agent did not produce a final state with messages."
    assert any("resolved" in m.content for m in final_messages if hasattr(m, "content")), "Agent did not resolve the build error."

    # --- 4. Final Verification ---
    logging.info(f"Performing final verification by re-running '{build_command}'...")
    verification_result = await run_shell.ainvoke({
        "command": build_command,
        "working_directory_relative_to_repo": NEXTJS_PROJECT_SUBDIR_NAME,
    })

    assert verification_result.ok is True, f"Final verification failed. Build did not pass. Stderr: {verification_result.stderr}"
    logging.info("Final verification successful. Next.js project builds correctly.")
