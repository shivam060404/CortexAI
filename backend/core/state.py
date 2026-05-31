"""
Agent State — extended TypedDict for the LangGraph orchestrator.
"""

from typing import Annotated, List, Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State schema for the deep research agent graph."""
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str
    status: str  # pending, running, completed, failed
    supervisor_phase: str
    analysis_summary: str
    evidence_confidence: float
    needs_replan: bool
    final_output: str
    supervisor_events: list[dict]
    iteration: int
    consecutive_failures: int
    accessed_urls: Annotated[set[str], lambda x, y: x | y]
    hitl_mode: str  # "auto", "supervised", "collaborative"
    pending_approval: dict | None
    user_modifications: list[dict]
    next: str
    plan_id: str | None
    plan_version: int
    plan_status: str
    plan_summary: str
    last_worker: str | None
