import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from gateway.main import app


def test_health_check():
    """
    Tests the /health endpoint to ensure the server is running and responsive.
    """
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("gateway.main.compile_agent_graph")
def test_websocket_agent_integration(mock_compile_agent_graph):
    """
    Tests that the /api/agent WebSocket endpoint correctly streams back agent events.
    """
    # 1. Configure the mock for the agent graph and its stream
    mock_agent_graph = MagicMock()
    mock_compile_agent_graph.return_value = mock_agent_graph

    async def mock_event_stream(*args, **kwargs):
        # Simulate a final message event
        yield {
            "event": "on_graph_end",
            "data": {
                "output": {
                    "messages": [AIMessage(content="This is the final agent response.")]
                }
            }
        }

    mock_agent_graph.astream_events = mock_event_stream

    client = TestClient(app)
    with client.websocket_connect("/api/agent") as websocket:
        # 2. Send a prompt
        test_prompt = "Hello, agent!"
        websocket.send_json({"prompt": test_prompt})

        # 4. Receive the response from the server
        data = websocket.receive_json()

        # 5. Assert the response is correct based on our schema and mock
        assert data["t"] == "final"
        assert data["d"] == "This is the final agent response."
