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
from tools.file_io_mcp_tools import read_file, write_file
from tools.shell_mcp_tools import run_shell
from tools.patch_tools import apply_patch
from tools.vector_store_tools import vector_search
from tools.lsp_tools import lsp_definition, lsp_hover
from tools.diagnostics_tools import get_diagnostics

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10  # Maximum number of planning iterations

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
]

# Mapping tool names to their callable functions for the executor
tool_map = {tool.name: tool for tool in all_tools_list}

def planner_llm_step(state: AgentState) -> AgentState:
    """
    The primary LLM-powered node that plans the next step or responds.
    """
    logger.info("Executing planner_llm_step...")

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

    logger.info(f"Invoking LLM for planning with {len(messages_for_llm)} messages...")
    response_ai_message = llm.invoke(messages_for_llm)
    logger.info(f"LLM Response: Content='{response_ai_message.content[:100]}...', ToolCalls={response_ai_message.tool_calls}")

    current_iteration_count = state.get('iteration_count', 0) + 1
    logger.info(f"Planner step completed. Iteration count: {current_iteration_count}")

    return {"messages": [response_ai_message], "iteration_count": current_iteration_count}

async def tool_executor_step(state: AgentState) -> dict:
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
    additional_state_updates: dict = {}

    for tool_call in parsed_tool_calls:
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
                lsp_tool_names = {lsp_definition.name, lsp_hover.name, get_diagnostics.name}
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
                if isinstance(tool_output, dict):
                    # For structured output like from run_shell, serialize to JSON
                    tool_output_content = json.dumps(tool_output, indent=2)
                else:
                    # For simple string outputs or already stringified errors from tools
                    tool_output_content = str(tool_output)
                logger.info(f"Tool '{tool_name}' executed successfully. Output (truncated): {tool_output_content[:200]}...")
            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}' with args {tool_args}: {e}", exc_info=True)
                tool_output_content = f"Error executing tool {tool_name}: {str(e)}"
            
            tool_messages.append(ToolMessage(content=tool_output_content, tool_call_id=tool_call_id))

            # Check if this was a successful 'create-next-app' command
            if tool_name == run_shell.name and isinstance(tool_output, dict) and tool_output.get("returncode") == 0:
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
            tool_messages.append(ToolMessage(content=f"Error: Tool '{tool_name}' not found.", tool_call_id=tool_call_id))

    return {"messages": tool_messages, **additional_state_updates}


def build_graph():
    """
    Builds the LangGraph for the autonomous agent.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_llm_step)
    workflow.add_node("tool_executor", tool_executor_step)

    def max_iterations_handler_node(state: AgentState) -> dict:
        logger.warning(f"Max iterations ({MAX_ITERATIONS}) reached. Ending graph.")
        max_iter_message = AIMessage(content=f"Maximum planning iterations ({MAX_ITERATIONS}) reached. Aborting execution.")
        return {"messages": [max_iter_message], "iteration_count": state.get('iteration_count', MAX_ITERATIONS)}

    workflow.add_node("max_iterations_handler", max_iterations_handler_node)

    workflow.set_entry_point("planner")

    def should_route_after_planner(state: AgentState) -> str:
        logger.info(f"Routing decision: Iteration count = {state.get('iteration_count')}")
        if state.get('iteration_count', 0) > MAX_ITERATIONS:
            logger.info("Max iterations reached. Routing to max_iterations_handler.")
            return "force_end_due_to_iterations"
        
        last_message = state['messages'][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            logger.info("Tool calls present. Routing to tool_executor.")
            return "tool_executor"
        
        logger.info("No tool calls from LLM and not max iterations. Ending graph.")
        return "continue_to_end" # End gracefully if no tools and not max iterations

    workflow.add_conditional_edges(
        "planner",
        should_route_after_planner,
        {
            "tool_executor": "tool_executor",
            "force_end_due_to_iterations": "max_iterations_handler",
            "continue_to_end": END
        }
    )
    
    workflow.add_edge("tool_executor", "planner")
    workflow.add_edge("max_iterations_handler", END) # Ensure this path also terminates

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
