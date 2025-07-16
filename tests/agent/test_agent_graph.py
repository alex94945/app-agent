import pytest
from unittest.mock import patch, AsyncMock

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from agent.agent_graph import build_agent_graph
from agent.state import AgentState


@patch('agent.agent_graph.planner_reason_step')
def test_run_agent_simple_flow(mock_planner_reason_step):
    """
    Tests the basic flow of the agent graph for a simple conversational response.
    The agent should call the reasoner once and terminate without calling tools.
    """
    # 1. Setup: Mock the planner_reason_step to return a final AIMessage,
    # simulating a response that doesn't require a tool.
    mock_response_content = "The capital of France is Paris."
    mock_planner_reason_step.return_value = AgentState(messages=[AIMessage(content=mock_response_content)])

    # 2. Build the graph
    graph = build_agent_graph().compile()

    # 3. Define inputs
    user_input = "What is the capital of France?"
    initial_state = AgentState(messages=[HumanMessage(content=user_input)])
    config = {"configurable": {"thread_id": "test-thread-simple"}}

    # 4. Run the agent
    final_state = graph.invoke(initial_state, config)

    # 5. Assertions
    mock_planner_reason_step.assert_called_once()
    call_args, _ = mock_planner_reason_step.call_args
    state_arg = call_args[0]
    assert isinstance(state_arg.messages[0], HumanMessage)
    assert state_arg.messages[0].content == user_input

    final_messages = final_state['messages']
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == mock_response_content

@pytest.mark.asyncio
@patch('agent.agent_graph.tool_executor_step', new_callable=AsyncMock)
@patch('agent.agent_graph.planner_reason_step')
async def test_run_agent_with_tool_flow(mock_planner_reason_step, mock_tool_executor_step):
    """
    Tests the agent flow when a tool is called.
    The flow should be: planner_reason -> tool_executor -> planner_reason -> END
    """
    # 1. Setup Mocks
    # First reasoner call decides to use a tool
    mock_planner_reason_step.side_effect = [
        AgentState(messages=[AIMessage(content="", tool_calls=[{"name": "test_tool", "args": {"arg1": "value1"}, "id": "123"}])]), # Call tool
        AgentState(messages=[AIMessage(content="Tool finished.")]) # Final response
    ]
    # Executor returns the tool's output
    mock_tool_executor_step.return_value = AgentState(messages=[ToolMessage(content="Tool output", tool_call_id="123")])

    # 2. Build Graph
    graph = build_agent_graph().compile()

    # 3. Define Inputs
    user_input = "Use the test tool."
    initial_state = AgentState(messages=[HumanMessage(content=user_input)])
    config = {"configurable": {"thread_id": "test-thread-tool"}}

    # 4. Run Agent
    final_state = await graph.ainvoke(initial_state, config)

    # 5. Assertions
    assert mock_planner_reason_step.call_count == 2
    assert mock_tool_executor_step.call_count == 1

    final_messages = final_state['messages']
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "Tool finished."

@pytest.mark.asyncio
@patch('agent.agent_graph.tool_executor_step', new_callable=AsyncMock)
@patch('agent.agent_graph.planner_reason_step')
async def test_agent_scaffolds_with_run_shell(
    mock_planner_reason_step,
    mock_tool_executor
):
    """
    Tests the updated agent flow: reason -> tool -> reason -> end.
    """
    # 1. Setup: Define a consistent tool_call_id for tracking.
    tool_call_id = "tool_call_123"

    # 2. Mock the sequence of planner and tool calls

    #   a. First reasoner call: decides to use 'run_shell' and provides all args.
    tool_call_with_args = {
        "name": "run_shell",
        "args": {
            "command": 'npx create-next-app@latest my-app --typescript --tailwind --app --eslint --src-dir --import-alias "@/*"'
        },
        "id": tool_call_id,
    }
    #   a. First reasoner call: decides to use 'run_shell' and provides all args.
    reason_step_output1 = AgentState(
        messages=[AIMessage(content="I should scaffold the app.", tool_calls=[tool_call_with_args])]
    )
    #   b. Second reasoner call: decides the task is done.
    reason_step_output2 = AgentState(
        messages=[AIMessage(content="All done!")]
    )
    mock_planner_reason_step.side_effect = [reason_step_output1, reason_step_output2]

    #   c. Tool executor call: returns a successful ToolMessage
    mock_tool_executor.return_value = AgentState(messages=[ToolMessage(content="Tool stub executed successfully.", tool_call_id=tool_call_id)])

    # 3. Build the graph
    graph = build_agent_graph().compile()

    # 4. Define inputs
    user_input = "Create a simple counter app."
    initial_state = AgentState(messages=[HumanMessage(content=user_input)])
    config = {"configurable": {"thread_id": "test-thread-scaffold"}}

    # 5. Run the agent
    final_state = await graph.ainvoke(initial_state, config)

    # 6. Assertions
    assert mock_planner_reason_step.call_count == 2
    mock_tool_executor.assert_awaited_once()

    # Check the input to the tool executor
    call_args, _ = mock_tool_executor.call_args
    state_arg = call_args[0]
    last_message = state_arg.messages[-1]
    assert isinstance(last_message, AIMessage)
    assert last_message.tool_calls[0]['name'] == tool_call_with_args['name']
    assert last_message.tool_calls[0]['args'] == tool_call_with_args['args']
    assert last_message.tool_calls[0]['id'] == tool_call_with_args['id']

    # Check the final state
    final_messages = final_state['messages']
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "All done!"
