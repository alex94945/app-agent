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

from agent.prompts.planner_system_prompt import PLANNER_SYSTEM_PROMPT_TEMPLATE
from agent.state import AgentState
from common.llm import get_llm_client
from agent.models import PlannerOutput

from agent.executor.output_handlers import format_tool_output


# Import all tools
from tools.file_io_mcp_tools import read_file, write_file

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


# --- Planner Node ---

def planner_reason_step(state: AgentState, llm: Optional[BaseChatModel] = None) -> dict:
    """Single planner step: LLM call to decide on the next tool or a conversational reply."""
    messages = state.messages
    if llm is None:
        llm = get_llm_client().with_structured_output(
            PlannerOutput, method="function_calling"
        )

    # Generate the tool list for the prompt (name + description)
    tool_docs = "\n".join([f"• `{tool.name}`: {tool.description}" for tool in ALL_TOOLS_LIST])
    system_prompt = PLANNER_SYSTEM_PROMPT_TEMPLATE.format(tool_list=tool_docs)

    # The reasoner needs the whole conversation history
    prompt_messages = [SystemMessage(content=system_prompt)] + messages
    logger.info(f"[PlannerStep] LLM Input: {prompt_messages}")

    try:
        result: PlannerOutput = llm.invoke(prompt_messages)
        logger.info(f"[PlannerStep] LLM Output: {result}")
    except Exception as e:
        logger.error(f"[PlannerStep] LLM invocation failed: {e}", exc_info=True)
        raise

    ai_msg = AIMessage(
        content=result.reply or "",
        additional_kwargs={"summary": result.summary, "thought": result.thought},
    )
    if result.tool:
        tool_call = {
            "name": result.tool,
            "args": result.tool_input or {},
            "id": str(uuid4()),
        }
        ai_msg.tool_calls = [tool_call]

    logger.info(f"[PlannerStep] EXIT | AI Message: {ai_msg} | Iteration: {state.iteration_count}")
    return {"messages": [ai_msg]}


# --- Executor Node ---

async def tool_executor_step(state: AgentState) -> dict:
    """Executes the chosen tool with the provided arguments and returns the output."""
    tool_call = state.messages[-1].tool_calls[0]
    tool_name = tool_call['name']
    tool_args = tool_call['args']
    logger.info(f"[ToolExecutorStep] ENTRY | Tool: {tool_name} | Args: {tool_args} | Iteration: {state.iteration_count}")
    tool = next((t for t in ALL_TOOLS_LIST if t.name == tool_name), None)
    if tool is None:
        error_message = f"Tool '{tool_name}' not found."
        logger.error(f"[ToolExecutorStep] {error_message}")
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call['id'])]}
    try:
        if hasattr(tool, 'ainvoke'):
            logger.info(f"[ToolExecutorStep] Invoking async tool '{tool_name}'...")
            output = await tool.ainvoke(tool_args)
        else:
            logger.info(f"[ToolExecutorStep] Invoking sync tool '{tool_name}' in thread...")
            output = await asyncio.to_thread(tool.invoke, tool_args)
        logger.info(f"[ToolExecutorStep] Tool '{tool_name}' output: {output}")
    except Exception as e:
        error_message = f"Error executing tool {tool_name}: {e}"
        logger.error(f"[ToolExecutorStep] {error_message}", exc_info=True)
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call['id'])]}
    output_content = format_tool_output(output)
    logger.info(f"[ToolExecutorStep] EXIT | Tool: {tool_name} | OutputContent: {output_content}")
    return {
        "messages": [ToolMessage(content=output_content, tool_call_id=tool_call['id'])]
    }


# --- Control Flow and Graph Definition ---

def after_planner_router(state: AgentState) -> str:
    """This router checks if the planner has chosen a tool. If so, it routes to the tool executor.
    Otherwise, it ends the process."""
    last = state.messages[-1]
    if getattr(last, "tool_calls", []):
        logger.info("[Router] Planner chose a tool. Routing to Tool Executor.")
        return "tool_executor"
    logger.info("[Router] Planner did not choose a tool. Ending process.")
    return END


def build_agent_graph() -> StateGraph:
    """This function builds and returns the agent state graph."""
    workflow = StateGraph(AgentState)

    # Add the nodes
    workflow.add_node("planner", planner_reason_step)
    workflow.add_node("tool_executor", tool_executor_step)

    # Set the entry point
    workflow.set_entry_point("planner")

    # Add the edges
    workflow.add_conditional_edges(
        "planner",
        after_planner_router,
        {"tool_executor": "tool_executor", END: END},
    )
    workflow.add_edge("tool_executor", "planner")

    return workflow

def compile_agent_graph(
    *,
    checkpointer: bool | BaseCheckpointSaver | None = True,
    interrupt_before: Optional[list[str]] = None,
) -> Pregel:
    """Return a compiled graph; when checkpointer is False or None, no persistence."""
    graph = build_agent_graph()
    
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

    return final_state.messages[-1]