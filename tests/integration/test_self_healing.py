# tests/integration/test_self_healing.py

import pytest
import subprocess
import json
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncGenerator
from unittest.mock import patch, MagicMock

from common.config import get_settings
from fastmcp import Client
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from langgraph.graph.graph import CompiledGraph
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

@pytest.fixture(scope="session")
def agent_graph_fixture() -> CompiledGraph:
    """Compile the agent graph once per session for performance."""
    from agent.agent_graph import build_graph
    return build_graph()

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


# --- Add this new fixture to the file ---

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


@pytest.fixture
def mock_llm_client(mocker: MagicMock) -> MagicMock:
    """
    Mocks the get_llm_client function to return a mock LLM client
    that can be configured with a side_effect list of responses.
    """
    mock_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_llm)
    return mock_bound_llm


@pytest.mark.asyncio
async def test_fix_typescript_lint_error(
    agent_graph_fixture: CompiledGraph,
    ts_project_with_error: Path,
    mock_llm_client: MagicMock,
    patch_client: Client,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Tests the agent's full self-healing loop for a TypeScript linting error
    using a declarative mock LLM and a final verification step.
    """
    # --- 1. Setup: Configure environment and mocks ---
    monkeypatch.setattr(get_settings(), 'REPO_DIR', ts_project_with_error)

    # Define the "Golden Path" of LLM responses
    # Use `npx --no-install` to robustly execute the local binary.
    lint_command = "npx --no-install eslint src/index.ts"
    response_1_run_lint = AIMessage(
        content="Okay, I will run the linter to check for issues.",
        tool_calls=[ToolCall(name="run_shell", args={"command": lint_command, "working_directory_relative_to_repo": PROJECT_SUBDIR_NAME}, id="tool_call_lint_1")]
    )
    diff_content = f"--- a/{PROJECT_SUBDIR_NAME}/{TS_FILE_NAME}\n+++ b/{PROJECT_SUBDIR_NAME}/{TS_FILE_NAME}\n@@ -1 +0,0 @@\n-const unusedVar = 42;\n"
    response_2_apply_patch = AIMessage(
        content="The linter found an unused variable. I will apply a patch to remove it.",
        tool_calls=[ToolCall(name="apply_patch", args={"file_path_in_repo": f"{PROJECT_SUBDIR_NAME}/{TS_FILE_NAME}", "diff_content": diff_content}, id="tool_call_patch_1")]
    )
    response_3_conclude = AIMessage(
        content="The patch was applied successfully, and the linter now passes. The issue is resolved.",
        tool_calls=[]
    )
    mock_llm_client.invoke.side_effect = [response_1_run_lint, response_2_apply_patch, response_3_conclude]

    # --- 2. Execute the agent graph within a correctly patched context ---
    final_state = None
    # Patch open_mcp_session in all modules where it is imported and used.
    with patch('tools.shell_mcp_tools.open_mcp_session') as mock_shell_mcp:

        # Configure all mocks to return the same in-memory client
        mock_shell_mcp.return_value.__aenter__.return_value = patch_client

        thread_id = "test_self_healing_thread"
        initial_state = {"messages": [HumanMessage(content=f"Please fix the linting errors in the '{PROJECT_SUBDIR_NAME}' project.")]}
        config = {"configurable": {"thread_id": thread_id}}

        final_state = await agent_graph_fixture.ainvoke(initial_state, config)

    # --- 3. Assert Agent Outcome ---
    assert final_state is not None, "Agent run did not complete."
    assert mock_llm_client.invoke.call_count == 3, "LLM planner was not called the expected number of times."

    final_messages = final_state.get("messages", [])
    assert final_messages, "Agent did not produce a final state with messages."
    last_message = final_messages[-1]
    assert isinstance(last_message, AIMessage) and not last_message.tool_calls
    assert "resolved" in last_message.content or "passes" in last_message.content

    # --- 4. Final Verification ---
    # Explicitly re-run the lint command to prove the fix was effective.
    logging.info(f"Performing final verification by re-running '{lint_command}'...")
    verification_result = await run_shell.ainvoke({
        "command": lint_command,
        "working_directory_relative_to_repo": PROJECT_SUBDIR_NAME,
    })

    assert verification_result.ok is True, f"Final verification failed. Linter did not pass. Stderr: {verification_result.stderr}"
    logging.info(f"Final verification successful. Linter passes.")


# --- Add this new test to the file ---

@pytest.mark.asyncio
async def test_fix_nextjs_build_error(
    agent_graph_fixture: CompiledGraph,
    nextjs_project_with_error: Path,
    mock_llm_client: MagicMock,
    patch_client: Client,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Tests the agent's ability to fix a TypeScript build error in a Next.js project.
    """
    # --- 1. Setup: Configure environment and mocks ---
    monkeypatch.setattr(get_settings(), 'REPO_DIR', nextjs_project_with_error)

    # Define the "Golden Path" of LLM responses
    build_command = "npm run build"
    response_1_run_build = AIMessage(
        content="Okay, I will run the build command to check for issues.",
        tool_calls=[ToolCall(name="run_shell", args={"command": build_command, "working_directory_relative_to_repo": NEXTJS_PROJECT_SUBDIR_NAME}, id="tool_call_build_1")]
    )

    # This diff reverses the change made in the fixture
    diff_content = (
        f"--- a/{NEXTJS_PROJECT_SUBDIR_NAME}/{NEXTJS_TSX_FILE_NAME}\n"
        f"+++ b/{NEXTJS_PROJECT_SUBDIR_NAME}/{NEXTJS_TSX_FILE_NAME}\n"
        "@@ -13,7 +13,7 @@\n"
        "       <p\n"
        "         className=\"fixed left-0 top-0 flex w-full justify-center border-b border-gray-300 bg-gradient-to-b from-zinc-200 pb-6 pt-8 backdrop-blur-2xl dark:border-neutral-800 dark:bg-zinc-800/30 dark:from-inherit lg:static lg:w-auto  lg:rounded-xl lg:border lg:bg-gray-200 lg:p-4 lg:dark:bg-zinc-800/30\"\n"
        "       >\n"
        "-        const myErrorObject = { message: 'This will not render' };\n"
        "-<p>{{myErrorObject}}</p>\n"
        "+        <p>Get started by editing&nbsp;</p>\n"
        "         <code className=\"font-mono font-bold\">src/app/page.tsx</code>\n"
        "       </p>\n"
        "       <div className=\"fixed bottom-0 left-0 flex h-48 w-full items-end justify-center bg-gradient-to-t from-white via-white dark:from-black dark:via-black lg:static lg:size-auto lg:bg-none\">"
    )
    response_2_apply_patch = AIMessage(
        content="The build failed with a type error. I will apply a patch to fix it.",
        tool_calls=[ToolCall(name="apply_patch", args={"file_path_in_repo": f"{NEXTJS_PROJECT_SUBDIR_NAME}/{NEXTJS_TSX_FILE_NAME}", "diff_content": diff_content}, id="tool_call_patch_1")]
    )

    response_3_conclude = AIMessage(
        content="The patch was applied, and the build should now succeed. The issue is resolved.",
        tool_calls=[]
    )
    mock_llm_client.invoke.side_effect = [response_1_run_build, response_2_apply_patch, response_3_conclude]

    # --- 2. Execute the agent graph ---
    final_state = None
    with patch('tools.shell_mcp_tools.open_mcp_session') as mock_shell_mcp:

        mock_shell_mcp.return_value.__aenter__.return_value = patch_client

        thread_id = "test_nextjs_build_error_thread" # Unique thread_id
        initial_state = {"messages": [HumanMessage(content=f"Please fix the build errors in the '{NEXTJS_PROJECT_SUBDIR_NAME}' project.")]}
        config = {"configurable": {"thread_id": thread_id}}

        final_state = await agent_graph_fixture.ainvoke(initial_state, config)

    # --- 3. Assert Agent Outcome ---
    assert final_state is not None, "Agent run did not complete."
    assert mock_llm_client.invoke.call_count == 3, "LLM planner was not called the expected number of times."

    final_messages = final_state.get("messages", [])
    assert final_messages, "Agent did not produce a final state with messages."
    last_message = final_messages[-1]
    assert isinstance(last_message, AIMessage) and not last_message.tool_calls, "Last message should be an AIMessage with no tool calls."
    assert "resolved" in last_message.content or "succeed" in last_message.content, "Final message content does not indicate resolution."

    # --- 4. Final Verification ---
    logging.info(f"Performing final verification by re-running '{build_command}'...")
    verification_result = await run_shell.ainvoke({
        "command": build_command,
        "working_directory_relative_to_repo": NEXTJS_PROJECT_SUBDIR_NAME,
    })

    assert verification_result.ok is True, f"Final verification failed. Build did not pass. Stderr: {verification_result.stderr}"
    logging.info("Final verification successful. Next.js project builds correctly.")
