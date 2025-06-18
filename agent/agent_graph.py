# agent/agent_graph.py

import logging
import asyncio # Required for gather if running multiple tools concurrently
import json
import re
import inspect
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage, ToolCall

from agent.prompts.initial_scaffold import INITIAL_SCAFFOLD_PROMPT
from agent.state import AgentState
from agent.executor.parser import parse_tool_calls
from common.llm import get_llm_client
from agent.executor.runner import run_single_tool, ToolExecutionError
from agent.executor.fix_cycle import FixCycleTracker
from agent.executor.output_handlers import is_tool_successful, format_tool_output

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

# tool_map is no longer needed here, run_single_tool resolves tools internally.
# all_tools_list is still used by the planner_llm_step.

def planner_llm_step(state: AgentState) -> AgentState:
    """
    The primary LLM-powered node that plans the next step or responds.
    """
    fix_tracker_summary = "N/A"
    if state.get('fix_cycle_tracker_state'):
        tracker = FixCycleTracker.from_state(state['fix_cycle_tracker_state'])
        fix_tracker_summary = tracker.get_current_fix_state()
    logger.info("Executing planner_llm_step... Iteration: %s, FixCycleTracker: %s", state.get('iteration_count', 0), fix_tracker_summary)

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
    logger.info(f"LLM Response: Content='{response_ai_message.content[:100]}...', ToolCalls={response_ai_message.tool_calls}")

    current_iteration_count = state.get('iteration_count', 0) + 1
    logger.debug("LLM tool_calls raw: %s", response_ai_message.tool_calls)
    logger.info("Planner step completed. Iteration count: %s", current_iteration_count)

    return {"messages": state["messages"] + [response_ai_message], "iteration_count": current_iteration_count}

async def tool_executor_step(state: AgentState) -> dict:
    logger.info("Entering tool_executor_step with FixCycleTracker integration.")
    """
    Executes tools based on the LLM's tool_calls, using FixCycleTracker and new output handlers.
    """
    messages = state['messages']
    last_message = messages[-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        logger.warning("No tool calls found in the last AIMessage. Returning empty tool messages.")
        return {"messages": [], "fix_cycle_tracker_state": state.get('fix_cycle_tracker_state')} # Pass through tracker state

    parsed_tool_calls = parse_tool_calls(last_message)
    if not parsed_tool_calls:
        logger.warning("No valid ToolCall objects to execute after parsing. Returning empty tool messages.")
        return {"messages": [], "fix_cycle_tracker_state": state.get('fix_cycle_tracker_state')} # Pass through tracker state

    tool_messages: list[ToolMessage] = []
    logger.debug("Parsed %s tool calls to execute.", len(parsed_tool_calls))
    
    # Retrieve FixCycleTracker from state, or initialize if not present
    tracker_state = state.get("fix_cycle_tracker_state")  # Load using the consistent key
    if tracker_state:
        tracker = FixCycleTracker.from_state(tracker_state)
        logger.info(f"FixCycleTracker loaded from state. Current state: {tracker.to_state()}")
    else:
        tracker = FixCycleTracker()
        logger.info(f"FixCycleTracker initialized fresh. Current state: {tracker.to_state()}")

    additional_state_updates: dict = {}

    logger.debug(f"Inspecting parsed_tool_calls before loop: {parsed_tool_calls}, type: {type(parsed_tool_calls)}")
    for tool_call in parsed_tool_calls:
        logger.debug(f"Inspecting individual tool_call in loop: {tool_call}, type: {type(tool_call)}")
        
        # ToolCall is a TypedDict, so tool_call is already a dictionary.
        # Access its elements using dictionary key access.
        try:
            tool_name = tool_call['name']
            tool_args = tool_call['args']
            tool_call_id = tool_call['id'] # Assumes 'id' is present for valid tool calls from AIMessage
        except KeyError as e:
            logger.error(f"Tool call dictionary {tool_call} missing expected key: {e}. Skipping.")
            continue
        except TypeError: # Handles case where tool_call might not be subscriptable (e.g. None)
            logger.error(f"Tool call {tool_call} is not a dictionary as expected. Skipping.")
            continue

        logger.info(f"Attempting to execute tool: '{tool_name}' with args: {tool_args} (Call ID: {tool_call_id})")

        # Core tool execution using run_single_tool
        raw_tool_output = await run_single_tool(tool_name, tool_args, state)

        # Determine success and format output using output_handlers
        # ToolExecutionError is one of the possible raw_tool_output types from run_single_tool
        succeeded = is_tool_successful(raw_tool_output)
        formatted_output_content = format_tool_output(raw_tool_output)
        
        tool_messages.append(ToolMessage(content=formatted_output_content, tool_call_id=tool_call_id))
        logger.debug(f"Tool '{tool_name}' (ID: {tool_call_id}) executed. Succeeded: {succeeded}. Formatted Output: {formatted_output_content[:200]}...")

        # Update FixCycleTracker
        # Get the state *before* record_tool_run for the conditional logging
        # This state reflects whether a fix cycle was active *before* this tool_run was recorded.
        pre_record_fix_state = tracker.get_current_fix_state()

        if pre_record_fix_state.get("is_active") and pre_record_fix_state.get("failing_tool_name") and tool_name != pre_record_fix_state.get("failing_tool_name"):
            logger.debug(f"DEBUG_FCT: Recording a fix attempt. Current tool: '{tool_name}', Failing tool: '{pre_record_fix_state.get('failing_tool_name')}'.")
            logger.debug(f"DEBUG_FCT: Tracker state BEFORE record_tool_run for fix tool '{tool_name}' (ID: {tool_call_id}): {tracker.to_state()}")

        tracker.record_tool_run(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            succeeded=succeeded,
            output_content=formatted_output_content
        )

        # Use the same pre_record_fix_state for the condition, as it reflects the state *before* this tool's effects were recorded.
        if pre_record_fix_state.get("is_active") and pre_record_fix_state.get("failing_tool_name") and tool_name != pre_record_fix_state.get("failing_tool_name"):
            logger.debug(f"DEBUG_FCT: Tracker state AFTER record_tool_run for fix tool '{tool_name}' (ID: {tool_call_id}): {tracker.to_state()}")

        # Special handling for 'create-next-app' success to update project_subdirectory
        if tool_name == run_shell.name and succeeded and isinstance(raw_tool_output, RunShellOutput):
            command_str = tool_args.get("command", "")
            if "create-next-app" in command_str:
                match = re.search(r"create-next-app(?:@latest)?\s+([^\s]+)", command_str)
                if match:
                    app_name = match.group(1).split(' ')[0]
                    if app_name and not app_name.startswith("--"):
                        logger.info(f"Detected successful 'create-next-app' for '{app_name}'. Updating project_subdirectory.")
                        additional_state_updates["project_subdirectory"] = app_name
                    else:
                        logger.warning(f"Could not reliably extract app name from '{command_str}' or extracted name is an option: '{app_name}'")
                else:
                    logger.warning(f"'create-next-app' detected, but could not extract app name from: {command_str}")

    # After processing all tool calls, the tracker instance holds the latest state.
    # This state will be returned via additional_state_updates.
    current_tracker_state_dict = tracker.to_state()
    logger.debug(f"Tracker's current state after all tool executions in this step: {current_tracker_state_dict}")

    # Determine if verification is needed based on the tracker's state AFTER all tools ran
    is_verification_needed = tracker.needs_verification()  # Call the method
    if is_verification_needed:
        failing_run_details = tracker._state.get("failing_tool_run")
        tool_name_for_log = failing_run_details['name'] if failing_run_details else 'N/A'
        tool_id_for_log = failing_run_details['id'] if failing_run_details else 'N/A'
        logger.info(f"Tool execution complete. Verification needed for tool '{tool_name_for_log}' (ID: {tool_id_for_log}). FixCycleTracker state: {tracker.to_state()}")
    else:
        logger.info(f"Tool execution complete. No verification currently needed. FixCycleTracker state: {tracker.to_state()}")

    additional_state_updates['needs_verification'] = is_verification_needed  # Use the correct variable
    additional_state_updates['fix_cycle_tracker_state'] = current_tracker_state_dict
    
    # Remove deprecated fields from direct state update if they exist
    # These are now managed by FixCycleTracker
    additional_state_updates.pop('failing_tool_run', None)
    additional_state_updates.pop('fix_attempts', None)

    logger.info(f"Exiting tool_executor_step. FixCycleTracker state: {additional_state_updates['fix_cycle_tracker_state']}, Needs Verification: {additional_state_updates.get('needs_verification')}")
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
        Verifies a fix by re-running the original failing tool call using FixCycleTracker.
        This node is entered only if `needs_verification` is True (set by FixCycleTracker).
        """
        logger.info("Entering verify_node.")
        
        fix_tracker = FixCycleTracker.from_state(state.get('fix_cycle_tracker_state') or {})
        tool_to_verify = fix_tracker.get_tool_to_verify()

        if not tool_to_verify:
            logger.error("Verify_node entered, but FixCycleTracker has no tool to verify. This might indicate a logic error or premature entry. Skipping verification.")
            # Ensure needs_verification is false if we can't proceed.
            fix_tracker.record_verification_result(succeeded=False) # Mark as failed to clear verification flag
            return {
                "messages": [ToolMessage(content="<error type='internal'>Verify node error: no tool details from FixCycleTracker.</error>", tool_call_id="verify_node_tracker_error")],
                "fix_cycle_tracker_state": fix_tracker.to_state()
            }

        tool_name_to_verify = tool_to_verify['name']
        tool_args_to_verify = tool_to_verify['args']
        original_tool_call_id = tool_to_verify.get('id', f"verify_{tool_name_to_verify}")

        logger.info(f"Attempting to verify by re-running tool: '{tool_name_to_verify}' with args: {tool_args_to_verify} (Original ID: {original_tool_call_id})")

        # Use run_single_tool for consistent execution and error handling
        raw_tool_output = await run_single_tool(tool_name_to_verify, tool_args_to_verify, state)
        
        succeeded = is_tool_successful(raw_tool_output, tool_name_to_verify)
        # Add a suffix to the original tool_call_id for the verification attempt's ToolMessage
        verification_tool_call_id = original_tool_call_id + "_verify"
        output_content = format_tool_output(raw_tool_output, tool_name_to_verify, verification_tool_call_id, succeeded)

        fix_tracker.record_verification_result(succeeded=succeeded)
        
        if succeeded:
            logger.info(f"Verification successful for tool '{tool_name_to_verify}'. Fix cycle resolved.")
        else:
            logger.warning(f"Verification failed for tool '{tool_name_to_verify}'. Fix cycle remains or may escalate to max attempts.")

        tool_message = ToolMessage(content=output_content, tool_call_id=verification_tool_call_id)
        updated_fix_cycle_state = fix_tracker.to_state()
        logger.info(f"Exiting verify_node. FixCycleTracker state: {updated_fix_cycle_state}")
        
        # The needs_verification flag is now internal to FixCycleTracker's state and its effect on routing.
        # We return the full tracker state.
        return {"messages": [tool_message], "fix_cycle_tracker_state": updated_fix_cycle_state}

    workflow.add_node("verify_step", verify_node)

    def max_iterations_handler_node(state: AgentState) -> dict:
        logger.warning(f"Max iterations ({MAX_ITERATIONS}) reached. Ending graph.")
        max_iter_message = AIMessage(content=f"Maximum planning iterations ({MAX_ITERATIONS}) reached. Aborting execution.")
        return {"messages": [max_iter_message], "iteration_count": state.get('iteration_count', MAX_ITERATIONS)}

    workflow.add_node("max_iterations_handler", max_iterations_handler_node)

    def max_fix_attempts_handler_node(state: AgentState) -> dict:
        fix_tracker = FixCycleTracker.from_state(state.get('fix_cycle_tracker_state') or {})
        current_fix_details = fix_tracker.get_current_fix_state()
        
        failing_tool_info_str = "unknown tool"
        if current_fix_details.get('is_active') and current_fix_details.get('failing_tool_run'):
            failing_run = current_fix_details['failing_tool_run']
            failing_tool_info_str = f"tool '{failing_run['name']}' (ID: {failing_run['id']}) with args {failing_run['args']}"
        
        attempts = current_fix_details.get('current_attempt_count', MAX_FIX_ATTEMPTS)
        logger.warning(f"Max fix attempts ({attempts}) reached for {failing_tool_info_str}. Ending graph.")
        
        max_fix_message = AIMessage(
            content=f"Maximum fix attempts ({attempts}) reached for {failing_tool_info_str}. Aborting further attempts on this issue."
        )
        
        # The tracker itself should manage its state when max attempts are hit (e.g., by no longer being 'active' or 'needs_verification').
        # We just pass its state through.
        # If the design requires explicitly resetting it here, that logic would go into FixCycleTracker.
        # For now, assume the planner routes away and the cycle effectively ends.
        return {
            "messages": [max_fix_message],
            "fix_cycle_tracker_state": fix_tracker.to_state() # Pass through the tracker state
        }
    workflow.add_node("max_fix_attempts_handler", max_fix_attempts_handler_node)

    workflow.set_entry_point("planner")

    def should_route_after_planner(state: AgentState) -> str:
        iteration_count = state.get('iteration_count', 0)
        fix_tracker = FixCycleTracker.from_state(state.get('fix_cycle_tracker_state') or {})
        logger.info(f"Routing decision: Iteration count = {iteration_count}, FixCycleTracker state = {fix_tracker.get_current_fix_state()}")

        if iteration_count > MAX_ITERATIONS:
            logger.info("Max iterations reached. Routing to max_iterations_handler.")
            return "force_end_due_to_iterations"
        
        if fix_tracker.has_reached_max_fix_attempts(MAX_FIX_ATTEMPTS):
            failing_tool_info = fix_tracker.get_current_fix_state().get('failing_tool_run', 'unknown tool')
            logger.info(f"Max fix attempts reached for tool {failing_tool_info} according to FixCycleTracker. Routing to max_fix_attempts_handler.")
            return "force_end_due_to_fix_attempts"
        
        last_message = state['messages'][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            logger.info("Tool calls present. Routing to tool_executor.")
            return "tool_executor"
        
        logger.info("No tool calls from LLM and not max iterations/fix_attempts. Ending graph.")
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
        fix_tracker = FixCycleTracker.from_state(state.get('fix_cycle_tracker_state') or {})
        if fix_tracker.needs_verification():
            logger.info("Routing after tool_executor: Needs verification (per FixCycleTracker). Routing to verify_step.")
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
        fix_tracker = FixCycleTracker.from_state(state.get('fix_cycle_tracker_state') or {})
        current_fix_state = fix_tracker.get_current_fix_state()

        if not current_fix_state['is_active'] and not current_fix_state['needs_verification']:
            # This implies verification was successful and the cycle is resolved.
            logger.info("Routing after verify_step: Verification successful (fix cycle inactive, no verification needed). Routing to planner.")
            return "planner"
        
        # If still needs verification (shouldn't happen if verify_node clears it) or is active and max attempts reached.
        if fix_tracker.has_reached_max_fix_attempts(MAX_FIX_ATTEMPTS):
            logger.info(f"Routing after verify_step: Verification failed or cycle ongoing, and max fix attempts reached. Routing to max_fix_attempts_handler.")
            return "max_fix_attempts_handler"
        
        # Verification failed, but more attempts are allowed, or cycle is still active for other reasons.
        logger.info(f"Routing after verify_step: Verification failed or cycle ongoing, but more attempts allowed. Routing to planner for another fix attempt.")
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
        logger.debug(f"EVENT SEEN: kind='{kind}', name='{event_name}'") # DEBUG ALL EVENTS
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
