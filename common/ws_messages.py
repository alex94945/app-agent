# common/ws_messages.py

from typing import Dict, Any, Literal, Optional
from pydantic import BaseModel, Field

# Base model for all WebSocket messages to ensure they have a type field 't'
class WsMessage(BaseModel):
    t: str = Field(..., description="The type of the message.")
    d: Any = Field(..., description="The data payload of the message.")

# Specific message types for different events in the agent's lifecycle

class TokenMessage(WsMessage):
    """A message containing a single LLM token for streaming."""
    t: Literal["tok"] = "tok"
    d: str = Field(..., description="A piece of a streamed LLM response.")

class ToolCallMessage(WsMessage):
    """A message indicating the agent is about to call a tool."""
    t: Literal["tool_call"] = "tool_call"
    d: Dict[str, Any] = Field(
        ..., 
        description="Details of the tool call, e.g., {'name': 'tool_name', 'args': {...}}"
    )

class ToolResultMessage(WsMessage):
    """A message containing the result of a tool execution."""
    t: Literal["tool_result"] = "tool_result"
    d: Dict[str, Any] = Field(
        ..., 
        description="The result from the tool call, e.g., {'tool_name': 'tool_name', 'result': ...}"
    )

class FinalMessage(WsMessage):
    """The final, complete response from the agent for a given user prompt."""
    t: Literal["final"] = "final"
    d: str = Field(..., description="The final agent response.")

class ErrorMessage(WsMessage):
    """A message indicating an error occurred in the agent's process."""
    t: Literal["error"] = "error"
    d: str = Field(..., description="The error message.")

# --- PTY Task Streaming Messages ---
from uuid import UUID
import datetime

class TaskStartedData(BaseModel):
    task_id: UUID
    name: str
    started_at: datetime.datetime

class TaskStartedMessage(WsMessage):
    t: Literal["task_started"] = "task_started"
    d: TaskStartedData

class TaskLogData(BaseModel):
    task_id: UUID
    chunk: str

class TaskLogMessage(WsMessage):
    t: Literal["task_log"] = "task_log"
    d: TaskLogData

class TaskFinishedData(BaseModel):
    task_id: UUID
    state: Literal["success", "error", "timeout"]
    exit_code: Optional[int]
    duration_ms: float

class TaskFinishedMessage(WsMessage):
    t: Literal["task_finished"] = "task_finished"
    d: TaskFinishedData