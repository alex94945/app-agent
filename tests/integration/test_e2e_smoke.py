# tests/integration/test_e2e_smoke.py

import logging
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from common.config import get_settings
from agent.state import AgentState
from tools.template_init import template_init
from tools.shell_mcp_tools import run_shell


# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_scaffolding_smoke_test(agent_graph_fixture, monkeypatch, tmp_path, mcp_server_fixture):
    """
    A smoke test to verify the agent's primary scaffolding workflow.

    It uses the REAL LLM to ensure prompt engineering is effective, but patches
    the MCP client to use an in-memory server that simulates the `create-next-app`
    command, making the test fast and reliable.
    """
    logger.info("--- Starting E2E Scaffolding Smoke Test ---")
    
    # Set the REPO_DIR to our temporary directory
    repo_dir = tmp_path / "smoke_test_repo"
    repo_dir.mkdir()
    monkeypatch.setattr(get_settings(), 'REPO_DIR', repo_dir)

    # Patch the MCP session to use the in-memory server
    with patch('common.mcp_session.open_mcp_session') as mock_open_mcp:
        # The patch_client fixture is session-scoped, so we can't directly
        # use it here. Instead, we create a new client for our test server.
        from fastmcp import Client
        # The mcp_server_fixture sets this environment variable.
        mcp_server_url = os.environ["MCP_SERVER_URL"]
        client = Client(mcp_server_url.replace("/mcp", "")) # Client needs the base URL
        mock_open_mcp.return_value.__aenter__.return_value = client

        # Build the agent graph with the specific tools needed for this test.
        # The agent_graph_fixture is a factory that we must call, and then compile the result.
        tools = [template_init, run_shell]
        agent_graph = agent_graph_fixture(tools=tools).compile()

        # --- Run the agent ---
        prompt = "Create a new Next.js application called my-app."
        thread_id = f"smoke-test-{uuid.uuid4()}"
        logger.info(f"Running agent with prompt: '{prompt}'")
        final_state = await agent_graph.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": thread_id}}
        )

    # --- Assertions ---
    logger.info("--- Verifying Assertions ---")

    # 1. Verify the agent completed without error
    assert final_state is not None, "Agent run did not complete."
    final_messages = final_state.get("messages", [])
    assert final_messages, "Agent run completed with no messages."
    last_message = final_messages[-1]
    assert "error" not in last_message.content.lower(), f"Agent run ended with an error: {last_message.content}"

    # 2. Verify the side effect: the package.json file was created by the mock tool
    expected_file = repo_dir / "my-app" / "package.json"
    assert expected_file.exists(), f"Assertion failed: Expected file '{expected_file}' was not created."
    logger.info(f"✅ Assertion Passed: File '{expected_file}' exists.")

    logger.info("--- E2E Scaffolding Smoke Test Passed Successfully! ---")

# This allows running the test via `pytest`
# To run just this test: `pytest scripts/e2e_smoke.py`