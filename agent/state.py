# agent/state.py

from typing import TypedDict, List, Annotated
from langchain_core.messages import BaseMessage
import operator

# The `operator.add` annotation tells LangGraph to append messages
# to this list rather than overwriting it.
class AgentState(TypedDict):
    """
    Represents the state of our LangGraph agent.
    """
    # The user's input prompt
    input: str
    
    # The list of messages that form the conversation history
    messages: Annotated[List[BaseMessage], operator.add]

    # Counter for the number of iterations/planning steps
    iteration_count: int
