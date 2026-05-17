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
    iteration: int
    consecutive_failures: int
    accessed_urls: Annotated[set[str], lambda x, y: x | y]
