"""
LangGraph Orchestrator — tool-augmented agent loop with ExecutionGuard middleware.
Replaces the old fixed-node graph with a dynamic ReAct loop.
Persists AgentTrace records to PostgreSQL for observability.
"""

import json
import time
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.core.state import AgentState
from backend.core.execution_guard import ExecutionGuard, ExecutionLimitExceeded
from backend.core.tool_guard import ToolPermissionGuard, ToolNotAllowed
from backend.core.logger import get_logger
from backend.agents.cro_agent import get_cro_supervisor_agent, CRO_SYSTEM_PROMPT
from backend.agents.search_agent import create_search_agent
from backend.agents.verification_agent import create_verification_agent
from backend.core.context_graph import ContextGraph
from backend.config import settings
import re

logger = get_logger(__name__)

# Map session_id -> ContextGraph
_session_graphs: dict[str, ContextGraph] = {}

def get_context_graph(session_id: str) -> ContextGraph:
    if session_id not in _session_graphs:
        _session_graphs[session_id] = ContextGraph(session_id)
    return _session_graphs[session_id]

# Per-session guards stored here (keyed by session_id)
_session_guards: dict[str, ExecutionGuard] = {}
_session_tool_guards: dict[str, ToolPermissionGuard] = {}
_session_context_managers: dict[str, ContextManager] = {}


def _get_guard(session_id: str) -> ExecutionGuard:
    if session_id not in _session_guards:
        _session_guards[session_id] = ExecutionGuard()
    return _session_guards[session_id]


def _get_tool_guard(session_id: str) -> ToolPermissionGuard:
    if session_id not in _session_tool_guards:
        _session_tool_guards[session_id] = ToolPermissionGuard()
    return _session_tool_guards[session_id]


def _get_context_manager(session_id: str) -> ContextManager:
    if session_id not in _session_context_managers:
        _session_context_managers[session_id] = ContextManager(session_id)
    return _session_context_managers[session_id]


def get_execution_metrics(session_id: str) -> dict:
    """Get current execution metrics for a session."""
    guard = _session_guards.get(session_id)
    return guard.metrics() if guard else {}


async def _persist_trace(session_id: str, event_type: str, tool_name: str = "",
                         input_data: dict | None = None, output_data: dict | None = None,
                         latency_ms: float = 0.0, tokens_used: int = 0,
                         is_error: bool = False, error_detail: str = ""):
    """Persist an AgentTrace record to PostgreSQL."""
    try:
        from backend.db.postgres import async_session as db_session_factory, AgentTrace
        async with db_session_factory() as db:
            trace = AgentTrace(
                session_id=session_id,
                event_type=event_type,
                tool_name=tool_name,
                input_data=input_data or {},
                output_data=output_data or {},
                latency_ms=latency_ms,
                tokens_used=tokens_used,
                is_error=is_error,
                error_detail=error_detail,
            )
            db.add(trace)
            await db.commit()
    except Exception as e:
        logger.error("trace_persist_failed", session_id=session_id, error=str(e))


async def build_graph(session_id: str):
    """
    Builds a Multi-Agent LangGraph with a Chief Research Officer (CRO) routing to Search and Verification agents.
    Powered by the Central Context Graph.
    """
    # Initialize the graph OS
    ctx_graph = get_context_graph(session_id)
    
    # 1. Create Agents
    cro_llm = get_cro_supervisor_agent()
    search_llm, search_tools, search_prompt = create_search_agent()
    verif_llm, verif_tools, verif_prompt = create_verification_agent()
    
    search_tool_node = ToolNode(search_tools)
    verif_tool_node = ToolNode(verif_tools)

    # 2. Define Nodes
    async def supervisor_node(state: AgentState):
        messages = [SystemMessage(content=CRO_SYSTEM_PROMPT)] + state["messages"]
        response = await cro_llm.ainvoke(messages)
        # Parse decision (SearchAgent, VerificationAgent, or FINISH)
        decision = response.content.strip()
        if "FINISH" in decision:
            next_node = "FINISH"
        elif "VerificationAgent" in decision:
            next_node = "VerificationAgent"
        else:
            next_node = "SearchAgent" # Default fallback
            
        logger.info("cro_routing_decision", decision=next_node)
        return {"next": next_node}

    async def search_node(state: AgentState):
        messages = [SystemMessage(content=search_prompt)] + state["messages"]
        response = await search_llm.ainvoke(messages)
        # In a full implementation, we'd extract URLs/Findings here and push to ctx_graph.add_node()
        return {"messages": [response], "iteration": state.get("iteration", 0) + 1}

    async def verification_node(state: AgentState):
        messages = [SystemMessage(content=verif_prompt)] + state["messages"]
        response = await verif_llm.ainvoke(messages)
        return {"messages": [response], "iteration": state.get("iteration", 0) + 1}

    # 3. Build Graph
    graph = StateGraph(AgentState)
    
    graph.add_node("CRO", supervisor_node)
    graph.add_node("SearchAgent", search_node)
    graph.add_node("VerificationAgent", verification_node)
    graph.add_node("SearchTools", search_tool_node)
    graph.add_node("VerificationTools", verif_tool_node)
    
    graph.set_entry_point("CRO")
    
    # Edges from CRO
    def route_from_cro(state):
        return state.get("next", "SearchAgent")
        
    graph.add_conditional_edges("CRO", route_from_cro, {
        "SearchAgent": "SearchAgent",
        "VerificationAgent": "VerificationAgent",
        "FINISH": END
    })
    
    # Tool routing for Search
    def route_search(state):
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "SearchTools"
        return "CRO"
        
    graph.add_conditional_edges("SearchAgent", route_search, {
        "SearchTools": "SearchTools",
        "CRO": "CRO"
    })
    graph.add_edge("SearchTools", "SearchAgent")
    
    # Tool routing for Verification
    def route_verif(state):
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "VerificationTools"
        return "CRO"
        
    graph.add_conditional_edges("VerificationAgent", route_verif, {
        "VerificationTools": "VerificationTools",
        "CRO": "CRO"
    })
    graph.add_edge("VerificationTools", "VerificationAgent")
    
    # Create persistent checkpointer
    checkpointer = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    await checkpointer.setup()

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("multi_agent_graph_compiled", session_id=session_id)
    return compiled


def cleanup_session(session_id: str):
    """Clean up per-session state."""
    _session_guards.pop(session_id, None)
    _session_tool_guards.pop(session_id, None)
    _session_context_managers.pop(session_id, None)
    clear_failures(session_id)


async def cleanup_stale_sessions(max_age_hours: int = 24):
    """Remove sessions that have been idle for more than max_age_hours."""
    stale_ids = []
    for session_id in list(_session_graphs.keys()):
        guard = _session_guards.get(session_id)
        if guard and hasattr(guard, 'start_time'):
            import time as _time
            if _time.time() - guard.start_time > max_age_hours * 3600:
                stale_ids.append(session_id)

    for session_id in stale_ids:
        cleanup_session(session_id)

    if stale_ids:
        logger.info("stale_sessions_cleaned", count=len(stale_ids))
    return len(stale_ids)
