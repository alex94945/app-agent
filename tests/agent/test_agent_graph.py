import pytest
from unittest.mock import patch, MagicMock

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from agent.agent_graph import build_graph
from agent.state import AgentState
from common.config import settings

@patch('agent.agent_graph.planner_llm_step')
def test_run_agent_simple_flow(mock_planner_llm_step):
    """
    Tests the basic flow of the agent graph for a simple conversational response.
    """
    # 1. Setup the mock for the planner node to return a serializable AIMessage
    mock_response_content = "The capital of France is Paris."
    mock_planner_llm_step.return_value = {"messages": [AIMessage(content=mock_response_content)]}

    # 2. Build the graph *within the test* so it uses the mocked node
    graph = build_graph()

    # 3. Define inputs for the agent
    user_input = "What is the capital of France?"
    thread_id = "test-thread-simple"
    inputs = {"messages": [HumanMessage(content=user_input)]}
    config = {"configurable": {"thread_id": thread_id}}

    # 4. Run the agent by invoking the test-specific graph instance
    final_state = graph.invoke(inputs, config)

    # 5. Assertions
    mock_planner_llm_step.assert_called_once()
    call_args, _ = mock_planner_llm_step.call_args
    state_arg = call_args[0]
    assert isinstance(state_arg['messages'][0], HumanMessage)
    assert state_arg['messages'][0].content == user_input

    final_messages = final_state['messages']
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == mock_response_content

@patch('agent.agent_graph.planner_llm_step')
@patch('agent.agent_graph.tool_executor_step')
def test_agent_scaffolds_with_run_shell(mock_tool_executor, mock_planner_llm_step):
    """
    Tests that for an initial prompt, the agent's first step is to
    call the `run_shell` tool to scaffold the app.
    """
    # 1. Setup the mock for the planner node to return a tool call
    expected_tool_call = {
        "name": "run_shell",
        "args": {
            "command": 'npx create-next-app@latest my-app --typescript --tailwind --app --eslint --src-dir --import-alias \"@/*\"'
        },
        "id": "tool_call_123",
        "type": "tool_call"
    }
    mock_planner_output = {"messages": [AIMessage(content="", tool_calls=[expected_tool_call])]}
    mock_planner_llm_step.return_value = mock_planner_output

    # 2. Setup the mock for the tool executor node
    mock_tool_result = {"messages": [ToolMessage(content="Tool stub executed successfully.", tool_call_id="tool_call_123")]}
    mock_tool_executor.return_value = mock_tool_result

    # 3. Build the graph *within the test* to use the mocked nodes
    graph = build_graph()

    # 4. Define inputs for the agent
    user_input = "Create a simple counter app."
    thread_id = "test-thread-scaffold"
    inputs = {"messages": [HumanMessage(content=user_input)]}
    config = {"configurable": {"thread_id": thread_id}}

    # 5. Run the agent by invoking the test-specific graph instance
    final_state = graph.invoke(inputs, config)

    # 6. Assertions
    mock_planner_llm_step.assert_called_once()
    mock_tool_executor.assert_called_once()
    call_args, _ = mock_tool_executor.call_args
    state_arg = call_args[0]
    assert isinstance(state_arg['messages'][-1], AIMessage)
    assert state_arg['messages'][-1].tool_calls[0] == expected_tool_call

    final_messages = final_state['messages']
    assert len(final_messages) == 3 # HumanMessage, AIMessage (with tool_call), ToolMessage
    assert final_messages[1].tool_calls[0] == expected_tool_call
    assert isinstance(final_messages[2], ToolMessage)
    assert "Tool stub executed successfully." in final_messages[2].content
