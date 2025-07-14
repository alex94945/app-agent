# agent/agent_graph.py

import logging
import asyncio
import json
import re
from typing import Optional
from uuid import uuid4
from langgraph.graph import StateGraph, END
from langgraph.pregel import Pregel
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
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

from agent.prompts.arg_generator_system_prompt import get_arg_generator_system_prompt
from agent.prompts.planner_system_prompt import PLANNER_SYSTEM_PROMPT
from agent.state import AgentState
from common.llm import get_llm_client
from agent.executor.runner import run_single_tool
from agent.executor.output_handlers import format_tool_output


# Import all tools
from tools.file_io_mcp_tools import read_file, write_file
from tools.scaffold_tool import scaffold_project, ScaffoldProjectOutput
from tools.shell_mcp_tools import run_shell
from tools.patch_tools import apply_patch
from tools.vector_store_tools import vector_search
from tools.lsp_tools import lsp_definition, lsp_hover
from tools.diagnostics_tools import get_diagnostics, diagnose

# List of all tools used by the agent
ALL_TOOLS_LIST = [
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

def planner_reason_step(state: AgentState, llm: Optional[BaseChatModel] = None, system_prompt: Optional[str] = None) -> dict:
    """First planner step: LLM call without tool schemas to decide which tool to use."""
    messages = state['messages']
    if llm is None:
        llm = get_llm_client().with_structured_output(ToolPicker)

    if system_prompt is None:
        system_prompt = PLANNER_SYSTEM_PROMPT

    prompt_messages = [SystemMessage(content=system_prompt)] + messages

    logger.info(f"Invoking reason step with messages: {prompt_messages}")
    result = llm.invoke(prompt_messages)
    logger.info(f"Reason step result: {result}")
    return {"tool_picker": result}

def planner_arg_step(state: AgentState) -> dict:
    """This step generates the arguments for the tool chosen in the reason step."""
    tool_name = state.get("next_tool_to_call")
    if not tool_name:
        # The planner has decided the task is complete.
        # We pass through the AIMessage from the previous step.
        logger.info("Arg step is skipping: task is complete.")
        return {}

    tool = next((t for t in ALL_TOOLS_LIST if t.name == tool_name), None)
    if tool is None:
        logger.warning(f"Tool '{tool_name}' not found in available tools.")
        return {}

    # Prepare the prompt for argument generation
    tool_args_schema = tool.args_schema.schema() if hasattr(tool, 'args_schema') else {}
    system_prompt = get_arg_generator_system_prompt(tool_name, tool.description, tool_args_schema.get('properties', {}))
    messages = state['messages']
    llm = get_llm_client().with_structured_output(tool.args_schema)
    prompt_messages = [SystemMessage(content=system_prompt)] + messages

    logger.info(f"Invoking arg step for tool '{tool_name}' with messages: {prompt_messages}")
    response_args = llm.invoke(prompt_messages)
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
    tool_call = state['messages'][-1].tool_calls[0]
    tool_name = tool_call['name']
    tool_args = tool_call['args']

    tool = next((t for t in ALL_TOOLS_LIST if t.name == tool_name), None)
    if tool is None:
        error_message = f"Tool '{tool_name}' not found."
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call['id'])]}

    try:
        # Tool execution may be async; run in a thread if not
        if hasattr(tool, 'ainvoke'):
            output = await tool.ainvoke(tool_args)
        else:
            # Run synchronous tools in a thread to avoid blocking the main event loop.
            output = await asyncio.to_thread(tool.invoke, tool_args)
    except Exception as e:
        error_message = f"Error executing tool {tool_name}: {e}"
        logger.error(error_message, exc_info=True)
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call['id'])]}

    # Format the output for the LLM
    output_content = format_tool_output(output)

    if isinstance(output, ScaffoldProjectOutput):
        return {
            "messages": [
                ToolMessage(
                    content=output_content,
                    tool_call_id=tool_call['id'],
                )
            ],
            "project_subdirectory": output.project_subdirectory,
        }
    else:
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
    workflow.add_node("planner_reasoner", RunnableLambda(planner_reason_step))
    workflow.add_node("planner_arg_generator", RunnableLambda(planner_arg_step))
    workflow.add_node("tool_executor", RunnableLambda(tool_executor_step))

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
    workflow.add_edge("tool_executor", "planner_reasoner")
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

    agent_graph = compile_agent_graph()

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