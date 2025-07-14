# agent/models.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class PlannerOutput(BaseModel):
    thought: str = Field(..., description="Private chain-of-thought (≤1–2 sentences)")
    summary: str = Field(..., description="Short rationale shown to user")
    tool: Optional[str] = Field(None, description="Tool name if calling a tool")
    tool_input: Optional[Dict[str, Any]] = Field(
        default=None, description="JSON args for the tool"
    )
    reply: Optional[str] = Field(
        default=None, description="User-facing text when no tool is invoked"
    )
