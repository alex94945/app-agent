# agent/agent_graph.py

import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage, ToolMessage

from agent.state import AgentState
from common.llm import get_llm_client
# We will define the tools in a separate file and import them
from tools.shell_mcp_tools import run_shell
from common.llm import get_llm_client
# We need a generic LLM client for the planner step
# For now, we can assume it's an OpenAI model.
# A more sophisticated get_llm_client can be built later if needed.
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

def planner_llm_step(state: AgentState) -> AgentState:
    """
    The primary LLM-powered node that plans the next step or responds.
    """
    logger.info("Executing planner_llm_step...")

    # Define the tools available for this step
    tools = [run_shell]

    # Initialize the LLM client for this step.
    llm = get_llm_client(purpose="planner").bind_tools(tools)

    # Create a new list of messages to avoid modifying the state directly
    messages: list[BaseMessage] = []

    # Add a system prompt to guide the LLM's behavior for initial scaffolding
    system_prompt = (
        "You are an expert AI developer. Your first task is to set up a new Next.js project. "
        "When the user asks to create an application, your first and only action should be to call the `run_shell` tool "
        "to execute `npx create-next-app@latest`. "
        "Use the following arguments for the command: "
        "`my-app --typescript --tailwind --app --eslint --src-dir --import-alias \"@/*\"`. "
        "Do not ask for confirmation. Do not respond with conversational text. Call the tool directly."
    )
    messages.append(SystemMessage(content=system_prompt))

    # Add the current message history from the state
    messages.extend(state['messages'])

    # The state['messages'] will contain the full conversation history.
    # For the first turn, this will just be the user's HumanMessage.
    prompt_messages = messages

    logger.info("Invoking LLM for planning...")
    response = llm.invoke(prompt_messages)
    logger.info(f"LLM Response: {response.content[:100]}...")
    
    # The response is an AIMessage, which we add to our state's message list.
    # If it contains tool_calls, the graph will route to the tool executor next.
    return {"messages": [response]}

# This is a placeholder for our tool execution node
# We will implement it fully in a later step.
def tool_executor_step(state: AgentState) -> dict:
    logger.info("Executing tool_executor_step (STUB)...")
    # For now, just return a dummy message
    tool_message = ToolMessage(content="Tool execution stubbed.", tool_call_id="0")
    return {"messages": [tool_message]}


def build_graph():
    """
    Builds the LangGraph for the autonomous agent.
    """
    workflow = StateGraph(AgentState)

    # Add the planner node
    workflow.add_node("planner", planner_llm_step)
    # Add a placeholder tool executor node
    workflow.add_node("tool_executor", tool_executor_step)

    # The entry point is the planner
    workflow.set_entry_point("planner")

    # Add a conditional edge from the planner.
    # If the LLM's response contains tool_calls, route to the tool_executor.
    # Otherwise, end the graph.
    def should_continue(state: AgentState) -> str:
        last_message = state['messages'][-1]
        if last_message.tool_calls:
            return "continue"
        return "end"

    workflow.add_conditional_edges("planner", should_continue, {"continue": "tool_executor", "end": END})
    workflow.add_edge("tool_executor", END) # For now, end after one tool call

    # Compile the graph into a runnable app
    # Add a memory saver to keep track of the conversation history for a given thread_id
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    logger.info("LangGraph compiled successfully.")
    return app

# Create a single, reusable instance of the graph
agent_graph = build_graph()

def run_agent(user_input: str, thread_id: str) -> str:
    """
    Runs the agent with a given user input and returns the final response.
    """
    logger.info(f"Running agent for thread '{thread_id}' with input: '{user_input}'")
    
    inputs = {"messages": [HumanMessage(content=user_input)]}
    config = {"configurable": {"thread_id": thread_id}}
    
    # For now, we just run until the end and get the final state.
    # Later, we will stream intermediate steps.
    final_state = agent_graph.invoke(inputs, config)
    
    # The final response is the last AI message in the list.
    last_message = final_state.get("messages", [])[-1]
    return last_message.content if isinstance(last_message, AIMessage) else "No response found."
