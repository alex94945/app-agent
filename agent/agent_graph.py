# agent/agent_graph.py

import logging
import asyncio # Required for gather if running multiple tools concurrently
import json
import re
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage, ToolCall

from agent.prompts.initial_scaffold import INITIAL_SCAFFOLD_PROMPT
from agent.state import AgentState
from common.llm import get_llm_client

# Import all tools
from tools.file_io_mcp_tools import read_file, write_file, WriteFileOutput
from tools.shell_mcp_tools import run_shell, RunShellOutput
from tools.patch_tools import apply_patch, ApplyPatchOutput
from tools.vector_store_tools import vector_search
from tools.lsp_tools import lsp_definition, lsp_hover
from tools.diagnostics_tools import get_diagnostics, diagnose

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10  # Maximum number of planning iterations
MAX_FIX_ATTEMPTS = 3   # Maximum number of fix attempts for a single tool call ID

# List of all tools for the planner LLM to know about
all_tools_list = [
    read_file,
    write_file,
    run_shell,
    apply_patch,
    vector_search,
    lsp_definition,
    lsp_hover,
    get_diagnostics,
    diagnose,
]

# Mapping tool names to their callable functions for the executor
tool_map = {tool.name: tool for tool in all_tools_list}

def planner_llm_step(state: AgentState) -> AgentState:
    """
    The primary LLM-powered node that plans the next step or responds.
    """
    logger.info("Executing planner_llm_step... Current iteration=%s, fix_attempts=%s, failing_tool_run=%s", state.get('iteration_count'), state.get('fix_attempts'), state.get('failing_tool_run'))

    # Initialize the LLM client for this step, binding all available tools.
    llm = get_llm_client(purpose="planner").bind_tools(all_tools_list)

    messages_for_llm: list[BaseMessage] = []

    # Add a system prompt to guide the LLM's behavior for initial scaffolding
    # This prompt is specific to the initial task of creating a Next.js app.
    system_prompt_content = INITIAL_SCAFFOLD_PROMPT

    # Prepend the system prompt to the messages for the LLM
    messages_for_llm = []
    current_project_subdirectory = state.get("project_subdirectory")
    if current_project_subdirectory:
        system_prompt_content = system_prompt_content.replace("{{project_subdirectory}}", current_project_subdirectory)
    
    messages_for_llm.append(SystemMessage(content=system_prompt_content))
    messages_for_llm.extend(state["messages"])  # Add the rest of the messages

    logger.debug("System prompt (truncated to 300 chars): %s", system_prompt_content[:300])
    logger.info("Invoking LLM for planning with %s messages...", len(messages_for_llm))
    response_ai_message = llm.invoke(messages_for_llm)
    # Normalize tool_calls to plain dicts so downstream code/tests can use dict access
    if response_ai_message.tool_calls:
        normalized_tool_calls = []
        for tc in response_ai_message.tool_calls:
            if hasattr(tc, "dict"):
                normalized_tool_calls.append(tc.dict())
            else:
                normalized_tool_calls.append(tc)
        response_ai_message.tool_calls = normalized_tool_calls
    logger.info(f"LLM Response: Content='{response_ai_message.content[:100]}...', ToolCalls={response_ai_message.tool_calls}")

    current_iteration_count = state.get('iteration_count', 0) + 1
    logger.debug("LLM tool_calls raw: %s", response_ai_message.tool_calls)
    logger.info("Planner step completed. Iteration count: %s", current_iteration_count)

    return {"messages": state["messages"] + [response_ai_message], "iteration_count": current_iteration_count}

async def tool_executor_step(state: AgentState) -> dict:
    logger.info("Entering tool_executor_step. Current fix_attempts=%s, failing_tool_run=%s, needs_verification=%s", state.get('fix_attempts'), state.get('failing_tool_run'), state.get('needs_verification'))
    logger.info("Entering tool_executor_step. Current fix_attempts=%s, failing_tool_run=%s, needs_verification=%s", state.get('fix_attempts'), state.get('failing_tool_run'), state.get('needs_verification'))
    logger.info("Entering tool_executor_step. Current fix_attempts=%s, failing_tool_run=%s", state.get('fix_attempts'), state.get('failing_tool_run'))
    """
    Executes tools based on the LLM's tool_calls.
    """
    logger.info("Executing tool_executor_step...")
    messages = state['messages']
    last_message = messages[-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        logger.warning("No tool calls found in the last AIMessage. Returning empty tool messages.")
        # This path should ideally not be hit if conditional routing is correct.
        return {"messages": []}

    raw_tool_calls_from_message = last_message.tool_calls
    parsed_tool_calls: list[ToolCall] = []
    if raw_tool_calls_from_message:
        for item in raw_tool_calls_from_message:
            if isinstance(item, dict):
                try:
                    # Use Pydantic parsing for robustness
                    tool_call_obj = ToolCall.parse_obj(item)
                except Exception:
                    # Fallback manual handling
                    args_data = item.get('args') or item.get('arguments')
                    if args_data is None:
                        logger.error(f"Dictionary item in tool_calls missing 'args'/'arguments': {item}")
                        continue
                    tool_call_obj = ToolCall(name=item['name'], args=args_data, id=item['id'])
                parsed_tool_calls.append(tool_call_obj)
            elif isinstance(item, ToolCall):
                parsed_tool_calls.append(item)
            else:
                logger.warning(f"Unexpected type in tool_calls list: {type(item)}, item: {item}")

    # Keep only well‑formed tool‑call objects (TypedDict or Pydantic model).
    def _is_valid_tool_call(obj) -> bool:
        # Pydantic model path (“dot” attributes exist)
        if hasattr(obj, "name") and hasattr(obj, "id") and hasattr(obj, "args"):
            return True
        # Plain dict / TypedDict path
        if isinstance(obj, dict) and "name" in obj and "id" in obj and (
            "args" in obj or "arguments" in obj
        ):
            return True
        return False

    parsed_tool_calls = [tc for tc in parsed_tool_calls if _is_valid_tool_call(tc)]
    if not parsed_tool_calls:
        logger.warning("No valid ToolCall objects to execute after parsing.")
        return {"messages": []}

    tool_messages: list[ToolMessage] = []
    logger.debug("Parsed %s tool calls to execute.", len(parsed_tool_calls))
    additional_state_updates: dict = {}
    additional_state_updates['needs_verification'] = False # Default to false, set true only if patch succeeds for a failing run
    additional_state_updates['needs_verification'] = False # Default to false, set true only if patch succeeds for a failing run

    # Initialize fix attempt state from the incoming state for this execution step.
    # These will be updated based on the outcomes of the tool calls in this batch.
    updated_fix_attempts = state.get('fix_attempts', 0)
    updated_failing_tool_run = state.get('failing_tool_run')

    for tool_call in parsed_tool_calls:
        logger.debug("Executing tool_call id=%s name=%s", getattr(tool_call, 'id', None) if not isinstance(tool_call, dict) else tool_call.get('id'), getattr(tool_call, 'name', None) if not isinstance(tool_call, dict) else tool_call.get('name'))
        tool_output = None
        if isinstance(tool_call, dict):
            tool_name = tool_call["name"]
            tool_args = tool_call.get("args") or tool_call.get("arguments") or {}
            tool_call_id = tool_call["id"]
        else:  # Pydantic model
            tool_name = tool_call.name
            tool_args = tool_call.args
            tool_call_id = tool_call.id

        logger.info(f"Attempting to execute tool: '{tool_name}' with args: {tool_args} (Call ID: {tool_call_id})")

        if tool_name in tool_map:
            selected_tool_func = tool_map[tool_name]
            try:
                # Inject project_subdirectory for LSP tools if available in state
                lsp_tool_names = {lsp_definition.name, lsp_hover.name, get_diagnostics.name, diagnose.name}
                if tool_name in lsp_tool_names:
                    current_project_subdirectory = state.get("project_subdirectory")
                    if current_project_subdirectory:
                        # Ensure tool_args is a mutable dictionary
                        if not isinstance(tool_args, dict):
                            # This case should ideally not happen if LLM follows schema,
                            # but as a safeguard if tool_args is some other Pydantic model type.
                            # Convert to dict if it's a Pydantic model or similar structure.
                            # For simplicity, assuming it's already a dict or compatible.
                            # If it's a Pydantic model, tool_args.dict() might be needed,
                            # but LangChain usually passes dicts for 'args'.
                            logger.warning(f"Tool args for {tool_name} is not a dict: {type(tool_args)}. Attempting to proceed.")
                        
                        # Make a mutable copy if tool_args might be an immutable Pydantic model's .args view
                        tool_args_mutable = dict(tool_args) if tool_args else {}
                        tool_args_mutable["project_subdirectory"] = current_project_subdirectory
                        logger.info(f"Injected project_subdirectory='{current_project_subdirectory}' into args for LSP tool '{tool_name}'. New args: {tool_args_mutable}")
                        tool_args_to_invoke = tool_args_mutable
                    else:
                        tool_args_to_invoke = tool_args # Pass original if no subdirectory
                else:
                    tool_args_to_invoke = tool_args # Pass original for non-LSP tools

                # All our tools are defined as async and expect dict args via @tool decorator
                tool_output = await selected_tool_func.ainvoke(tool_args_to_invoke)

                if isinstance(tool_output, RunShellOutput):
                    if not tool_output.ok:
                        tool_output_content = f'<error type="shell" command="{tool_output.command_executed}">Error details: {tool_output.stderr}</error>'
                        logger.error(f"Tool '{tool_name}' failed. Output: {tool_output_content}")
                    else:
                        tool_output_content = tool_output.model_dump_json(indent=2)
                        logger.info(f"Tool '{tool_name}' executed successfully. Output (truncated): {tool_output_content[:200]}...")
                elif isinstance(tool_output, WriteFileOutput):
                    if not tool_output.ok:
                        tool_output_content = f'<error type="file_write" path="{tool_output.path}">Error details: {tool_output.message}</error>'
                        logger.error(f"Tool '{tool_name}' failed. Output: {tool_output_content}")
                    else:
                        tool_output_content = tool_output.model_dump_json(indent=2)
                        logger.info(f"Tool '{tool_name}' executed successfully. Output (truncated): {tool_output_content[:200]}...")
                elif isinstance(tool_output, ApplyPatchOutput):
                    if not tool_output.ok:
                        stderr_details = tool_output.details.stderr if tool_output.details else ''
                        tool_output_content = f'<error type="patch" file_path_hint="{tool_output.file_path_hint}">Error details: {tool_output.message} Stderr: {stderr_details}</error>'
                        logger.error(f"Tool '{tool_name}' failed. Output: {tool_output_content}")
                    else:
                        tool_output_content = tool_output.model_dump_json(indent=2)
                        logger.info(f"Tool '{tool_name}' executed successfully. Output (truncated): {tool_output_content[:200]}...")
                elif isinstance(tool_output, dict):
                    # For other structured dict outputs, serialize to JSON
                    tool_output_content = json.dumps(tool_output, indent=2)
                    logger.info(f"Tool '{tool_name}' executed successfully. Output (truncated): {tool_output_content[:200]}...")
                else:
                    # For simple string outputs or already stringified errors from other tools
                    tool_output_content = str(tool_output)
                    logger.info(f"Tool '{tool_name}' executed successfully. Output (truncated): {tool_output_content[:200]}...")
            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}' with args {tool_args}: {e}", exc_info=True)
                tool_output_content = f"Error executing tool {tool_name}: {str(e)}"
            
            tool_messages.append(ToolMessage(content=tool_output_content, tool_call_id=tool_call_id))

            # Determine tool success for fix attempt logic
            tool_succeeded = True # Assume success unless explicitly failed by structured output or exception
            if isinstance(tool_output, (RunShellOutput, WriteFileOutput, ApplyPatchOutput)):
                if not tool_output.ok:
                    tool_succeeded = False
            elif 'Error executing tool' in tool_output_content: # Check for exception-based error messages
                 tool_succeeded = False

            current_tool_run_details = {"name": tool_name, "args": tool_args, "id": tool_call_id} # Store ID for verification re-run
            is_part_of_fix_cycle = updated_failing_tool_run is not None

            if tool_succeeded:
                if tool_name == apply_patch.name and is_part_of_fix_cycle and updated_failing_tool_run['name'] == current_tool_run_details['name'] and updated_failing_tool_run['args'] == current_tool_run_details['args']:
                    # Successful patch for the specific failing tool run.
                    # Don't clear failing_tool_run or reset attempts yet. Mark for verification.
                    logger.info(f"Successful '{apply_patch.name}' for failing tool: {updated_failing_tool_run}. Marking for verification.")
                    additional_state_updates['needs_verification'] = True
                    # failing_tool_run and fix_attempts remain until verification confirms the fix.
                elif is_part_of_fix_cycle and current_tool_run_details['name'] != updated_failing_tool_run['name']:
                    # A *different* tool succeeded during a fix cycle. This implies the LLM abandoned the original failing tool.
                    # Consider the fix cycle for the *original* failing_tool_run resolved by this alternative success.
                    logger.info(f"A different tool '{tool_name}' succeeded during fix cycle for '{updated_failing_tool_run}'. Resetting fix cycle.")
                    updated_failing_tool_run = None
                    updated_fix_attempts = 0
                elif not is_part_of_fix_cycle:
                    # Standard successful tool run, not part of any fix cycle. No change to fix state.
                    pass
            else: # Tool failed
                # If this failure is for the *same* tool that was already failing, increment attempts.
                if is_part_of_fix_cycle and updated_failing_tool_run['name'] == current_tool_run_details['name'] and updated_failing_tool_run['args'] == current_tool_run_details['args']:
                    updated_fix_attempts += 1
                    logger.info(f"Failing tool {updated_failing_tool_run} failed again. Fix attempts incremented to {updated_fix_attempts}.")
                else:
                    # A new tool has failed, or a different tool failed during an existing fix cycle.
                    # Start/reset the fix cycle for *this specific* failing tool.
                    logger.info(f"Tool {current_tool_run_details} failed. Starting/resetting fix cycle. Setting attempts to 1.")
                    updated_failing_tool_run = current_tool_run_details # Store name, args, and ID
                    updated_fix_attempts = 1
                    additional_state_updates['needs_verification'] = False # Explicitly false if a new failure occurs

            # Check if this was a successful 'create-next-app' command
            if tool_name == run_shell.name and isinstance(tool_output, RunShellOutput) and tool_output.ok:
                command_str = tool_args.get("command", "")
                if "create-next-app" in command_str:
                    # Try to extract the app name. Example: npx create-next-app@latest my-app --ts
                    match = re.search(r"create-next-app(?:@latest)?\s+([^\s]+)", command_str)
                    if match:
                        app_name = match.group(1)
                        # Remove potential options like --ts from the app_name if they are captured
                        app_name = app_name.split(' ')[0]
                        if app_name and not app_name.startswith("--"):
                            logger.info(f"Detected successful 'create-next-app' for '{app_name}'. Updating project_subdirectory.")
                            additional_state_updates["project_subdirectory"] = app_name
                        else:
                            logger.warning(f"Could not reliably extract app name from '{command_str}' or extracted name is an option: '{app_name}'")
                    else:
                        logger.warning(f"'create-next-app' detected in command, but could not extract app name from: {command_str}")
        else:
            logger.error(f"Tool '{tool_name}' not found in tool_map.")
            # This case means the tool itself wasn't found, treat as a failure for fix counts
            logger.error(f"Tool '{tool_name}' not found in tool_map. Treating as failure for fix count.")
            if tool_call_id == updated_current_tool_call_id_for_fix:
                updated_fix_attempts_count += 1
            else:
                updated_fix_attempts_count = 1
                updated_current_tool_call_id_for_fix = tool_call_id
            tool_messages.append(ToolMessage(content=f"Error: Tool '{tool_name}' not found.", tool_call_id=tool_call_id))

    additional_state_updates['fix_attempts'] = updated_fix_attempts
    additional_state_updates['failing_tool_run'] = updated_failing_tool_run
    logger.info(f"Exiting tool_executor_step. Updated fix_attempts: {updated_fix_attempts}, updated_failing_tool_run: {updated_failing_tool_run}, needs_verification: {additional_state_updates.get('needs_verification')}")
    return {"messages": tool_messages, **additional_state_updates}


def build_graph():
    """
    Builds the LangGraph for the autonomous agent.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_llm_step)
    workflow.add_node("tool_executor", tool_executor_step)

    async def verify_node(state: AgentState) -> dict:
        """
        Verifies a fix by re-running the original failing tool call.
        This node is entered only if `needs_verification` is True.
        """
        logger.info("Entering verify_node. Current fix_attempts=%s, failing_tool_run=%s", state.get('fix_attempts'), state.get('failing_tool_run'))
        
        failing_tool_run_details = state.get('failing_tool_run')
        if not failing_tool_run_details:
            logger.error("Verify_node was entered but failing_tool_run is not set. This should not happen. Skipping verification.")
            return {"messages": [ToolMessage(content="<error type='internal'>Verify node error: no failing_tool_run details.</error>", tool_call_id="verify_node_internal_error")], "needs_verification": False}

        tool_name_to_verify = failing_tool_run_details['name']
        tool_args_to_verify = failing_tool_run_details['args']
        original_tool_call_id = failing_tool_run_details.get('id', f"verify_{tool_name_to_verify}")

        logger.info(f"Attempting to verify by re-running tool: '{tool_name_to_verify}' with args: {tool_args_to_verify}")

        tool_output = None
        tool_succeeded = False
        output_content = ""
        additional_state_updates = {}

        if tool_name_to_verify in tool_map:
            selected_tool_func = tool_map[tool_name_to_verify]
            try:
                lsp_tool_names = {lsp_definition.name, lsp_hover.name, get_diagnostics.name, diagnose.name}
                tool_args_to_invoke = dict(tool_args_to_verify) 
                if tool_name_to_verify in lsp_tool_names:
                    current_project_subdirectory = state.get("project_subdirectory")
                    if current_project_subdirectory:
                        tool_args_to_invoke["project_subdirectory"] = current_project_subdirectory
                
                tool_output = await selected_tool_func.ainvoke(tool_args_to_invoke)

                if isinstance(tool_output, (RunShellOutput, WriteFileOutput, ApplyPatchOutput)):
                    tool_succeeded = tool_output.ok
                    output_content = tool_output.model_dump_json(indent=2) if tool_succeeded else f'<error type="{tool_name_to_verify}">{tool_output.message if hasattr(tool_output, "message") else "Verification failed."}</error>'
                elif isinstance(tool_output, dict):
                    tool_succeeded = True 
                    output_content = json.dumps(tool_output, indent=2)
                else:
                    tool_succeeded = True 
                    output_content = str(tool_output)
                
                if not tool_succeeded and not output_content.startswith("<error"):
                     output_content = f"<error type='verification_failure'>Tool {tool_name_to_verify} failed during verification. Output: {str(tool_output)}</error>"

            except Exception as e:
                logger.error(f"Error during verification execution of tool '{tool_name_to_verify}': {e}", exc_info=True)
                output_content = f"<error type='verification_exception'>Exception during verification of {tool_name_to_verify}: {str(e)}</error>"
                tool_succeeded = False
        else:
            logger.error(f"Tool '{tool_name_to_verify}' (for verification) not found in tool_map.")
            output_content = f"<error type='internal'>Tool {tool_name_to_verify} not found for verification.</error>"
            tool_succeeded = False

        if tool_succeeded:
            logger.info(f"Verification successful for {failing_tool_run_details}. Clearing fix cycle.")
            additional_state_updates['failing_tool_run'] = None
            additional_state_updates['fix_attempts'] = 0
        else:
            current_fix_attempts = state.get('fix_attempts', 0)
            additional_state_updates['fix_attempts'] = current_fix_attempts + 1
            logger.warning(f"Verification failed for {failing_tool_run_details}. Fix attempts now {additional_state_updates['fix_attempts']}.")

        additional_state_updates['needs_verification'] = False 
        
        tool_message = ToolMessage(content=output_content, tool_call_id=original_tool_call_id + "_verify")
        logger.info(f"Exiting verify_node. Updated state: {additional_state_updates}")
        return {"messages": [tool_message], **additional_state_updates}

    workflow.add_node("verify_step", verify_node)

    def max_iterations_handler_node(state: AgentState) -> dict:
        logger.warning(f"Max iterations ({MAX_ITERATIONS}) reached. Ending graph.")
        max_iter_message = AIMessage(content=f"Maximum planning iterations ({MAX_ITERATIONS}) reached. Aborting execution.")
        return {"messages": [max_iter_message], "iteration_count": state.get('iteration_count', MAX_ITERATIONS)}

    workflow.add_node("max_iterations_handler", max_iterations_handler_node)

    def max_fix_attempts_handler_node(state: AgentState) -> dict:
        failing_tool_run = state.get('failing_tool_run', 'unknown tool')
        attempts = state.get('fix_attempts', MAX_FIX_ATTEMPTS)
        logger.warning(f"Max fix attempts ({attempts}) reached for tool run '{failing_tool_run}'. Ending graph.")
        max_fix_message = AIMessage(
            content=f"Maximum fix attempts ({attempts}) reached for a failing tool: {failing_tool_run}. Aborting further attempts on this issue."
        )
        return {
            "messages": [max_fix_message],
            "fix_attempts": 0, 
            "failing_tool_run": None
        }
    workflow.add_node("max_fix_attempts_handler", max_fix_attempts_handler_node)

    workflow.set_entry_point("planner")

    def should_route_after_planner(state: AgentState) -> str:
        logger.info(f"Routing decision: Iteration count = {state.get('iteration_count')}, Fix attempts = {state.get('fix_attempts', 0)}")
        if state.get('iteration_count', 0) > MAX_ITERATIONS:
            logger.info("Max iterations reached. Routing to max_iterations_handler.")
            return "force_end_due_to_iterations"
        
        current_fix_attempts = state.get('fix_attempts', 0)
        if current_fix_attempts >= MAX_FIX_ATTEMPTS:
            logger.info(f"Max fix attempts ({current_fix_attempts}) reached for tool {state.get('failing_tool_run')}. Routing to max_fix_attempts_handler.")
            return "force_end_due_to_fix_attempts"
        
        last_message = state['messages'][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            logger.info("Tool calls present. Routing to tool_executor.")
            return "tool_executor"
        
        logger.info("No tool calls from LLM and not max iterations. Ending graph.")
        return "continue_to_end"

    workflow.add_conditional_edges(
        "planner",
        should_route_after_planner,
        {
            "tool_executor": "tool_executor",
            "force_end_due_to_iterations": "max_iterations_handler",
            "force_end_due_to_fix_attempts": "max_fix_attempts_handler",
            "continue_to_end": END
        }
    )
    
    workflow.add_edge("max_iterations_handler", END)
    workflow.add_edge("max_fix_attempts_handler", END)

    def should_route_after_tool_executor(state: AgentState) -> str:
        if state.get('needs_verification', False):
            logger.info("Routing after tool_executor: Needs verification. Routing to verify_step.")
            return "verify_step"
        logger.info("Routing after tool_executor: No verification needed. Routing to planner.")
        return "planner"

    workflow.add_conditional_edges(
        "tool_executor",
        should_route_after_tool_executor,
        {
            "verify_step": "verify_step",
            "planner": "planner"
        }
    )

    def should_route_after_verify_node(state: AgentState) -> str:
        if state.get('failing_tool_run') is None: 
            logger.info("Routing after verify_step: Verification successful. Routing to planner.")
            return "planner"
        
        if state.get('fix_attempts', 0) >= MAX_FIX_ATTEMPTS:
            logger.info(f"Routing after verify_step: Verification failed, max fix attempts ({state.get('fix_attempts')}) reached. Routing to max_fix_attempts_handler.")
            return "max_fix_attempts_handler"
        
        logger.info(f"Routing after verify_step: Verification failed, {state.get('fix_attempts')} attempts. Routing to planner for another fix.")
        return "planner" 

    workflow.add_conditional_edges(
        "verify_step",
        should_route_after_verify_node,
        {
            "planner": "planner",
            "max_fix_attempts_handler": "max_fix_attempts_handler"
        }
    )

    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    logger.info("LangGraph compiled successfully with tool routing.")
    return app

agent_graph = build_graph()

async def run_agent(user_input: str, thread_id: str):
    """
    Runs the agent with a given user input and returns the final response or streams events.
    This example focuses on getting the final message but can be adapted for full streaming.
    """
    logger.info(f"Running agent for thread_id: {thread_id} with input: '{user_input}'")
    
    config = {"configurable": {"thread_id": thread_id}}
    initial_message = HumanMessage(content=user_input)
    
    final_message_to_return = None

    async for event in agent_graph.astream_events(
        {"messages": [initial_message], "input": user_input, "iteration_count": 0},
        config=config,
        version="v1"
    ):
        kind = event["event"]
        event_name = event.get("name", "N/A") # Some events might not have a 'name'
        logger.info(f"EVENT SEEN: kind='{kind}', name='{event_name}'") # DEBUG ALL EVENTS
        # logger.debug(f"Event: {kind}, Data: {event['data']}") # Verbose event logging

        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                # print(content, end="") # For live token streaming to console
                pass
        elif kind == "on_tool_start":
            logger.info(f"Tool started: {event['name']} with input {event['data'].get('input')}")
        elif kind == "on_tool_end":
            logger.info(f"Tool ended: {event['name']} with output (truncated): {str(event['data'].get('output'))[:200]}...")
        elif kind == "on_chain_end" and event["name"] == "LangGraph": # Graph finished execution for this input
            raw_final_output = event['data']['output']
            logger.info(f"__root__ on_chain_end: raw_final_output type: {type(raw_final_output)}, value: {raw_final_output}")

            final_messages_list = []
            output_states = []
            if isinstance(raw_final_output, list):
                output_states = raw_final_output
            elif isinstance(raw_final_output, dict):
                output_states = [raw_final_output]

            # Prioritize the handler's message if it exists, as it's a definitive terminal state.
            handler_state = next((s for s in output_states if 'max_iterations_handler' in s), None)
            if handler_state:
                final_messages_list = handler_state.get('max_iterations_handler', {}).get('messages', [])
            else:
                # Otherwise, find the planner's message from the last known state.
                # In a list, the last item is the most recent state.
                last_state = output_states[-1] if output_states else {}
                if 'planner' in last_state:
                    final_messages_list = last_state.get('planner', {}).get('messages', [])
                # Fallback for direct message state from a single-node output.
                elif 'messages' in last_state:
                    final_messages_list = last_state.get('messages', [])

            if final_messages_list:
                final_message_to_return = final_messages_list[-1]
                logger.info(f"Agent run completed for thread_id: {thread_id}. Final message: {final_message_to_return}")
            else:
                logger.warning(f"Agent run completed for thread_id: {thread_id}, but could not determine final messages from raw_final_output: {raw_final_output}")
            
            break # Exit loop once graph is done for this input
        elif kind == "on_chain_error":
            logger.error(f"Error in agent execution for thread_id: {thread_id}. Event: {event}")
            # Potentially set an error message to return
            final_message_to_return = AIMessage(content=f"An error occurred: {event['data'].get('error')}")
            break

    if final_message_to_return is None:
        logger.error(f"Agent stream ended without a final message for thread_id: {thread_id}")
        return AIMessage(content="Agent finished processing, but no final message was generated.")
        
    return final_message_to_return
