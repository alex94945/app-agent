# agent/agent_graph.py

import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState
from common.config import settings
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
    
    # For now, we use a simple prompt. This will become more complex.
    # The state['messages'] will contain the full history.
    prompt_messages = state['messages']
    
    # Initialize the LLM client for this step
    # This assumes OpenAI for planning, as per our design.
    llm = ChatOpenAI(api_key=settings.OPENAI_API_KEY.get_secret_value())
    
    logger.info("Invoking LLM for planning...")
    response = llm.invoke(prompt_messages)
    logger.info(f"LLM Response: {response.content[:100]}...")
    
    # The response is an AIMessage, which we add to our state's message list
    return {"messages": [response]}


def build_graph():
    """
    Builds the LangGraph for the autonomous agent.
    """
    workflow = StateGraph(AgentState)

    # Add the planner node
    workflow.add_node("planner", planner_llm_step)

    # The entry point is the planner
    workflow.set_entry_point("planner")

    # For now, the graph ends after the first planning step.
    # Later, we will add conditional edges to a tool executor.
    workflow.add_edge("planner", END)

    # Compile the graph into a runnable app
    # Add a memory saver to keep track of the conversation history
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
