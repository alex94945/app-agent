# agent/state.py

from typing import List, Annotated, Optional, Dict
from uuid import UUID
from pydantic import Field, BaseModel
from langchain_core.messages import BaseMessage
import operator



class AgentState(BaseModel):
    """
    Represents the state of our LangGraph agent.
    """
    class Config:
        arbitrary_types_allowed = True

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



    # The planner's reasoning for the current step
    reasoning: Optional[str] = Field(default=None, description="The planner's reasoning for the current step.")