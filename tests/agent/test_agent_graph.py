import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# Import ToolPicker for mocking
from agent.agent_graph import build_state_graph, ToolPicker
from agent.state import AgentState
from common.config import settings

# Note: The original tests patched `planner_llm_step`. This has been refactored into
# `planner_reason_step` and `planner_arg_step`. The tests are updated accordingly.

@patch('agent.agent_graph.planner_reason_step')
def test_run_agent_simple_flow(mock_planner_reason_step):
    """
    Tests the basic flow of the agent graph for a simple conversational response.
    The agent should call the reasoner once and terminate without calling tools.
    """
    # 1. Setup: Mock the planner_reason_step to return a final AIMessage,
    # simulating a response that doesn't require a tool.
    mock_response_content = "The capital of France is Paris."
    mock_planner_reason_step.return_value = {"messages": [AIMessage(content=mock_response_content)]}

    # 2. Build the graph
    graph = build_state_graph().compile()

    # 3. Define inputs
    user_input = "What is the capital of France?"
    inputs = {"messages": [HumanMessage(content=user_input)]}
    config = {"configurable": {"thread_id": "test-thread-simple"}}

    # 4. Run the agent
    final_state = graph.invoke(inputs, config)

    # 5. Assertions
    mock_planner_reason_step.assert_called_once()
    call_args, _ = mock_planner_reason_step.call_args
    state_arg = call_args[0]
    assert isinstance(state_arg['messages'][0], HumanMessage)
    assert state_arg['messages'][0].content == user_input

    final_messages = final_state['messages']
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == mock_response_content

@pytest.mark.asyncio
@patch('agent.agent_graph.tool_executor_step', new_callable=AsyncMock)
@patch('agent.agent_graph.planner_arg_step')
@patch('agent.agent_graph.planner_reason_step')
async def test_agent_scaffolds_with_run_shell(
    mock_planner_reason_step,
    mock_planner_arg_step,
    mock_tool_executor
):
    """
    Tests the two-step planner flow: reason -> args -> tool -> reason -> end.
    """
    # 1. Setup: Define a consistent tool_call_id for tracking.
    tool_call_id = "tool_call_123"

    # 2. Mock the sequence of planner and tool calls

    #   a. First reasoner call: decides to use 'run_shell'.
    #      This step only decides the tool name and provides reasoning.
    reason_step_output1 = {
        "next_tool_to_call": "run_shell",
        "messages": [AIMessage(content="I should scaffold the app.")]
    }
    #      Second reasoner call: decides the task is done.
    reason_step_output2 = {
        "next_tool_to_call": None,
        "messages": [AIMessage(content="All done!")]
    }
    mock_planner_reason_step.side_effect = [reason_step_output1, reason_step_output2]

    #   b. Argument generation call: provides args for 'run_shell'.
    #      This step creates the full AIMessage with the tool_calls dict.
    tool_call_with_args = {
        "name": "run_shell",
        "args": {
            "command": 'npx create-next-app@latest my-app --typescript --tailwind --app --eslint --src-dir --import-alias "@/*"'
        },
        "id": tool_call_id,
    }
    arg_step_output = {
        "messages": [AIMessage(content="", tool_calls=[tool_call_with_args])]
    }
    mock_planner_arg_step.return_value = arg_step_output

    #   c. Tool executor call: returns a successful ToolMessage
    mock_tool_executor.return_value = {"messages": [ToolMessage(content="Tool stub executed successfully.", tool_call_id=tool_call_id)]}

    # 3. Build the graph
    graph = build_state_graph().compile()

    # 4. Define inputs
    user_input = "Create a simple counter app."
    inputs = {"messages": [HumanMessage(content=user_input)]}
    config = {"configurable": {"thread_id": "test-thread-scaffold"}}

    # 5. Run the agent
    final_state = await graph.ainvoke(inputs, config)

    # 6. Assertions
    assert mock_planner_reason_step.call_count == 2
    mock_planner_arg_step.assert_called_once()
    mock_tool_executor.assert_awaited_once()

    # Check the input to the tool executor
    call_args, _ = mock_tool_executor.call_args
    state_arg = call_args[0]
    # The last message before the tool executor should be the one from the arg_step
    last_message = state_arg['messages'][-1]
    assert isinstance(last_message, AIMessage)
    # Langchain adds the 'type' field, so we compare the rest of the dict
    assert last_message.tool_calls[0]['name'] == tool_call_with_args['name']
    assert last_message.tool_calls[0]['args'] == tool_call_with_args['args']
    assert last_message.tool_calls[0]['id'] == tool_call_with_args['id']

    # Check the final state
    final_messages = final_state['messages']
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "All done!"
