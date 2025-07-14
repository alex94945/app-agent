# tests/live_e2e/test_live_e2e.py

# By being in a separate directory `live_e2e`, this test avoids loading
# the mock fixtures from `tests/integration/conftest.py`.
# IMPORTANT: This test will not mock ANYTHING! The point is to test the
# full end-to-end flow with real tools, real LLM calls, everything is real.

from contextlib import asynccontextmanager
from unittest.mock import patch
from fastmcp import Client
import pytest
import logging
from pathlib import Path

import io
import shutil
import sys
import subprocess
import json
import os
import re
from langchain.schema import HumanMessage

logger = logging.getLogger(__name__)

def slugify(text):
    # A simple slugify function to convert prompt to a valid directory name
    text = text.lower()
    text = re.sub(r'[\s\W-]+', '-', text).strip('-')
    return text


@pytest.fixture(scope="function")
def live_e2e_repo_dir(tmp_path: Path) -> Path:
    """
    Provides a clean, temporary git repository for the live E2E test to run in.
    This fixture ensures the agent operates in an isolated environment.
    """
    repo_dir = tmp_path / "live_e2e_repo"
    repo_dir.mkdir()
    logger.info(f"Using temporary directory for E2E test output: {repo_dir}")
    logger.debug(f"Test environment: cwd={os.getcwd()} PATH={os.environ.get('PATH')}")
    logger.debug(f"Test environment variables: {json.dumps(dict(os.environ), indent=2)}")

    # Initialize a git repository, as the agent's patch tool requires it.
    logger.info("Initializing git repository for live E2E test...")
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    logger.info(f"Live E2E test running in: {repo_dir}")
    logger.debug(f"Repo contents after init: {os.listdir(repo_dir)}")
    
    yield repo_dir
    
    logger.info(f"Live E2E test finished in: {repo_dir}")
    logger.debug(f"Repo contents at teardown: {os.listdir(repo_dir)}")


@pytest.mark.live_e2e
@pytest.mark.e2e_live
@pytest.mark.timeout(1200)
@pytest.mark.asyncio
async def test_live_full_e2e(live_e2e_repo_dir: Path, prompt: str, live_mcp_client: Client, request, monkeypatch):
    app_slug = slugify(prompt)
    """
    Tests the full, unmocked agent pipeline on a simple scaffolding and
    editing task. This test uses REAL implementations of all tools.
    It is parametrized by the 'prompt' fixture, which is populated by the
    --prompts CLI argument.
    """
    logger.info(f"--- Starting LIVE End-to-End Test for prompt: '{prompt}' ---")

    save_app = request.config.getoption("--save-app")
    if save_app:
        from pathlib import Path
        live_e2e_repo_dir = Path.cwd()

    # Ensure all shell.run cwd paths resolve under this repo directory
    workspace_path = live_e2e_repo_dir / "workspace_dev"
    if workspace_path.exists():
        shutil.rmtree(workspace_path) # Redundant given tmp_path, but safe
    workspace_path.mkdir()

    # Configure the settings to use our temporary workspace
    from common import config
    config.get_settings.cache_clear()
    monkeypatch.setattr(config.settings, 'REPO_DIR', workspace_path)

    # Build the agent graph using its default (production) tools.
    # These tools will connect to the live_mcp_server_fixture.
    from agent.agent_graph import compile_agent_graph

    # Forcefully capture logs from the agent graph
    agent_logger = logging.getLogger("agent.agent_graph")
    log_capture_string = io.StringIO()
    log_handler = logging.StreamHandler(log_capture_string)
    agent_logger.addHandler(log_handler)

    agent_graph = compile_agent_graph(interrupt_before=[])

    app_slug = None
    final_state = None # Ensure final_state is defined
    import time
    try:
        thread_id = f"live-e2e-test-{os.getpid()}"
        # The agent graph now handles the initial prompt logic based on iteration count.
        # We just need to pass the user's raw request.
        initial_state = {"messages": [HumanMessage(content=prompt)]}
        config = {"configurable": {"thread_id": thread_id}}

        logger.info(f"[E2E] Current working directory: {os.getcwd()}")
        logger.info(f"[E2E] PATH: {os.environ.get('PATH')}")
        logger.info(f"[E2E] Environment variables: {json.dumps(dict(os.environ), indent=2)}")
        logger.info(f"[E2E] Workspace path: {workspace_path} contents: {os.listdir(workspace_path)}")

        logger.info(f"Invoking agent for prompt: '{prompt}'")
        t0 = time.time()
        # Create a mock context manager that yields our live client
        @asynccontextmanager
        async def mock_mcp_session_cm():
            yield live_mcp_client

        # Forcefully patch the session opener in the tool modules
        with patch('tools.shell_mcp_tools.open_mcp_session', new=mock_mcp_session_cm):
            try:
                final_state = await agent_graph.ainvoke(initial_state, config)
            finally:
                t1 = time.time()
                logger.info(f"Agent invocation elapsed time: {t1-t0:.2f} seconds")
        logger.info("Agent invocation complete.")
    
        app_slug = final_state.get("project_subdirectory")
        logger.info(f"[E2E] Agent output project_subdirectory: {app_slug}")
    finally:
        if app_slug:
            logger.info(f"Generated app output directory: {workspace_path / app_slug}")
        else:
            logger.info(f"Generated app output directory: {workspace_path} (app_slug unknown)")
        # This block now only handles logging and cleanup
        log_contents = log_capture_string.getvalue()
        if sys.exc_info()[0] or not app_slug: # Log on error or if slug not set
            logger.error(f"--- Captured agent.agent_graph logs ---\n{log_contents}\n---------------------------------")
            if final_state:
                messages = final_state.get("messages", [])
                logger.error(f"--- Message History on Failure ---\n{messages}\n---------------------------------")
                # Explicitly log the final AI message content
                if messages and hasattr(messages[-1], 'content'):
                    logger.error(f"--- Final AI Message Content ---\n{messages[-1].content}\n---------------------------------")
        agent_logger.removeHandler(log_handler)
    
    # --- Assertions ---
    assert app_slug, "Agent did not set project_subdirectory in its final state."
    logger.info("--- Verifying Assertions ---")

    project_path = workspace_path / app_slug
    page_tsx_path = project_path / "src" / "app" / "page.tsx"

    assert project_path.is_dir(), f"Project directory '{project_path}' was not created."
    assert page_tsx_path.is_file(), f"Page component '{page_tsx_path}' was not created."
    logger.info("✅ Assertion Passed: Project directory and page.tsx exist.")
    
    # Generic check: The page should contain some content.
    assert page_tsx_path.read_text().strip(), f"Page component '{page_tsx_path}' is empty."

    package_json_path = project_path / "package.json"
    assert package_json_path.is_file(), "package.json was not created."
    package_data = json.loads(package_json_path.read_text())
    dependencies = package_data.get("dependencies", {})
    assert "next" in dependencies, "'next' not found in package.json dependencies"
    assert "react" in dependencies, "'react' not found in package.json dependencies"
    logger.info("✅ Assertion Passed: package.json dependencies are correct.")

    logger.info(f"Performing final verification by running 'npm run build' in {project_path}...")
    # We need to import the original tool to call it for verification
    from tools.shell_mcp_tools import run_shell
    build_result = await run_shell.ainvoke({
        "command": "npm run build",
        "working_directory_relative_to_repo": app_slug,
    })

    assert build_result.ok, f"Final verification failed. 'npm run build' did not pass.\nSTDOUT:\n{build_result.stdout}\nSTDERR:\n{build_result.stderr}"
    logger.info("✅ Assertion Passed: `npm run build` completed successfully.")
    logger.info(f"--- LIVE End-to-End Test for prompt '{prompt}' Passed Successfully! ---")
    logger.info(f"Generated app output directory: {project_path}")