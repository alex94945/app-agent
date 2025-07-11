# agent/agent_graph.py

import logging
import asyncio
import json
import re
from typing import Optional
from uuid import uuid4
from langgraph.graph import StateGraph, END
from langgraph.pregel import Pregel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.pydantic_v1 import BaseModel, Field, create_model
from typing import Type

# Helper to map schema types to Python types
_TYPE_MAP = {
    'string': str,
    'number': float,
    'integer': int,
    'boolean': bool,
    'object': dict,
    'array': list,
}

def get_type_from_schema(schema_dict: dict) -> Type:
    """Gets the Python type from a JSON-like schema dictionary."""
    return _TYPE_MAP.get(schema_dict.get('type', 'string'), str)

from agent.prompts.initial_scaffold import INITIAL_SCAFFOLD_PROMPT
from agent.prompts.arg_generator_system_prompt import get_arg_generator_system_prompt
from agent.prompts.planner_system_prompt import PLANNER_SYSTEM_PROMPT
from agent.state import AgentState
from common.llm import get_llm_client
from agent.executor.runner import run_single_tool
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

def planner_reason_step(state: AgentState) -> dict:
    """First planner step: LLM call without tool schemas to decide which tool to use."""
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
    messages = state['messages']
    llm = get_llm_client().with_structured_output(ToolPicker)
    
    tool_names = [tool.name for tool in all_tools_list]

    # On the first turn, use the special scaffolding prompt. Otherwise, use the general planner prompt.
    if state.get("iteration_count", 0) == 0:
        system_prompt = INITIAL_SCAFFOLD_PROMPT
    else:
        system_prompt = PLANNER_SYSTEM_PROMPT.format(tool_names=tool_names)

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
    


    # increment iteration count so MAX_ITERATIONS can trigger even when no tool executes
    update_dict["iteration_count"] = state.get("iteration_count", 0) + 1
    return update_dict

def planner_arg_step(state: AgentState) -> dict:
    """This step generates the arguments for the tool chosen in the reason step."""
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
    tool_name = state.get("next_tool_to_call")
    if not tool_name:
        # The planner has decided the task is complete.
        # We pass through the AIMessage from the previous step.
        logger.info("Arg step is skipping: task is complete.")
        return {}

    # Initialize the tool map inside the function to avoid serialization issues
    tool_map = {tool.name: tool for tool in all_tools_list}

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

    # Dynamically create a Pydantic model for the tool's arguments
    # The tool.args is a dict where the value is another dict (a JSON-like schema)
    fields = {
        k: (get_type_from_schema(v), v.get('default'))
        for k, v in tool.args.items()
    }
    ToolArguments = create_model(f'{tool_name}Args', **fields)

    # Get the LLM with the dynamically created tool schema
    llm_with_tool = get_llm_client().with_structured_output(ToolArguments)

    system_prompt = get_arg_generator_system_prompt(
        tool_name=tool_name,
        tool_description=tool.description,
        tool_args=tool.args
    )

    prompt_messages = [SystemMessage(content=system_prompt)] + state['messages']

    logger.info(f"Invoking arg step for tool {tool_name} with messages: {prompt_messages}")
    response_args = llm_with_tool.invoke(prompt_messages)
    logger.info(f"Arg step response: {response_args}")

    # The response_args is a Pydantic model. We need to convert it to a dict.
    args_dict = response_args.dict() if hasattr(response_args, 'dict') else response_args.model_dump()

    # LangChain expects tool calls to be in a specific format.
    tool_call = {
        "name": tool_name,
        "args": args_dict,
        "id": str(uuid4()),
    }

    # The state should be updated by appending the new tool call to the existing messages.
    # The reasoning message is already the last message in the list.
    # Clear the next_tool_to_call so we don't loop.
    return {
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "next_tool_to_call": None
    }

# --- Executor Node ---

async def tool_executor_step(state: AgentState) -> dict:
    """Executes the chosen tool with the provided arguments and returns the output."""
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
    tool_call = state['messages'][-1].tool_calls[0]
    tool_name = tool_call['name']
    tool_args = tool_call['args']

    # Initialize the tool map inside the function to avoid serialization issues
    tool_map = {tool.name: tool for tool in all_tools_list}

    # Find the tool in the registry
    tool = tool_map.get(tool_name)
    if not tool:
        error_message = f"Error: Tool '{tool_name}' not found."
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call['id'])]}

    # Execute the tool and get the output
    try:
        # Note: Not all tools may be async, but we run them in a thread pool
        # to avoid blocking the main event loop.
        output = await tool.ainvoke(tool_args)
    except Exception as e:
        error_message = f"Error executing tool {tool_name}: {e}"
        logger.error(error_message, exc_info=True)
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call['id'])]}

    # Format the output for the LLM
    output_content = format_tool_output(output)

    return {
        "messages": [
            ToolMessage(
                content=output_content,
                tool_call_id=tool_call['id'],
            )
        ]
    }

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

def build_state_graph() -> StateGraph:
    """Builds the LangGraph StateGraph for the autonomous agent, without compiling it."""
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
    return workflow

def compile_agent_graph(
    *,
    checkpointer: bool | BaseCheckpointSaver | None = True,
    interrupt_before: Optional[list[str]] = None,
) -> Pregel:
    """Return a compiled graph; when checkpointer is False or None, no persistence."""
    graph = build_state_graph()
    
    cp = None
    if checkpointer is True:  # production default
        cp = MemorySaver()
    elif checkpointer:
        cp = checkpointer  # caller supplied a saver instance

    return graph.compile(
        checkpointer=cp,
        # No default interruption
        interrupt_before=interrupt_before,
    )

# --- Main Entry Points ---

agent_graph = compile_agent_graph()

async def run_agent(question: str, project_subdirectory: str):
    """Run the agent with a given question and project subdirectory."""
    config = {"configurable": {"thread_id": "test-thread"}}
    # The user's question is the first message.
    initial_messages = [HumanMessage(content=question)]

    initial_state = AgentState(
        messages=initial_messages,
        iteration_count=0,
        project_subdirectory=project_subdirectory,
        next_tool_to_call=None,
    )

    # The astream call was for logging, but invoke is what we need for the final state.
    # To avoid running twice, I'll use invoke directly.
    # The original astream loop can be uncommented if verbose logging is needed during debugging.
    # async for event in agent_graph.astream(initial_state, config=config):
    #     for key, value in event.items():
    #         logger.info(f"Event: {key} | Value: {value}")
    #     logger.info("----")

    final_state = await agent_graph.ainvoke(
        initial_state,
        config=config,
    )

    # In LangGraph >= 0.4, invoke can return a tuple of states if multiple branches hit END.
    # We take the last one, which corresponds to the state from the max_iterations_handler.
    if isinstance(final_state, tuple):
        final_state = final_state[-1]

    return final_state["messages"][-1]