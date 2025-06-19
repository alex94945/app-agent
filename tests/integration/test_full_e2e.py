# tests/integration/test_full_e2e.py

import pytest
import logging
import shutil
from pathlib import Path
import sys

# --- Add project root to sys.path to allow imports ---
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from common.config import get_settings
from langchain_core.messages import HumanMessage
from tools.shell_mcp_tools import run_shell

logger = logging.getLogger(__name__)

@pytest.fixture(scope="function")
def e2e_repo_dir(tmp_path: Path) -> Path:
    """
    Provides the repository directory for the E2E test.

    If the `E2E_OUTPUT_DIR` setting is configured, it uses that directory
    and cleans it beforehand. Otherwise, it uses a temporary directory.
    """
    settings = get_settings()
    if settings.E2E_OUTPUT_DIR:
        repo_dir = settings.E2E_OUTPUT_DIR.resolve()
        logger.info(f"Using persistent directory for E2E test output: {repo_dir}")
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        repo_dir.mkdir(parents=True, exist_ok=True)
    else:
        repo_dir = tmp_path / "e2e_repo"
        repo_dir.mkdir()
        logger.info(f"Using temporary directory for E2E test output: {repo_dir}")

    return repo_dir

@pytest.mark.e2e_full
@pytest.mark.timeout(600) # 10-minute timeout for this slow test
@pytest.mark.asyncio
async def test_full_e2e_hello_world(agent_graph_fixture, e2e_repo_dir: Path, monkeypatch):
    """
    Tests the full, unmocked agent pipeline on a simple scaffolding and
    editing task. This test uses the real LLM and real tool execution.
    It is slow and should be run selectively (e.g., in a nightly CI job).
    """
    logger.info("--- Starting Full End-to-End Test: Hello World ---")

    # 1. Setup: Use a temporary directory for the workspace
    monkeypatch.setattr(get_settings(), 'REPO_DIR', e2e_repo_dir)

    # The agent graph fixture is already compiled and ready
    agent_graph = agent_graph_fixture

    # 2. Define the multi-step prompt
    prompt = (
        "Create a new Next.js application called 'hello-world-app'. "
        "After it's created, modify the home page to display the text 'Hello, World!'."
    )
    thread_id = "e2e-full-hello-world"
    initial_state = {"messages": [HumanMessage(content=prompt)]}
    config = {"configurable": {"thread_id": thread_id}}

    # 3. Run the agent (this is the slow part)
    logger.info(f"Invoking agent for prompt: '{prompt}'")
    final_state = await agent_graph.ainvoke(initial_state, config)
    logger.info("Agent invocation complete.")

    # 4. Assertions
    logger.info("--- Verifying Assertions ---")

    # Assert 4.1: The agent completed successfully
    assert final_state is not None, "Agent run did not complete."
    final_messages = final_state.get("messages", [])
    assert final_messages, "Agent did not produce a final state with messages."
    last_message = final_messages[-1]
    assert "error" not in last_message.content.lower(), f"Agent run ended with an error: {last_message.content}"
    assert "hello, world" in last_message.content.lower(), "Agent's final message did not confirm the change."

    # Assert 4.2: The project directory and key files exist
    project_path = e2e_repo_dir / "hello-world-app"
    page_tsx_path = project_path / "src" / "app" / "page.tsx"
    assert project_path.is_dir(), f"Project directory '{project_path}' was not created."
    assert page_tsx_path.is_file(), f"Page component '{page_tsx_path}' was not created."
    logger.info("✅ Assertion Passed: Project directory and page.tsx exist.")

    # Assert 4.3: The file content was modified correctly
    page_content = page_tsx_path.read_text()
    assert "Hello, World!" in page_content, "The text 'Hello, World!' was not found in page.tsx."
    logger.info("✅ Assertion Passed: page.tsx content is correct.")

    # Assert 4.4: The generated project can be built successfully
    logger.info(f"Performing final verification by running 'npm run build' in {project_path}...")
    build_result = await run_shell.ainvoke({
        "command": "npm run build",
        "working_directory_relative_to_repo": "hello-world-app",
    })

    assert build_result.ok is True, f"Final verification failed. 'npm run build' did not pass. Stderr: {build_result.stderr}"
    logger.info("✅ Assertion Passed: `npm run build` completed successfully.")

    logger.info("--- Full End-to-End Test Passed Successfully! ---")