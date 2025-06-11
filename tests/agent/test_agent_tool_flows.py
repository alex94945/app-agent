# tests/agent/test_agent_tool_flows.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage, ToolCall

from agent.agent_graph import agent_graph, all_tools_list, run_agent
from agent.state import AgentState

# Ensure all tools are loaded for potential mocking/inspection if needed by name
tool_names = [tool.name for tool in all_tools_list]

@pytest.mark.asyncio
async def test_initial_create_app_flow_uses_run_shell(mocker):
    """
    Tests that the agent, when prompted to create a new app on the first turn,
    correctly calls the run_shell tool with the npx create-next-app command.
    """
    thread_id = "test_create_app_flow_thread"
    user_input = "Create a new Next.js application."

    # 1. Mock the LLM client chain for planner_llm_step
    # This mock will be returned by get_llm_client()
    mock_initial_llm = MagicMock()

    # This mock will be returned by mock_initial_llm.bind_tools()
    mock_bound_llm = MagicMock()
    mock_initial_llm.bind_tools.return_value = mock_bound_llm

    # This is the expected tool call the LLM should make
    expected_tool_call = ToolCall(
        name="run_shell",
        args={
            "command": 'npx create-next-app@latest my-app --typescript --tailwind --app --eslint --src-dir --import-alias "@/*"'
        },
        id="test_tool_call_id_123"
    )
    # The AIMessage the mock LLM will return, prompting the tool call
    llm_planned_tool_call_response = AIMessage(
        content="Okay, I will create the Next.js application.", 
        tool_calls=[expected_tool_call]
    )
    
    # Mock the LLM again for the second planner call (after tool execution)
    # This time, it should just produce a final message without further tool calls.
    final_llm_response_content = "The Next.js application 'my-app' has been set up based on the tool's output."
    final_llm_response = AIMessage(content=final_llm_response_content)

    # Configure the invoke method on the bound LLM mock with side effects
    # This is the actual method called in planner_llm_step
    mock_bound_llm.invoke.side_effect = [
        llm_planned_tool_call_response,  # First call by planner
        final_llm_response               # Second call by planner (after run_shell result)
    ]

    # Patch get_llm_client to return our initial LLM mock
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_initial_llm)

    # 2. Mock the actual run_shell tool to prevent real execution and provide mock output
    mock_run_shell_tool_output = {
        "stdout": "Successfully created Next.js app my-app",
        "stderr": "",
        "return_code": 0
    }
    # Find the actual run_shell tool object from the list the agent uses
    run_shell_tool_instance = next(t for t in all_tools_list if t.name == "run_shell")
    # Mock the 'coroutine' attribute of the tool instance
    mock_run_shell_coroutine = AsyncMock(return_value=mock_run_shell_tool_output)
    mocker.patch.object(run_shell_tool_instance, 'coroutine', new=mock_run_shell_coroutine)
    


    # 3. Run the agent
    # The run_agent function in agent_graph.py streams events and returns the final message.
    # We need to capture the full message history or specific events to verify.
    
    # To inspect the full state, we might need to use graph.ainvoke directly
    # or modify run_agent for testing to return the full final state.
    # For now, let's assume run_agent returns the last message, and we'll check mocks.

    final_agent_message = await run_agent(user_input, thread_id)

    # 4. Assertions
    # Assert that the LLM was called (at least twice: once for planning, once after tool result)
    assert mock_bound_llm.invoke.call_count == 2
    
    # First call to LLM (planner)
    planner_llm_call_args = mock_bound_llm.invoke.call_args_list[0]
    planner_messages_arg = planner_llm_call_args[0][0] # First positional arg of the first call
    
    assert isinstance(planner_messages_arg[0], SystemMessage) # System prompt
    assert "npx create-next-app@latest my-app" in planner_messages_arg[0].content
    assert isinstance(planner_messages_arg[1], HumanMessage)
    assert planner_messages_arg[1].content == user_input

    # Assert that the tool's coroutine was called correctly with keyword arguments
    mock_run_shell_coroutine.assert_called_once_with(**expected_tool_call['args'])
    
    # Assert the content of the final message returned by the agent
    assert isinstance(final_agent_message, AIMessage)
    assert final_agent_message.content == final_llm_response_content
    assert not final_agent_message.tool_calls # Ensure no further tool calls in final response

    # To verify the ToolMessage was correctly added to the state and processed by the second LLM call:
    # We need to check the arguments to the second call to mock_bound_llm.invoke.
    second_planner_llm_call_args = mock_bound_llm.invoke.call_args_list[1]
    second_planner_messages_arg = second_planner_llm_call_args[0][0]
    
    # Expected messages for the second planner call:
    # SystemMessage (from first call, if logic keeps it or re-adds it)
    # HumanMessage (user_input)
    # AIMessage (llm_planned_tool_call_response with the tool_call)
    # ToolMessage (with result from mock_run_shell_tool)
    
    # Check that the ToolMessage is present and correct
    assert len(second_planner_messages_arg) >= 4 # At least System, Human, AI (tool call), ToolMessage
    # The actual number might vary based on how system prompts are handled on subsequent turns.
    # Let's find the ToolMessage
    found_tool_message = None
    for msg in reversed(second_planner_messages_arg):
        if isinstance(msg, ToolMessage):
            found_tool_message = msg
            break
    
    assert found_tool_message is not None, "ToolMessage not found in messages for second planner call"
    assert found_tool_message.tool_call_id == expected_tool_call['id']
    assert str(mock_run_shell_tool_output) in found_tool_message.content

    # Clean up (specific to LangGraph's in-memory checkpointer for this thread_id if needed,
    # but pytest isolation + unique thread_ids should handle it)
    # For MemorySaver, state is kept per thread_id. New test runs with same ID would resume.
    # Using unique thread_ids per test is a good practice.

# Add more tests here for read_file, vector_search, etc.


@pytest.mark.asyncio
async def test_vector_search_flow(mocker):
    """
    Tests that the agent, when a vector search is appropriate,
    correctly calls the vector_search tool and processes its output.
    """
    thread_id = "test_vector_search_flow_thread"
    user_input = "What is the project's main objective?"
    llm_generated_search_query = "project main objective overview"
    mock_search_results_list = [
        {"page_content": "The project aims to build an autonomous AI agent capable of coding tasks.", "metadata": {"source": "design_doc.md", "page": 1}},
        {"page_content": "Key features include tool usage and self-healing.", "metadata": {"source": "readme.md", "page": 1}}
    ]

    # 1. Mock the LLM client chain
    mock_initial_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_initial_llm.bind_tools.return_value = mock_bound_llm

    expected_vector_search_tool_call = ToolCall(
        name="vector_search",
        args={"query": llm_generated_search_query, "k": 3}, # Assuming default k or k is part of LLM decision
        id="test_vector_search_tool_call_789"
    )
    llm_planned_vector_search_response = AIMessage(
        content="I will search the project documents for information on the main objective.",
        tool_calls=[expected_vector_search_tool_call]
    )

    final_llm_response_content_vector_search = f"Based on the project documents, the main objective is: {mock_search_results_list[0]['page_content']} Additional context: {mock_search_results_list[1]['page_content']}"
    final_llm_response_vector_search = AIMessage(content=final_llm_response_content_vector_search)

    mock_bound_llm.invoke.side_effect = [
        llm_planned_vector_search_response,  # First call by planner
        final_llm_response_vector_search     # Second call by planner (after vector_search result)
    ]

    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_initial_llm)

    # 2. Mock the vector_search tool
    vector_search_tool_instance = next(t for t in all_tools_list if t.name == "vector_search")
    mock_vector_search_coroutine = AsyncMock(return_value=mock_search_results_list)
    mocker.patch.object(vector_search_tool_instance, 'coroutine', new=mock_vector_search_coroutine)

    # 3. Run the agent
    final_agent_message = await run_agent(user_input, thread_id)

    # 4. Assertions
    assert mock_bound_llm.invoke.call_count == 2

    # First call to LLM (planner)
    planner_llm_call_args_1 = mock_bound_llm.invoke.call_args_list[0]
    planner_messages_arg_1 = planner_llm_call_args_1[0][0]
    assert isinstance(planner_messages_arg_1[0], SystemMessage)
    assert isinstance(planner_messages_arg_1[1], HumanMessage)
    assert planner_messages_arg_1[1].content == user_input

    # Assert that the tool's coroutine was called correctly
    mock_vector_search_coroutine.assert_called_once_with(query=llm_generated_search_query, k=3)

    # Assert the content of the final message returned by the agent
    assert isinstance(final_agent_message, AIMessage)
    assert final_agent_message.content == final_llm_response_content_vector_search
    assert not final_agent_message.tool_calls

    # Verify the ToolMessage was correctly added to the state and processed by the second LLM call
    second_planner_llm_call_args = mock_bound_llm.invoke.call_args_list[1]
    second_planner_messages_arg = second_planner_llm_call_args[0][0]
    
    found_tool_message = None
    for msg in reversed(second_planner_messages_arg):
        if isinstance(msg, ToolMessage):
            found_tool_message = msg
            break
    
    assert found_tool_message is not None, "ToolMessage not found in messages for second planner call"
    assert found_tool_message.tool_call_id == expected_vector_search_tool_call['id']
    # The content of ToolMessage for vector_search is a list of dicts, so convert to string for comparison if needed, or check structure.
    # For simplicity, we'll check if a key part of the content is there.
    assert str(mock_search_results_list) in found_tool_message.content



@pytest.mark.asyncio
async def test_read_file_flow(mocker):
    """
    Tests that the agent, when prompted to read a file,
    correctly calls the read_file tool and processes its output.
    """
    thread_id = "test_read_file_flow_thread"
    user_input = "Please read the file dummy/file.txt"
    file_path_to_read = "dummy/file.txt"
    mock_file_content_str = "This is the content of dummy/file.txt from the mock."

    # 1. Mock the LLM client chain
    mock_initial_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_initial_llm.bind_tools.return_value = mock_bound_llm

    expected_read_file_tool_call = ToolCall(
        name="read_file",
        args={"path_in_repo": file_path_to_read},
        id="test_read_file_tool_call_456"
    )
    llm_planned_read_file_response = AIMessage(
        content="Okay, I will read that file.",
        tool_calls=[expected_read_file_tool_call]
    )

    final_llm_response_content_read_file = f"I have read {file_path_to_read}. It says: {mock_file_content_str}"
    final_llm_response_read_file = AIMessage(content=final_llm_response_content_read_file)

    mock_bound_llm.invoke.side_effect = [
        llm_planned_read_file_response,  # First call by planner
        final_llm_response_read_file     # Second call by planner (after read_file result)
    ]

    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_initial_llm)

    # 2. Mock the read_file tool
    # The read_file tool returns a string directly.
    read_file_tool_instance = next(t for t in all_tools_list if t.name == "read_file")
    mock_read_file_coroutine = AsyncMock(return_value=mock_file_content_str)
    mocker.patch.object(read_file_tool_instance, 'coroutine', new=mock_read_file_coroutine)

    # 3. Run the agent
    final_agent_message = await run_agent(user_input, thread_id)

    # 4. Assertions
    assert mock_bound_llm.invoke.call_count == 2

    # First call to LLM (planner)
    planner_llm_call_args_1 = mock_bound_llm.invoke.call_args_list[0]
    planner_messages_arg_1 = planner_llm_call_args_1[0][0]
    assert isinstance(planner_messages_arg_1[0], SystemMessage)
    assert isinstance(planner_messages_arg_1[1], HumanMessage)
    assert planner_messages_arg_1[1].content == user_input

    # Assert that the tool's coroutine was called correctly
    mock_read_file_coroutine.assert_called_once_with(path_in_repo=file_path_to_read)

    # Assert the content of the final message returned by the agent
    assert isinstance(final_agent_message, AIMessage)
    assert final_agent_message.content == final_llm_response_content_read_file
    assert not final_agent_message.tool_calls

    # Verify the ToolMessage in the second planner call
    planner_llm_call_args_2 = mock_bound_llm.invoke.call_args_list[1]
    planner_messages_arg_2 = planner_llm_call_args_2[0][0]
    
    assert len(planner_messages_arg_2) >= 4 # System, Human, AI (tool call), ToolMessage
    found_tool_message = None
    for msg in reversed(planner_messages_arg_2):
        if isinstance(msg, ToolMessage):
            found_tool_message = msg
            break
    
    assert found_tool_message is not None, "ToolMessage not found for read_file call"
    assert found_tool_message.tool_call_id == expected_read_file_tool_call['id']
    # The content of the ToolMessage for read_file is the string content itself
    assert found_tool_message.content == mock_file_content_str
