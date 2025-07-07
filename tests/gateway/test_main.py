import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute # For debug printing
from starlette.routing import WebSocketRoute # For debug printing
from gateway.main import app

def test_health_check():
    """
    Tests the /health endpoint to ensure the server is running and responsive.
    """
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@patch('gateway.main.run_agent', new_callable=AsyncMock)
def test_websocket_agent_integration(mock_run_agent):
    """
    Tests that the /api/agent WebSocket endpoint correctly calls the agent
    and forwards its response.
    """
    # Debug: Print registered WebSocket routes
    ws_paths = [r.path for r in app.routes if isinstance(r, WebSocketRoute)]
    print("Registered WebSocket routes:", ws_paths)
    http_paths = [r.path for r in app.routes if isinstance(r, APIRoute)]
    print("Registered HTTP routes:", http_paths)
    # 1. Configure the mock for the agent function
    mock_response = "This is the agent's mocked response."
    mock_run_agent.return_value = MagicMock(content=mock_response)

    client = TestClient(app)
    with client.websocket_connect("/api/agent") as websocket:
        # 2. Define the message to send
        test_prompt = "Hello, agent!"
        message_to_send = {"prompt": test_prompt}

        # 3. Send the message to the server
        websocket.send_json(message_to_send)

        # 4. Receive the response from the server
        data = websocket.receive_json()

        # 5. Assert the response is correct based on our schema and mock
        assert "t" in data
        assert "d" in data
        assert data["t"] == "final"
        assert data["d"] == mock_response

        # 6. Assert that the agent function was called correctly
        mock_run_agent.assert_called_once()
        call_args, _ = mock_run_agent.call_args
        assert call_args[0] == test_prompt
