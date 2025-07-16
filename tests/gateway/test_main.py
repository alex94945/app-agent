import pytest
import time
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


@patch("gateway.main.template_init", new_callable=AsyncMock)
@patch("agent.pty.manager.PTYManager.spawn", new_callable=AsyncMock)
@patch("gateway.main.compile_agent_graph")
def test_websocket_agent_integration(mock_compile_agent_graph, mock_pty_spawn, mock_template_init):
    # 1. Configure mocks
    # Mock template_init to behave like an async generator
    async def mock_template_invoke(*args, **kwargs):
        yield {"type": "file", "path": "/mock/path/package.json", "content": "{}"}
    mock_template_init.invoke.return_value = mock_template_invoke()

    # Mock PTYManager.spawn to immediately call the on_pty_complete callback
    async def mock_spawn_and_complete(*args, **kwargs):
        # The real spawn takes callbacks as arguments, find them and call them.
        on_pty_complete = kwargs.get("on_pty_complete")
        if on_pty_complete:
            task_id = args[0] if args else kwargs.get("task_id", "mock_task_id")
            await on_pty_complete(task_id, {"state": "exited", "duration_ms": 100})
    mock_pty_spawn.side_effect = mock_spawn_and_complete
    """
    Tests that the /api/agent WebSocket endpoint correctly streams back agent events.
    """
    # 1. Configure the mock for the agent graph and its stream
    mock_agent_graph = MagicMock()
    mock_compile_agent_graph.return_value = mock_agent_graph

    async def mock_event_stream(*args, **kwargs):
        from starlette.websockets import WebSocketDisconnect
        # Simulate a final message event
        yield {
            "event": "on_graph_end",
            "data": {
                "output": {
                    "messages": [AIMessage(content="This is the final agent response.")]
                }
            }
        }
        # Crucially, simulate the connection closing after the stream ends.
        # This is what the real graph would do, allowing the client to exit.
        raise WebSocketDisconnect(1000, "Stream finished")

    mock_agent_graph.astream_events = mock_event_stream

    client = TestClient(app)
    with client.websocket_connect("/api/agent") as websocket:
        # 1. Receive and verify the initial greeting
        greeting_data = websocket.receive_json()
        assert greeting_data["t"] == "final"
        assert greeting_data["d"] == "Hello, I'm App Agent. Let me know if you'd like to brainstorm your idea, or get straight into building!"

        # 2. Send a prompt to trigger the agent
        websocket.send_json({"prompt": "Hello, agent!"})

        # 3. Receive all messages until timeout, as their order is not guaranteed
        from starlette.websockets import WebSocketDisconnect
        received_messages = []
        start_time = time.time()
        while time.time() - start_time < 5: # 5-second timeout
            try:
                message = websocket.receive_json()
                received_messages.append(message)
                # Stop if we have the final agent response, as no more messages will follow
                if message.get("d") == "This is the final agent response.":
                    break
            except WebSocketDisconnect:
                break # Connection closed cleanly
            except Exception:
                break # Or other error

        # 4. Assert that all expected messages were received, regardless of order
        messages_by_type = {msg.get('t'): msg for msg in received_messages}

        assert 'file' in messages_by_type, "File message not received"
        assert messages_by_type['file']['d']['path'] == "/mock/path/package.json"

        assert 'pty_task_finished' in messages_by_type, "PTY task finished message not received"
        assert messages_by_type['pty_task_finished']['d']['state'] == "exited"

        assert 'final' in messages_by_type, "Final agent response not received"
        assert messages_by_type['final']['d'] == "This is the final agent response."
