# agent/agent_graph.py

import logging
import asyncio
import json
import re
from typing import Optional
from uuid import uuid4
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.pydantic_v1 import BaseModel, Field

from agent.prompts.initial_scaffold import INITIAL_SCAFFOLD_PROMPT
from agent.state import AgentState
from common.llm import get_llm_client
from agent.executor.runner import run_single_tool, ToolExecutionError
from agent.executor.output_handlers import format_tool_output

# Import all tools
from tools.file_io_mcp_tools import read_file, write_file
from tools.shell_mcp_tools import run_shell
from tools.patch_tools import apply_patch
from tools.vector_store_tools import vector_search
from tools.lsp_tools import lsp_definition, lsp_hover
from tools.diagnostics_tools import get_diagnostics, diagnose

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

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
tool_map = {tool.name: tool for tool in all_tools_list}

# --- Planner Nodes (Two-Step: Reason -> Act) ---

class ToolPicker(BaseModel):
    """A tool to perform the requested action, or finish if the task is complete."""
    tool_name: Optional[str] = Field(
        default=None, 
        description="The name of the tool to use, or leave blank if the task is complete."
    )
    summary: str = Field(
        description="A brief summary of your reasoning for choosing this tool, or a summary of why the task is complete."
    )
    project_subdirectory: Optional[str] = Field(
        default=None,
        description="If creating a new project, the URL-friendly slug for the project subdirectory (e.g., 'my-cool-app')."
    )

def planner_reason_step(state: AgentState) -> dict:
    """First planner step: LLM call without tool schemas to decide which tool to use."""
    messages = state['messages']
    llm = get_llm_client().with_structured_output(ToolPicker)
    
    system_prompt = f"""You are an expert software development agent.

Your task is to choose the best tool for the job to solve the user's request. The user's request is in the first message.

If this is the first step in creating a new project, you MUST decide on a descriptive, URL-friendly slug for the project (e.g., "my-cool-app") and set the `project_subdirectory` field.

Review the conversation history and the output of previous tools. 

If the user's request is not yet complete, choose the next tool to use. The available tools are: {[tool.name for tool in all_tools_list]}.

If the user's request has been fully satisfied, DO NOT select a tool. Instead, provide a summary of the work completed.

Please respond with your decision."""

    prompt_messages = [SystemMessage(content=system_prompt)] + messages

    logger.info(f"Invoking reason step with messages: {prompt_messages}")
    response = llm.invoke(prompt_messages)
    logger.info(f"Reason step response: {response}")

    update_dict = {}

    # If the LLM decides the task is done, it will return a None tool_name.
    if not response.tool_name:
        logger.info("Planner decided task is complete.")
        update_dict["next_tool_to_call"] = None
        update_dict["messages"] = [AIMessage(content=f"Final summary: {response.summary}")]
    else:
        update_dict["next_tool_to_call"] = response.tool_name
        update_dict["messages"] = [AIMessage(content=f"Reasoning: {response.summary}")]
    
    # If the LLM sets the project subdirectory, add it to the state update.
    # Only do this if the state doesn't already have one.
    if response.project_subdirectory and not state.get("project_subdirectory"):
        logger.info(f"Planner set project_subdirectory to: {response.project_subdirectory}")
        update_dict["project_subdirectory"] = response.project_subdirectory

    return update_dict

def planner_arg_step(state: AgentState) -> dict:
    """This step generates the arguments for the tool chosen in the reason step."""
    tool_name = state.get("next_tool_to_call")
    if not tool_name:
        # The planner has decided the task is complete.
        # We pass through the AIMessage from the previous step.
        logger.info("Arg step is skipping: task is complete.")
        return {}

    # Get the specific tool schema
    try:
        tool = tool_map[tool_name]
    except KeyError:
        # This could happen if the LLM hallucinates a tool name.
        # We'll add the error as a tool message and let the agent recover.
        error_message = f"Tool '{tool_name}' not found. Please choose from the available tools."
        # This message doesn't have a tool_call_id, which might be an issue.
        # For now, we'll add it and see how LangGraph handles it.
        # TODO: Create a robust error handling mechanism for bad tool names.
        return {"messages": [ToolMessage(content=error_message, tool_call_id="invalid_tool_name")]}

    # Get the LLM with the specific tool schema
    llm_with_tool = get_llm_client().with_structured_output(tool.args_schema)

    system_prompt = f"""You are an expert software development agent.

Your task is to generate the arguments for the tool: '{tool_name}'.

Review the conversation history and the user's request to determine the correct arguments.

Only respond with the arguments, nothing else."""

    prompt_messages = [SystemMessage(content=system_prompt)] + state['messages']

    logger.info(f"Invoking arg step for tool {tool_name} with messages: {prompt_messages}")
    response_args = llm_with_tool.invoke(prompt_messages)
    logger.info(f"Arg step response: {response_args}")

    # The response_args is a Pydantic model. We need to convert it to a dict.
    args_dict = response_args.dict()

    # LangChain expects tool calls to be in a specific format.
    tool_call = {
        "name": tool_name,
        "args": args_dict,
        "id": str(uuid4()),
    }

    return {"messages": [AIMessage(content="", tool_calls=[tool_call])]}

# --- Executor Node ---

async def tool_executor_step(state: AgentState) -> dict:
    """Executes the tool call generated by the planner."""
    last_message = state['messages'][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {}

    tool_call = last_message.tool_calls[0]
    
    try:
        output = await run_single_tool(tool_call['name'], tool_call['args'], state)
        output_content = format_tool_output(output)
        tool_message = ToolMessage(content=output_content, tool_call_id=tool_call['id'])
    except ToolExecutionError as e:
        logger.error(f"Tool execution failed: {e}")
        tool_message = ToolMessage(content=f"Error: {e}", tool_call_id=tool_call['id'])

    return {"messages": [tool_message]}

# --- Control Flow and Graph Definition ---

def after_reasoner_router(state: AgentState) -> str:
    """Routes after the reasoning step. If a tool is chosen, generate args. Otherwise, end."""
    if state.get("next_tool_to_call"):
        return "planner_arg_generator"
    logger.info("Reasoner did not choose a tool. Ending.")
    return END

def after_executor_router(state: AgentState) -> str:
    """After executing a tool, decide whether to continue or end."""
    if state.get('iteration_count', 0) >= MAX_ITERATIONS:
        logger.warning("Max iterations reached. Ending.")
        return END
    return "planner_reasoner"

def build_graph():
    """Builds the LangGraph for the autonomous agent."""
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("planner_reasoner", planner_reason_step)
    workflow.add_node("planner_arg_generator", planner_arg_step)
    workflow.add_node("tool_executor", tool_executor_step)

    # Define edges
    workflow.set_entry_point("planner_reasoner")
    workflow.add_conditional_edges(
        "planner_reasoner",
        after_reasoner_router,
        {
            "planner_arg_generator": "planner_arg_generator",
            END: END
        }
    )
    workflow.add_edge("planner_arg_generator", "tool_executor")
    workflow.add_conditional_edges(
        "tool_executor",
        after_executor_router,
        {
            "planner_reasoner": "planner_reasoner",
            END: END
        }
    )

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)

# --- Main Entry Points ---

agent_graph = build_graph()

async def run_agent(question: str, project_subdirectory: str):
    """Run the agent with a given question and project subdirectory."""
    config = {"configurable": {"thread_id": "test-thread"}}
    initial_state = AgentState(
        messages=[HumanMessage(content=INITIAL_SCAFFOLD_PROMPT.format(question=question))],
        iteration_count=0,
        project_subdirectory=project_subdirectory,
        next_tool_to_call=None,
    )

    async for event in agent_graph.astream(initial_state, config=config):
        for key, value in event.items():
            logger.info(f"Event: {key} | Value: {value}")
        logger.info("----")

    final_state = await agent_graph.aget_state(config)
    return final_state['messages'][-1].content