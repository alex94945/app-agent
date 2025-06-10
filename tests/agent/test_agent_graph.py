import pytest
from unittest.mock import patch, MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from agent.agent_graph import run_agent, build_graph
from agent.state import AgentState
from common.config import settings

@patch('agent.agent_graph.get_llm_client')
def test_run_agent_simple_flow(mock_get_llm_client):
    """
    Tests the basic flow of the agent graph:
    - Takes user input.
    - Calls the mocked LLM.
    - Returns the mocked LLM's response.
    """
    # 1. Setup the mock for the LLM
    mock_llm_instance = MagicMock()
    mock_response_content = "The capital of France is Paris."
    mock_llm_instance.invoke.return_value = AIMessage(content=mock_response_content)
    mock_get_llm_client.return_value = mock_llm_instance

    # 2. Define inputs for the agent
    user_input = "What is the capital of France?"
    thread_id = "test-thread-123"

    # 3. Run the agent
    # We need to ensure the graph is rebuilt for the test to use the mock
    # A simple way is to patch the global instance or call build_graph directly
    with patch('agent.agent_graph.agent_graph', build_graph()):
        final_response = run_agent(user_input, thread_id)

    # 4. Assertions
    # Check that our factory function was called
    mock_get_llm_client.assert_called_once_with(purpose="planner")
    
    # Check that the LLM was invoked with the correct message history
    mock_llm_instance.invoke.assert_called_once()
    call_args, _ = mock_llm_instance.invoke.call_args
    sent_messages = call_args[0]
    assert len(sent_messages) == 1
    assert isinstance(sent_messages[0], HumanMessage)
    assert sent_messages[0].content == user_input

    # Check that the final response is what we expect from the mock
    assert final_response == mock_response_content
