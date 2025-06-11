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
    # Iteration count is now part of the state and might affect message count if not handled carefully in test mocks
    # For this test, we are primarily interested in the ToolMessage content from the first tool call.
    found_tool_message = None
    for msg in reversed(second_planner_messages_arg):
        if isinstance(msg, ToolMessage):
            found_tool_message = msg
            break
    
    assert found_tool_message is not None, "ToolMessage not found in messages for second planner call"
    assert found_tool_message.tool_call_id == expected_tool_call['id']
    # The content should be the JSON string representation of the tool output due to recent changes
    import json
    assert found_tool_message.content == json.dumps(mock_run_shell_tool_output, indent=2)

    # Clean up (specific to LangGraph's in-memory checkpointer for this thread_id if needed,
    # but pytest isolation + unique thread_ids should handle it)
    # For MemorySaver, state is kept per thread_id. New test runs with same ID would resume.
    # Using unique thread_ids per test is a good practice.


@pytest.mark.asyncio
async def test_run_shell_failure_and_report(mocker):
    """
    Tests that if run_shell returns an error (e.g., non-zero exit code),
    the error is correctly formatted as a JSON string in the ToolMessage,
    and the LLM (mocked) processes this to report the failure.
    """
    thread_id = "test_run_shell_failure_thread"
    user_input = "List contents of a non-existent directory /foo/bar"
    command_to_fail = "ls /foo/bar"

    # 1. Mock LLM client
    mock_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_llm)

    # --- LLM Planning Sequence ---
    # Step 1: LLM plans to call run_shell with the failing command
    failing_tool_call_id = "failing_shell_call_1"
    failing_tool_call = ToolCall(name="run_shell", args={"command": command_to_fail}, id=failing_tool_call_id)
    llm_plan_failing_shell_call = AIMessage(
        content=f"Okay, I will try to list {command_to_fail}.", 
        tool_calls=[failing_tool_call]
    )

    # Step 2: LLM receives the error ToolMessage and decides to report it
    expected_error_report_content = f"The command '{command_to_fail}' failed. Error: ls: /foo/bar: No such file or directory"
    llm_report_error_response = AIMessage(content=expected_error_report_content)

    mock_bound_llm.invoke.side_effect = [
        llm_plan_failing_shell_call,  # Planner call 1 (plans the failing command)
        llm_report_error_response     # Planner call 2 (after tool error, reports it)
    ]

    # 2. Mock run_shell tool to return an error
    mock_run_shell_error_output = {
        "stdout": "",
        "stderr": "ls: /foo/bar: No such file or directory",
        "return_code": 1
    }
    run_shell_tool_instance = next(t for t in all_tools_list if t.name == "run_shell")
    mock_run_shell_coroutine = AsyncMock(return_value=mock_run_shell_error_output)
    mocker.patch.object(run_shell_tool_instance, 'coroutine', new=mock_run_shell_coroutine)

    # 3. Run the agent
    final_agent_message = await run_agent(user_input, thread_id)

    # 4. Assertions
    assert mock_bound_llm.invoke.call_count == 2 # Planner called twice

    # Assert run_shell tool was called with the correct failing command
    mock_run_shell_coroutine.assert_called_once_with(command=command_to_fail)

    # Assert the ToolMessage content passed to the second planner call
    planner_call_2_args = mock_bound_llm.invoke.call_args_list[1][0][0]
    tool_msg_from_error = next(m for m in reversed(planner_call_2_args) if isinstance(m, ToolMessage))
    
    assert tool_msg_from_error is not None
    assert tool_msg_from_error.tool_call_id == failing_tool_call_id
    import json
    assert tool_msg_from_error.content == json.dumps(mock_run_shell_error_output, indent=2)

    # Assert the final agent message reports the error
    assert isinstance(final_agent_message, AIMessage)
    assert final_agent_message.content == expected_error_report_content
    assert not final_agent_message.tool_calls


@pytest.mark.asyncio
async def test_read_file_non_existent_and_report(mocker):
    """
    Tests that if read_file is called on a non-existent file,
    the error string is correctly passed in the ToolMessage,
    and the LLM (mocked) processes this to report the failure.
    """
    thread_id = "test_read_file_non_existent_thread"
    non_existent_file_path = "path/to/a/ghost.txt"
    user_input = f"Please read the file {non_existent_file_path}"

    # 1. Mock LLM client
    mock_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_llm)

    # --- LLM Planning Sequence ---
    # Step 1: LLM plans to call read_file
    read_file_tool_call_id = "read_ghost_file_call_1"
    read_file_tool_call = ToolCall(
        name="read_file", 
        args={"path_in_repo": non_existent_file_path}, 
        id=read_file_tool_call_id
    )
    llm_plan_read_file_call = AIMessage(
        content=f"Okay, I will attempt to read {non_existent_file_path}.",
        tool_calls=[read_file_tool_call]
    )

    # Step 2: LLM receives the error ToolMessage and decides to report it
    mock_read_file_error_output = f"Error: File not found at {non_existent_file_path}" # Match tool's actual error format
    expected_error_report_content = f"I could not read the file '{non_existent_file_path}'. The tool reported: {mock_read_file_error_output}"
    llm_report_error_response = AIMessage(content=expected_error_report_content)

    mock_bound_llm.invoke.side_effect = [
        llm_plan_read_file_call,    # Planner call 1 (plans the read_file call)
        llm_report_error_response   # Planner call 2 (after tool error, reports it)
    ]

    # 2. Mock read_file tool to return an error string
    read_file_tool_instance = next(t for t in all_tools_list if t.name == "read_file")
    mock_read_file_coroutine = AsyncMock(return_value=mock_read_file_error_output)
    mocker.patch.object(read_file_tool_instance, 'coroutine', new=mock_read_file_coroutine)

    # 3. Run the agent
    final_agent_message = await run_agent(user_input, thread_id)

    # 4. Assertions
    assert mock_bound_llm.invoke.call_count == 2 # Planner called twice

    # Assert read_file tool was called with the correct path
    mock_read_file_coroutine.assert_called_once_with(path_in_repo=non_existent_file_path)

    # Assert the ToolMessage content passed to the second planner call
    planner_call_2_args = mock_bound_llm.invoke.call_args_list[1][0][0]
    tool_msg_from_error = next(m for m in reversed(planner_call_2_args) if isinstance(m, ToolMessage))
    
    assert tool_msg_from_error is not None
    assert tool_msg_from_error.tool_call_id == read_file_tool_call_id
    # read_file tool returns a string error directly, not a dict, so no JSON dump
    assert tool_msg_from_error.content == mock_read_file_error_output

    # Assert the final agent message reports the error
    assert isinstance(final_agent_message, AIMessage)
    assert final_agent_message.content == expected_error_report_content
    assert not final_agent_message.tool_calls


@pytest.mark.asyncio
async def test_max_iterations_reached(mocker):
    """
    Tests that the agent graph stops after MAX_ITERATIONS
    and returns the appropriate message when the LLM continuously plans tool calls.
    """
    thread_id = "test_max_iterations_thread"
    user_input = "Please do something that will cause a loop."
    MAX_ITERATIONS_FROM_GRAPH = 10 # From agent_graph.py

    # 1. Mock LLM client to always plan a tool call
    mock_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_llm)

    # LLM always plans the same run_shell tool call
    looping_tool_call_id_prefix = "loop_call_"
    looping_tool_call = ToolCall(
        name="run_shell", 
        args={"command": "echo 'looping...'"}, 
        id=f"{looping_tool_call_id_prefix}0" # ID will be updated by mock
    )
    # The invoke mock needs to generate unique tool call IDs for each call if the graph uses them
    # For simplicity here, we'll make the mock update the ID if needed, or ensure the graph handles non-unique IDs if that's the case.
    # Based on current graph, tool_call.id is used in ToolMessage, so it should ideally be unique if we were to inspect each ToolMessage.
    # However, for this test, we only care about the loop and final message.
    def llm_invoke_side_effect(messages):
        # Find the current iteration from messages if needed, or just return the same tool call
        # For this test, always returning the same tool call structure is sufficient to induce a loop.
        # The graph's iteration_count handles termination.
        current_call_count = mock_bound_llm.invoke.call_count # call_count is 1-based for current call
        looping_tool_call['id'] = f"{looping_tool_call_id_prefix}{current_call_count -1}"
        return AIMessage(
            content="Okay, I will run the echo command again.",
            tool_calls=[looping_tool_call]
        )
    mock_bound_llm.invoke.side_effect = llm_invoke_side_effect

    # 2. Mock run_shell tool to return a simple output
    mock_run_shell_output = {"stdout": "looping...", "stderr": "", "return_code": 0}
    run_shell_tool_instance = next(t for t in all_tools_list if t.name == "run_shell")
    mock_run_shell_coroutine = AsyncMock(return_value=mock_run_shell_output)
    mocker.patch.object(run_shell_tool_instance, 'coroutine', new=mock_run_shell_coroutine)

    # 3. Run the agent
    final_agent_message = await run_agent(user_input, thread_id)

    # 4. Assertions
    # Planner is called MAX_ITERATIONS times before routing to max_iterations_handler
    # Planner is called MAX_ITERATIONS + 1 times before routing to max_iterations_handler
    assert mock_bound_llm.invoke.call_count == MAX_ITERATIONS_FROM_GRAPH + 1
    
    # Tool executor is called MAX_ITERATIONS times
    assert mock_run_shell_coroutine.call_count == MAX_ITERATIONS_FROM_GRAPH

    # Assert the final agent message indicates max iterations reached
    assert isinstance(final_agent_message, AIMessage)
    expected_final_content = f"Maximum planning iterations ({MAX_ITERATIONS_FROM_GRAPH}) reached. Aborting execution."
    assert final_agent_message.content == expected_final_content
    assert not final_agent_message.tool_calls


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
async def test_multi_step_create_dir_write_read_flow(mocker):
    """
    Tests a multi-step agent flow: 
    1. Create a directory (run_shell)
    2. Write a file into that directory (write_file)
    3. Read the file (read_file)
    4. Report the content.
    """
    thread_id = "test_multi_step_flow_thread"
    user_input = "Create a dir 'my_project', then write 'Hello from multi-step!' to 'my_project/notes.txt', then read 'my_project/notes.txt' and tell me what it says."
    
    dir_to_create = "my_project"
    file_to_write = "my_project/notes.txt"
    file_content_to_write = "Hello from multi-step!"

    # 1. Mock LLM and Tools
    mock_initial_llm = MagicMock()
    mock_bound_llm = MagicMock()
    mock_initial_llm.bind_tools.return_value = mock_bound_llm
    mocker.patch("agent.agent_graph.get_llm_client", return_value=mock_initial_llm)

    # --- LLM Planning Sequence ---
    # Step 1: Plan to create directory
    mkdir_tool_call_id = "mkdir_call_1"
    mkdir_tool_call = ToolCall(name="run_shell", args={"command": f"mkdir {dir_to_create}"}, id=mkdir_tool_call_id)
    llm_plan_mkdir_response = AIMessage(content=f"Okay, I'll create the directory {dir_to_create}.", tool_calls=[mkdir_tool_call])

    # Step 2: Plan to write file (after mkdir success)
    write_file_tool_call_id = "write_file_call_1"
    write_file_tool_call = ToolCall(name="write_file", args={"path_in_repo": file_to_write, "content": file_content_to_write}, id=write_file_tool_call_id)
    llm_plan_write_file_response = AIMessage(content=f"Directory created. Now, I'll write to {file_to_write}.", tool_calls=[write_file_tool_call])

    # Step 3: Plan to read file (after write_file success)
    read_file_tool_call_id = "read_file_call_1"
    read_file_tool_call = ToolCall(name="read_file", args={"path_in_repo": file_to_write}, id=read_file_tool_call_id)
    llm_plan_read_file_response = AIMessage(content=f"File written. Now, I'll read {file_to_write}.", tool_calls=[read_file_tool_call])

    # Step 4: Final response (after read_file success)
    final_llm_response_content = f"I have read the file '{file_to_write}'. It says: '{file_content_to_write}'"
    llm_final_response = AIMessage(content=final_llm_response_content)

    mock_bound_llm.invoke.side_effect = [
        llm_plan_mkdir_response,          # Planner call 1
        llm_plan_write_file_response,     # Planner call 2
        llm_plan_read_file_response,      # Planner call 3
        llm_final_response                # Planner call 4
    ]

    # --- Mock Tool Coroutines ---
    mock_run_shell_output = {"stdout": f"Directory {dir_to_create} created.", "stderr": "", "return_code": 0}
    run_shell_tool_instance = next(t for t in all_tools_list if t.name == "run_shell")
    mock_run_shell_coroutine = AsyncMock(return_value=mock_run_shell_output)
    mocker.patch.object(run_shell_tool_instance, 'coroutine', new=mock_run_shell_coroutine)

    mock_write_file_output = f"Successfully wrote to {file_to_write}"
    write_file_tool_instance = next(t for t in all_tools_list if t.name == "write_file")
    mock_write_file_coroutine = AsyncMock(return_value=mock_write_file_output)
    mocker.patch.object(write_file_tool_instance, 'coroutine', new=mock_write_file_coroutine)

    # read_file tool returns the content directly
    read_file_tool_instance = next(t for t in all_tools_list if t.name == "read_file")
    mock_read_file_coroutine = AsyncMock(return_value=file_content_to_write)
    mocker.patch.object(read_file_tool_instance, 'coroutine', new=mock_read_file_coroutine)

    # 2. Run the agent
    final_agent_message = await run_agent(user_input, thread_id)

    # 3. Assertions
    assert mock_bound_llm.invoke.call_count == 4 # Four planner calls

    # Verify initial planner call
    planner_call_1_args = mock_bound_llm.invoke.call_args_list[0][0][0]
    assert isinstance(planner_call_1_args[0], SystemMessage)
    assert isinstance(planner_call_1_args[1], HumanMessage) and planner_call_1_args[1].content == user_input

    # Verify tool calls
    mock_run_shell_coroutine.assert_called_once_with(command=f"mkdir {dir_to_create}")
    mock_write_file_coroutine.assert_called_once_with(path_in_repo=file_to_write, content=file_content_to_write)
    mock_read_file_coroutine.assert_called_once_with(path_in_repo=file_to_write)

    # Verify ToolMessages were passed to subsequent planner calls
    # Planner call 2 (after mkdir)
    planner_call_2_args = mock_bound_llm.invoke.call_args_list[1][0][0]
    tool_msg_1 = next(m for m in reversed(planner_call_2_args) if isinstance(m, ToolMessage))
    assert tool_msg_1.tool_call_id == mkdir_tool_call_id
    import json
    assert tool_msg_1.content == json.dumps(mock_run_shell_output, indent=2)

    # Planner call 3 (after write_file)
    planner_call_3_args = mock_bound_llm.invoke.call_args_list[2][0][0]
    tool_msg_2 = next(m for m in reversed(planner_call_3_args) if isinstance(m, ToolMessage))
    assert tool_msg_2.tool_call_id == write_file_tool_call_id
    assert mock_write_file_output in tool_msg_2.content

    # Planner call 4 (after read_file)
    planner_call_4_args = mock_bound_llm.invoke.call_args_list[3][0][0]
    tool_msg_3 = next(m for m in reversed(planner_call_4_args) if isinstance(m, ToolMessage))
    assert tool_msg_3.tool_call_id == read_file_tool_call_id
    assert file_content_to_write in tool_msg_3.content

    # Verify final agent message
    assert isinstance(final_agent_message, AIMessage)
    assert final_agent_message.content == final_llm_response_content
    assert not final_agent_message.tool_calls



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
