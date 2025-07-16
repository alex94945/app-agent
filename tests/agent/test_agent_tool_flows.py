# tests/agent/test_agent_tool_flows.py
import pytest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

from agent.state import AgentState

# Ensure all tools are loaded for potential mocking/inspection if needed by name
# (No need to import build_agent_graph or ALL_TOOLS_LIST at module level)

@pytest.mark.asyncio
@patch('agent.agent_graph.planner_reason_step', new_callable=MagicMock)
@patch('agent.agent_graph.tool_executor_step', new_callable=MagicMock)
async def test_initial_create_app_flow_uses_run_shell(mock_tool_executor_step, mock_planner_reason_step, fix_cycle_tracker):
    # Add a print side effect to the executor mock
    def executor_side_effect(*args, **kwargs):
        print("MOCK TOOL EXECUTOR CALLED")
        return {
            "messages": [ToolMessage(content="App created.", tool_call_id="tool_call_123")],
            "fix_cycle_tracker": fix_cycle_tracker
        }
    mock_tool_executor_step.side_effect = executor_side_effect
    # 1. Setup Mocks
    tool_call_id = "tool_call_123"
    tool_call = ToolCall(
        name="run_shell",
        args={"command": "npx create-next-app@latest my-app"},
        id=tool_call_id
    )
    mock_planner_reason_step.side_effect = [
        {"messages": [AIMessage(content="Okay, creating the app.", tool_calls=[tool_call])]},
        {"messages": [AIMessage(content="App created successfully.")]}
    ]

    # 2. Build the graph after patching
    from agent.agent_graph import build_agent_graph
    graph = build_agent_graph().compile()

    # 3. Define Inputs and run agent
    initial_state = AgentState(messages=[HumanMessage(content="Create a new Next.js app called my-app")])
    config = {"configurable": {"thread_id": "test-create-app"}}
    final_state = await graph.ainvoke(initial_state, config)

    # 4. Assertions
    assert mock_planner_reason_step.call_count == 2
    mock_tool_executor_step.assert_called_once()

    # Check the state passed to the tool executor
    call_args, _ = mock_tool_executor_step.call_args
    state_arg = call_args[0]  # Get the state object from mock args
    last_message = state_arg.messages[-1]
    tool_call = last_message.tool_calls[0]
    if isinstance(tool_call, dict):
        assert tool_call["name"] == "run_shell"
    else:
        assert tool_call.name == "run_shell"

    # Check the final message
    assert final_state['messages'][-1].content == "App created successfully."


@pytest.mark.asyncio
@patch('agent.agent_graph.planner_reason_step', new_callable=MagicMock)
@patch('agent.agent_graph.tool_executor_step', new_callable=MagicMock)
async def test_multi_step_flow(mock_tool_executor_step, mock_planner_reason_step, fix_cycle_tracker):
    # Add a print side effect to the executor mock
    def executor_side_effect(*args, **kwargs):
        print("MOCK TOOL EXECUTOR CALLED")
        # Determine which tool_call_id to use based on the input
        tool_call = args[0].messages[-1].tool_calls[0]
        tool_call_id = tool_call["id"] if isinstance(tool_call, dict) else tool_call.id
        if tool_call_id == "read_call_456":
            return {
                "messages": [ToolMessage(content="content from a", tool_call_id="read_call_456")],
                "fix_cycle_tracker": fix_cycle_tracker
            }
        else:
            return {
                "messages": [ToolMessage(content="File written.", tool_call_id="write_call_789")],
                "fix_cycle_tracker": fix_cycle_tracker
            }
    mock_tool_executor_step.side_effect = executor_side_effect
    # 1. Setup Mocks
    read_tool_call_id = "read_call_456"
    write_tool_call_id = "write_call_789"
    read_tool_call = ToolCall(name="read_file", args={"path_in_repo": "a.txt"}, id=read_tool_call_id)
    write_tool_call = ToolCall(name="write_file", args={"path_in_repo": "b.txt", "content": "content from a"}, id=write_tool_call_id)

    # Mock the planner to first call read_file, then write_file, then finish.
    mock_planner_reason_step.side_effect = [
        {"messages": [AIMessage(content="I'll read a.txt", tool_calls=[read_tool_call])]},
        {"messages": [AIMessage(content="I'll write to b.txt", tool_calls=[write_tool_call])]},
        {"messages": [AIMessage(content="All done.")]}
    ]

    # 2. Build the graph after patching
    from agent.agent_graph import build_agent_graph
    graph = build_agent_graph().compile()

    # 3. Define Inputs and run agent
    initial_state = AgentState(messages=[HumanMessage(content="Read a.txt and write its content to b.txt")])
    config = {"configurable": {"thread_id": "test-multi-step"}}
    final_state = await graph.ainvoke(initial_state, config)

    # 4. Assertions
    assert mock_planner_reason_step.call_count == 3
    assert mock_tool_executor_step.call_count == 2

    # Check that the final message is correct
    assert final_state['messages'][-1].content == "All done."
