# agent/state.py

from typing import TypedDict, List, Annotated, Optional
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

    # This will store the details (name, args) of the tool call that is currently being fixed.
    # It's used to track retries for a specific operation.
    failing_tool_run: Optional[dict]

    # Counter for how many times we've tried to fix the tool run.
    fix_attempts: int = Field(default=0, description="Counter for fix attempts for a specific failing tool call.")

    # Flag to indicate if the last successful patch for a failing_tool_run needs verification.
    needs_verification: bool = Field(default=False, description="True if a successful patch attempt requires verification.")
