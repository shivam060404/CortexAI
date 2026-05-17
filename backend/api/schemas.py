"""
Pydantic request/response schemas for the CortexAI API.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# --- Requests ---
class CreateSessionRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000, description="Research query")

class WatchSessionRequest(BaseModel):
    topic: str = Field(..., description="Topic to continuously monitor in the background")
    frequency_hours: float = Field(24.0, description="How often to run the watch (in hours)")


# --- Responses ---
class TodoItemResponse(BaseModel):
    id: str
    text: str
    status: TodoStatus
    order: int
    error_message: str = ""

    class Config:
        from_attributes = True


class WorkspaceFileResponse(BaseModel):
    name: str
    is_dir: bool
    size: int = 0


class ExecutionMetrics(BaseModel):
    iterations_count: int = 0
    tool_calls_count: int = 0
    tokens_used: int = 0
    time_elapsed: float = 0.0
    limits: dict = {}


class ExperimentTrackResponse(BaseModel):
    id: str
    hypothesis: str
    approach: str
    result: str
    conclusion: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class SessionResponse(BaseModel):
    id: str
    title: str
    user_request: str
    status: str
    final_report: str = ""
    iterations_used: int = 0
    tokens_used: int = 0
    tool_calls_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class SessionListResponse(BaseModel):
    sessions: List[SessionResponse]
    total: int


class AgentEvent(BaseModel):
    """WebSocket event schema."""
    type: str  # thinking, tool_call, tool_result, message, todo_update, file_write, metrics, error, complete
    data: dict = {}
