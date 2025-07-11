# agent/state.py

from typing import TypedDict, List, Annotated, Optional, Dict, Callable, Any, Awaitable
from pydantic import Field
from langchain_core.messages import BaseMessage
import operator

# The `operator.add` annotation tells LangGraph to append messages
# to this list rather than overwriting it.
class AgentState(TypedDict):
    """
    Represents the state of our LangGraph agent.
    """
    # The user's input prompt
    input: Optional[str] = Field(default=None, description="The initial user input.")
    
    # The list of messages that form the conversation history
    messages: Annotated[List[BaseMessage], operator.add]

    # Counter for the number of iterations/planning steps
    iteration_count: int = Field(default=0, description="Counter for planning iterations.")

    # The subdirectory within REPO_DIR that is the current project's root, e.g., 'my-app'
    project_subdirectory: Optional[str] = Field(default=None, description="The subdirectory within REPO_DIR that is the current project's root, e.g., 'my-app'.")

    # Serialized state for FixCycleTracker
    fix_cycle_tracker_state: Optional[dict] = None

    # The name of the tool chosen by the reason step, to be used by the arg step.
    next_tool_to_call: Optional[str] = Field(default=None, description="The name of the tool selected by the reasoning planner.")
