import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from gateway.main import app

# Create a TestClient instance for our FastAPI app
client = TestClient(app)

def test_health_check():
    """
    Tests the /health endpoint to ensure the server is running and responsive.
    """
    # Make a GET request to the /health endpoint
    response = client.get("/health")
    
    # Assert that the HTTP status code is 200 (OK)
    assert response.status_code == 200
    
    # Assert that the response body is the expected JSON
    assert response.json() == {"status": "ok"}

@patch('gateway.main.run_agent')
def test_websocket_agent_integration(mock_run_agent):
    """
    Tests that the /api/agent WebSocket endpoint correctly calls the agent
    and forwards its response.
    """
    # 1. Configure the mock for the agent function
    mock_response = "This is the agent's mocked response."
    mock_run_agent.return_value = mock_response

    # TestClient provides a context manager for WebSocket testing
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
        assert data["t"] == "final" # Expecting a FinalMessage
        assert data["d"] == mock_response

        # 6. Assert that the agent function was called correctly
        mock_run_agent.assert_called_once()
        # We can also check the arguments it was called with
        call_args, _ = mock_run_agent.call_args
        assert call_args[0] == test_prompt # The user_input
        # call_args[1] is the uuid thread_id, which is harder to assert,
        # so we just check that the prompt was passed correctly.
