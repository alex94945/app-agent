# agent/agent_graph.py

import logging
import asyncio # Required for gather if running multiple tools concurrently
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage, ToolCall

from agent.state import AgentState
from common.llm import get_llm_client

# Import all tools
from tools.file_io_mcp_tools import read_file, write_file
from tools.shell_mcp_tools import run_shell
from tools.patch_tools import apply_patch
from tools.vector_store_tools import vector_search
from tools.lsp_tools import lsp_definition, lsp_hover, get_diagnostics # Assuming get_diagnostics is in lsp_tools.py

logger = logging.getLogger(__name__)

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
    # It might need to be adjusted or made more general for broader agent capabilities.
    system_prompt_content = (
        "You are an expert AI developer. Your primary goal is to assist the user with software development tasks in their repository."
        "If the user asks to create a new application, and it's the first turn, your first and only action should be to call the `run_shell` tool "
        "to execute `npx create-next-app@latest my-app --typescript --tailwind --app --eslint --src-dir --import-alias \"@/*\"`. "
        "Do not ask for confirmation. Do not respond with conversational text. Call the tool directly."
        "In subsequent turns, analyze the user's request and the output of previous tools to plan your next action. "
        "This might involve reading files, writing files, running shell commands, applying patches, searching code, or using LSP features."
    )
    
    messages_for_llm.append(SystemMessage(content=system_prompt_content))
    messages_for_llm.extend(state['messages'])

    logger.info(f"Invoking LLM for planning with {len(messages_for_llm)} messages...")
    response_ai_message = llm.invoke(messages_for_llm)
    logger.info(f"LLM Response: Content='{response_ai_message.content[:100]}...', ToolCalls={response_ai_message.tool_calls}")
    
    return {"messages": [response_ai_message]}

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
                # All our tools are defined as async and expect dict args via @tool decorator
                tool_output = await selected_tool_func.ainvoke(tool_args)
                tool_output_str = str(tool_output)
                logger.info(f"Tool '{tool_name}' executed successfully. Output (truncated): {tool_output_str[:200]}...")
            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}' with args {tool_args}: {e}", exc_info=True)
                tool_output_str = f"Error executing tool {tool_name}: {str(e)}"
            
            tool_messages.append(ToolMessage(content=tool_output_str, tool_call_id=tool_call_id))
        else:
            logger.error(f"Tool '{tool_name}' not found in tool_map.")
            tool_messages.append(ToolMessage(content=f"Error: Tool '{tool_name}' not found.", tool_call_id=tool_call_id))

    return {"messages": tool_messages}


def build_graph():
    """
    Builds the LangGraph for the autonomous agent.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_llm_step)
    workflow.add_node("tool_executor", tool_executor_step) # LangGraph handles async nodes

    workflow.set_entry_point("planner")

    def should_route_to_tool_executor(state: AgentState) -> str:
        last_message = state['messages'][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            logger.info("Routing to tool_executor.")
            return "tool_executor" # Route to tool_executor if there are tool calls
        logger.info("No tool calls from LLM. Ending graph.")
        return END # Otherwise, end the graph

    workflow.add_conditional_edges(
        "planner",
        should_route_to_tool_executor,
        {
            "tool_executor": "tool_executor",
            END: END
        }
    )
    
    # After tools are executed, route back to the planner to process results
    workflow.add_edge("tool_executor", "planner")

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
        {"messages": [initial_message], "input": user_input}, # Ensure 'input' is also part of the initial state if needed by AgentState
        config=config,
        version="v1" # Using v1 for events
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
            final_state = event['data']['output']
            logger.info(f"__root__ on_chain_end: final_state type: {type(final_state)}, value: {final_state}") # DEBUG LOG
            planner_state = final_state.get('planner', {})
            final_messages_from_planner = planner_state.get('messages', [])
            if final_messages_from_planner:
                final_message_to_return = final_messages_from_planner[-1]
                logger.info(f"Agent run completed for thread_id: {thread_id}. Final message from planner: {final_message_to_return}")
            else:
                logger.warning(f"Agent run completed for thread_id: {thread_id}, but no final messages found in planner state within final_state: {final_state}")
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
