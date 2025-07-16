import pytest
import time
import asyncio
import logging

from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from langchain_core.messages import AIMessage
from gateway.main import app

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def configure_logging_for_tests(caplog):
    """
    Configures logging for tests to ensure all logs are captured.
    """
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Logging configured for tests.")


def test_health_check():
    """
    Tests the /health endpoint to ensure the server is running and responsive.
    """
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("gateway.main.get_pty_manager", new_callable=MagicMock)
@patch("gateway.main.template_init", new_callable=MagicMock)
def test_websocket_connects_and_greets(
    mock_template_init: MagicMock,
    mock_get_pty_manager: MagicMock,
):
    """
    A simplified test to confirm that the WebSocket endpoint is alive,
    accepts a connection, and sends the initial greeting.

    This avoids the complexity of mocking the entire agent lifecycle and
    prevents the test from hanging.
    """
    # 1. Configure the minimal mocks required for the server to start
    #    and accept a connection.
    logger.info("Test: Configuring mocks...")
    mock_template_init.invoke.return_value = "/tmp/fake-project-path"

    # Configure the PTY manager mock to have an async `spawn` method
    mock_pty_instance = MagicMock()
    mock_pty_instance.spawn = AsyncMock()
    mock_get_pty_manager.return_value = mock_pty_instance

    # 2. Setup the test client and connect via WebSocket
    logger.info("Test: Connecting to WebSocket...")
    client = TestClient(app)
    with client.websocket_connect("/api/agent") as websocket:
        # 3. Assert that the server sends the initial greeting message.
        #    This proves the connection was successful and the endpoint is alive.
        logger.info("Test: Receiving greeting from server...")
        greeting = websocket.receive_json()
        logger.info(f"Test: Received greeting: {greeting}")
        assert greeting["t"] == "final"
        assert "Hello, I'm App Agent" in greeting["d"]

        # We do not test the rest of the flow to avoid brittle mocks.
        # The primary goal is to ensure the gateway's websocket is reachable.
    logger.info("Test: WebSocket test finished successfully.")
