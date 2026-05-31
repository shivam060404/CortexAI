"""
LangGraph orchestration with PostgreSQL-backed checkpoint persistence.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
except ImportError:  # pragma: no cover - optional dependency fallback
    AsyncPostgresSaver = None
    from langgraph.checkpoint.memory import MemorySaver
else:
    MemorySaver = None

from backend.agents.context_manager import ContextManager
from backend.agents.cro_agent import CRO_SYSTEM_PROMPT, get_cro_supervisor_agent
from backend.agents.search_agent import create_search_agent
from backend.agents.verification_agent import create_verification_agent
from backend.config import settings
from backend.core.context_graph import ContextGraph
from backend.core.execution_guard import ExecutionGuard
from backend.core.failure_memory import clear_failures
from backend.core.logger import get_logger
from backend.core.state import AgentState
from backend.core.tool_guard import ToolPermissionGuard
from backend.tools.planning_tools import load_latest_plan, persist_research_plan

logger = get_logger(__name__)

SESSION_IDLE_TTL_SECONDS = 24 * 60 * 60
SUPERVISOR_PHASE_RECEIVED = "RECEIVED"
SUPERVISOR_PHASE_ANALYZING = "ANALYZING"
SUPERVISOR_PHASE_PLANNING = "PLANNING"
SUPERVISOR_PHASE_DISPATCHING = "DISPATCHING"
SUPERVISOR_PHASE_WAITING = "WAITING"
SUPERVISOR_PHASE_EVALUATING = "EVALUATING"
SUPERVISOR_PHASE_REPLANNING = "REPLANNING"
SUPERVISOR_PHASE_COMPILING = "COMPILING"
SUPERVISOR_PHASE_COMPLETED = "COMPLETED"
SUPERVISOR_PHASE_FAILED = "FAILED"
SUPERVISOR_ACTIVE_PHASES = {
    SUPERVISOR_PHASE_RECEIVED,
    SUPERVISOR_PHASE_ANALYZING,
    SUPERVISOR_PHASE_PLANNING,
    SUPERVISOR_PHASE_DISPATCHING,
    SUPERVISOR_PHASE_WAITING,
    SUPERVISOR_PHASE_EVALUATING,
    SUPERVISOR_PHASE_REPLANNING,
    SUPERVISOR_PHASE_COMPILING,
}

_session_graphs: dict[str, ContextGraph] = {}
_session_guards: dict[str, ExecutionGuard] = {}
_session_tool_guards: dict[str, ToolPermissionGuard] = {}
_session_context_managers: dict[str, ContextManager] = {}
_session_last_accessed: dict[str, float] = {}
_session_metric_snapshots: dict[str, dict] = {}
_compiled_graphs: dict[str, Any] = {}
_checkpointer = None


class _FallbackLLM:
    """Minimal no-op LLM used when model credentials are unavailable."""

    def __init__(self, content: str):
        self.content = content

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        return AIMessage(content=self.content)


def get_context_graph(session_id: str) -> ContextGraph:
    if session_id not in _session_graphs:
        _session_graphs[session_id] = ContextGraph(session_id)
    return _session_graphs[session_id]


def _touch_session(session_id: str) -> None:
    _session_last_accessed[session_id] = time.time()


def _get_guard(session_id: str) -> ExecutionGuard:
    if session_id not in _session_guards:
        _session_guards[session_id] = ExecutionGuard()
    _touch_session(session_id)
    return _session_guards[session_id]


def _get_tool_guard(session_id: str) -> ToolPermissionGuard:
    if session_id not in _session_tool_guards:
        _session_tool_guards[session_id] = ToolPermissionGuard()
    _touch_session(session_id)
    return _session_tool_guards[session_id]


def _get_context_manager(session_id: str) -> ContextManager:
    if session_id not in _session_context_managers:
        _session_context_managers[session_id] = ContextManager(session_id)
    _touch_session(session_id)
    return _session_context_managers[session_id]


async def _get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        if AsyncPostgresSaver is None:
            logger.warning("postgres_checkpointer_unavailable", fallback="memory")
            _checkpointer = MemorySaver()
        else:
            conn_string = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
            _checkpointer = AsyncPostgresSaver.from_conn_string(conn_string)
            await _checkpointer.setup()
    return _checkpointer


def get_execution_metrics(session_id: str) -> dict:
    guard = _session_guards.get(session_id)
    if guard:
        metrics = guard.metrics()
        _session_metric_snapshots[session_id] = metrics
        return metrics
    return _session_metric_snapshots.get(session_id, {})


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content or "")


def _build_fallback_plan(query: str) -> list[dict]:
    short_query = query.strip()[:200] or "the research request"
    tasks = [
        f"Clarify the scope, constraints, and success criteria for {short_query}.",
        "Collect high-signal sources and supporting evidence relevant to the request.",
        "Compare conflicting findings and identify verification checkpoints.",
        "Synthesize the strongest insights into a structured final report outline.",
    ]
    return [
        {
            "id": str(uuid.uuid4()),
            "text": task,
            "status": "pending",
            "order": index,
            "error_message": "",
        }
        for index, task in enumerate(tasks)
    ]


def _phase_event(phase: str, event_type: str, **details: Any) -> dict[str, Any]:
    return {"phase": phase, "event_type": event_type, **details}


def _append_event(state: AgentState, phase: str, event_type: str, **details: Any) -> list[dict[str, Any]]:
    return list(state.get("supervisor_events", [])) + [_phase_event(phase, event_type, **details)]


def _analyze_query(query: str) -> dict[str, Any]:
    trimmed = query.strip()
    if not trimmed:
        return {"valid": False, "summary": "Query is empty", "entities": [], "constraints": []}

    words = [word.strip(".,:;!?()[]{}").lower() for word in trimmed.split()]
    unique_words = [word for word in words if word]
    entities = [word for word in unique_words if len(word) > 6][:5]
    constraints = []
    if "compare" in unique_words:
        constraints.append("comparison")
    if "benchmark" in unique_words:
        constraints.append("benchmark")
    if "risk" in unique_words:
        constraints.append("risk")

    summary = (
        f"Intent analyzed for request: {trimmed[:180]}. "
        f"Key entities: {', '.join(entities) if entities else 'general research scope'}. "
        f"Constraints: {', '.join(constraints) if constraints else 'none explicit'}."
    )
    return {"valid": True, "summary": summary[:1000], "entities": entities, "constraints": constraints}


async def _replan_persisted_plan(session_id: str, analysis_summary: str, previous_plan: dict | None) -> dict[str, Any]:
    if previous_plan and previous_plan.get("todos"):
        replanned_todos = []
        for index, item in enumerate(previous_plan["todos"]):
            status = item.get("status", "pending")
            if status in {"failed", "in_progress"}:
                status = "pending"
            replanned_todos.append(
                {
                    "id": item.get("id", str(uuid.uuid4())),
                    "text": item.get("text", "")[:1000],
                    "status": status,
                    "order": index,
                    "error_message": "",
                }
            )
        replanned_todos.append(
            {
                "id": str(uuid.uuid4()),
                "text": f"Close remaining evidence gaps based on: {analysis_summary[:200]}",
                "status": "pending",
                "order": len(replanned_todos),
                "error_message": "",
            }
        )
    else:
        replanned_todos = _build_fallback_plan(analysis_summary or session_id)
    return await persist_research_plan(session_id, replanned_todos, source="supervisor_replan")


async def _complete_persisted_plan(session_id: str, existing_plan: dict | None) -> dict | None:
    if not existing_plan or not existing_plan.get("todos"):
        return existing_plan

    completed_todos = []
    for index, item in enumerate(existing_plan["todos"]):
        completed_todos.append(
            {
                "id": item.get("id", str(uuid.uuid4())),
                "text": item.get("text", "")[:1000],
                "status": "completed",
                "order": index,
                "error_message": "",
            }
        )
    return await persist_research_plan(session_id, completed_todos, source="supervisor_compile")


def _normalize_plan_items(items: list[Any]) -> list[dict]:
    normalized: list[dict] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            text_value = item
            status = "pending"
            error_message = ""
        else:
            text_value = item.get("text") or item.get("task") or str(item)
            status = item.get("status", "pending")
            error_message = item.get("error_message", "")

        if status not in {"pending", "in_progress", "completed", "failed"}:
            status = "pending"

        normalized.append(
            {
                "id": item.get("id", str(uuid.uuid4())) if isinstance(item, dict) else str(uuid.uuid4()),
                "text": text_value[:1000],
                "status": status,
                "order": index,
                "error_message": error_message,
            }
        )
    return normalized


async def _generate_persisted_plan(session_id: str, query: str, planner_llm) -> dict:
    prompt = (
        "Create a durable research execution plan for the following user request.\n"
        "Return ONLY valid JSON as an array of 4 to 8 objects.\n"
        "Each object must contain: text, status.\n"
        "Use status='pending' for new tasks.\n\n"
        f"Request:\n{query}"
    )
    todos = _build_fallback_plan(query)
    try:
        response = await planner_llm.ainvoke([SystemMessage(content=prompt)])
        raw_content = _extract_message_text(getattr(response, "content", ""))
        cleaned = raw_content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, list) and parsed:
            todos = _normalize_plan_items(parsed)
    except Exception as exc:
        logger.warning("planner_generation_fallback", session_id=session_id, error=str(exc))

    plan = await persist_research_plan(session_id, todos, source="supervisor")
    return plan or {
        "id": "",
        "session_id": session_id,
        "version": 0,
        "status": "pending",
        "source": "fallback",
        "summary": "Fallback plan active",
        "todos": todos,
        "is_current": True,
        "created_at": None,
        "updated_at": None,
    }


def _plan_state_updates(plan: dict | None) -> dict:
    if not plan:
        return {
            "plan_id": None,
            "plan_version": 0,
            "plan_status": "missing",
            "plan_summary": "",
        }
    return {
        "plan_id": plan.get("id"),
        "plan_version": int(plan.get("version", 0) or 0),
        "plan_status": plan.get("status", "pending"),
        "plan_summary": plan.get("summary", ""),
    }


def decide_next_step(plan_version: int, plan_status: str, iteration: int, last_worker: str | None) -> str:
    if plan_version <= 0 or plan_status in {"missing", "failed"}:
        return "Planner"
    if plan_status == "completed" or iteration >= settings.MAX_ITERATIONS:
        return "FINISH"
    if last_worker == "SearchAgent":
        return "VerificationAgent"
    return "SearchAgent"


def decide_evaluation_outcome(
    *,
    plan_version: int,
    plan_status: str,
    iteration: int,
    last_worker: str | None,
    evidence_confidence: float,
    needs_replan: bool = False,
) -> str:
    if plan_version <= 0 or plan_status in {"missing", "failed"} or needs_replan:
        return "REPLANNING"
    if iteration >= settings.MAX_ITERATIONS or plan_status == "completed":
        return "COMPILING"
    if evidence_confidence >= 0.85 and last_worker == "VerificationAgent":
        return "COMPILING"
    return "DISPATCHING"


def _parse_supervisor_decision(raw_decision: str, fallback_decision: str) -> str:
    decision = raw_decision.strip()
    if "FINISH" in decision:
        return "FINISH"
    if "Planner" in decision:
        return "Planner"
    if "VerificationAgent" in decision:
        return "VerificationAgent"
    if "SearchAgent" in decision:
        return "SearchAgent"
    return fallback_decision


async def build_graph(session_id: str):
    """Build and compile a session-aware research graph using a persistent checkpointer."""

    _touch_session(session_id)
    get_context_graph(session_id)
    _get_guard(session_id)
    _get_tool_guard(session_id)
    _get_context_manager(session_id)

    if session_id in _compiled_graphs:
        return _compiled_graphs[session_id]

    try:
        cro_llm = get_cro_supervisor_agent()
        search_llm, search_tools, search_prompt = create_search_agent()
        verif_llm, verif_tools, verif_prompt = create_verification_agent()
    except Exception as exc:
        logger.warning("graph_agent_init_fallback", error=str(exc))
        cro_llm = _FallbackLLM("FINISH")
        search_tools = []
        verif_tools = []
        search_prompt = "Search unavailable in fallback mode."
        verif_prompt = "Verification unavailable in fallback mode."
        search_llm = _FallbackLLM("Fallback search response")
        verif_llm = _FallbackLLM("Fallback verification response")

    search_tool_node = ToolNode(search_tools)
    verif_tool_node = ToolNode(verif_tools)

    async def load_plan_node(state: AgentState):
        _touch_session(state["session_id"])
        plan = await load_latest_plan(state["session_id"])
        next_node = "Received"
        return {"next": next_node, **_plan_state_updates(plan)}

    async def received_node(state: AgentState):
        _touch_session(state["session_id"])
        return {
            "status": "running",
            "supervisor_phase": SUPERVISOR_PHASE_RECEIVED,
            "next": "Analyzing",
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_RECEIVED,
                "supervisor.request.received",
                session_id=state["session_id"],
            ),
        }

    async def analyzing_node(state: AgentState):
        _touch_session(state["session_id"])
        analysis = _analyze_query(_extract_message_text(state["messages"][0].content))
        next_node = "Planning" if analysis["valid"] else "Failed"
        return {
            "analysis_summary": analysis["summary"],
            "supervisor_phase": SUPERVISOR_PHASE_ANALYZING,
            "next": next_node,
            "status": "running" if analysis["valid"] else "failed",
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_ANALYZING,
                "supervisor.analysis.started",
                valid=analysis["valid"],
            ),
        }

    async def planner_node(state: AgentState):
        _touch_session(state["session_id"])
        plan = await _generate_persisted_plan(
            state["session_id"],
            f"{_extract_message_text(state['messages'][0].content)}\n\nAnalysis:\n{state.get('analysis_summary', '')}",
            cro_llm,
        )
        return {
            "messages": [AIMessage(content=f"Persisted research plan v{plan.get('version', 0)}")],
            "next": "CRO",
            "last_worker": "Planner",
            "supervisor_phase": SUPERVISOR_PHASE_PLANNING,
            "needs_replan": False,
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_PLANNING,
                "supervisor.plan.created",
                version=plan.get("version", 0),
            ),
            **_plan_state_updates(plan),
        }

    async def dispatching_node(state: AgentState):
        _touch_session(state["session_id"])
        fallback_decision = decide_next_step(
            state.get("plan_version", 0),
            state.get("plan_status", "missing"),
            state.get("iteration", 0),
            state.get("last_worker"),
        )
        if fallback_decision in {"Planner", "FINISH"}:
            return {"next": fallback_decision}

        messages = [
            SystemMessage(
                content=(
                    f"{CRO_SYSTEM_PROMPT}\n\n"
                    f"Persisted plan version: {state.get('plan_version', 0)}\n"
                    f"Persisted plan status: {state.get('plan_status', 'missing')}\n"
                    f"Plan summary: {state.get('plan_summary', '') or 'No plan summary available'}\n"
                    f"Last worker: {state.get('last_worker') or 'none'}\n"
                    f"Current iteration: {state.get('iteration', 0)}"
                )
            )
        ] + state["messages"]
        try:
            response = await cro_llm.ainvoke(messages)
            decision = _extract_message_text(getattr(response, "content", ""))
        except Exception as exc:
            logger.warning("supervisor_routing_fallback", session_id=state["session_id"], error=str(exc))
            decision = fallback_decision

        next_node = _parse_supervisor_decision(decision, fallback_decision)
        if next_node == "FINISH":
            next_node = "Compiling"
        if next_node == "Planner":
            next_node = "Replanning"
        return {
            "next": next_node,
            "supervisor_phase": SUPERVISOR_PHASE_DISPATCHING,
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_DISPATCHING,
                "supervisor.batch.dispatched",
                target=next_node,
            ),
        }

    async def search_node(state: AgentState):
        _touch_session(state["session_id"])
        messages = [
            SystemMessage(
                content=(
                    f"{search_prompt}\n\n"
                    f"Plan summary: {state.get('plan_summary', '') or 'No persisted plan loaded.'}\n"
                    f"Plan version: {state.get('plan_version', 0)}"
                )
            )
        ] + state["messages"]
        response = await search_llm.ainvoke(messages)
        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
            "last_worker": "SearchAgent",
            "supervisor_phase": SUPERVISOR_PHASE_WAITING,
            "evidence_confidence": max(float(state.get("evidence_confidence", 0.0) or 0.0), 0.55),
            "next": "Evaluating",
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_WAITING,
                "worker.task.completed",
                worker="SearchAgent",
            ),
        }

    async def verification_node(state: AgentState):
        _touch_session(state["session_id"])
        messages = [
            SystemMessage(
                content=(
                    f"{verif_prompt}\n\n"
                    f"Plan summary: {state.get('plan_summary', '') or 'No persisted plan loaded.'}\n"
                    f"Plan version: {state.get('plan_version', 0)}"
                )
            )
        ] + state["messages"]
        response = await verif_llm.ainvoke(messages)
        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
            "last_worker": "VerificationAgent",
            "supervisor_phase": SUPERVISOR_PHASE_WAITING,
            "evidence_confidence": max(float(state.get("evidence_confidence", 0.0) or 0.0), 0.9),
            "next": "Evaluating",
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_WAITING,
                "worker.task.completed",
                worker="VerificationAgent",
            ),
        }

    async def evaluating_node(state: AgentState):
        _touch_session(state["session_id"])
        next_node = decide_evaluation_outcome(
            plan_version=state.get("plan_version", 0),
            plan_status=state.get("plan_status", "missing"),
            iteration=state.get("iteration", 0),
            last_worker=state.get("last_worker"),
            evidence_confidence=float(state.get("evidence_confidence", 0.0) or 0.0),
            needs_replan=bool(state.get("needs_replan", False)),
        )
        return {
            "next": {
                "DISPATCHING": "CRO",
                "REPLANNING": "Replanning",
                "COMPILING": "Compiling",
            }[next_node],
            "supervisor_phase": SUPERVISOR_PHASE_EVALUATING,
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_EVALUATING,
                "supervisor.evaluation.completed",
                decision=next_node,
                evidence_confidence=state.get("evidence_confidence", 0.0),
            ),
        }

    async def replanning_node(state: AgentState):
        _touch_session(state["session_id"])
        current_plan = await load_latest_plan(state["session_id"])
        plan = await _replan_persisted_plan(
            state["session_id"],
            state.get("analysis_summary", ""),
            current_plan,
        )
        return {
            "messages": [AIMessage(content=f"Replanned research plan v{plan.get('version', 0)}")],
            "next": "CRO",
            "last_worker": "Planner",
            "supervisor_phase": SUPERVISOR_PHASE_REPLANNING,
            "needs_replan": False,
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_REPLANNING,
                "supervisor.replan.created",
                version=plan.get("version", 0),
            ),
            **_plan_state_updates(plan),
        }

    async def compiling_node(state: AgentState):
        _touch_session(state["session_id"])
        completed_plan = await _complete_persisted_plan(state["session_id"], await load_latest_plan(state["session_id"]))
        final_output = (
            f"Workflow completed for session {state['session_id']}. "
            f"Analysis: {state.get('analysis_summary', '')[:200]} "
            f"Confidence: {float(state.get('evidence_confidence', 0.0) or 0.0):.2f}"
        ).strip()
        return {
            "messages": [AIMessage(content=final_output)],
            "status": "completed",
            "supervisor_phase": SUPERVISOR_PHASE_COMPLETED,
            "final_output": final_output[:2000],
            "next": "FINISH",
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_COMPILING,
                "supervisor.report.finalized",
                status="completed",
            ),
            **_plan_state_updates(completed_plan),
        }

    async def failed_node(state: AgentState):
        _touch_session(state["session_id"])
        return {
            "status": "failed",
            "supervisor_phase": SUPERVISOR_PHASE_FAILED,
            "final_output": state.get("analysis_summary", "Workflow failed validation"),
            "next": "FINISH",
            "supervisor_events": _append_event(
                state,
                SUPERVISOR_PHASE_FAILED,
                "supervisor.workflow.failed",
                reason=state.get("analysis_summary", "unknown"),
            ),
        }

    graph = StateGraph(AgentState)
    graph.add_node("LoadPlan", load_plan_node)
    graph.add_node("Received", received_node)
    graph.add_node("Analyzing", analyzing_node)
    graph.add_node("Planning", planner_node)
    graph.add_node("CRO", dispatching_node)
    graph.add_node("SearchAgent", search_node)
    graph.add_node("VerificationAgent", verification_node)
    graph.add_node("Evaluating", evaluating_node)
    graph.add_node("Replanning", replanning_node)
    graph.add_node("Compiling", compiling_node)
    graph.add_node("Failed", failed_node)
    graph.add_node("SearchTools", search_tool_node)
    graph.add_node("VerificationTools", verif_tool_node)
    graph.set_entry_point("LoadPlan")

    graph.add_conditional_edges(
        "LoadPlan",
        lambda state: state.get("next", "Received"),
        {
            "Received": "Received",
        },
    )

    graph.add_edge("Received", "Analyzing")

    graph.add_conditional_edges(
        "Analyzing",
        lambda state: state.get("next", "Planning"),
        {
            "Planning": "Planning",
            "Failed": "Failed",
        },
    )

    graph.add_conditional_edges(
        "Planning",
        lambda state: state.get("next", "CRO"),
        {
            "CRO": "CRO",
        },
    )

    graph.add_conditional_edges(
        "CRO",
        lambda state: state.get("next", "Replanning"),
        {
            "Replanning": "Replanning",
            "SearchAgent": "SearchAgent",
            "VerificationAgent": "VerificationAgent",
            "Compiling": "Compiling",
        },
    )

    graph.add_conditional_edges(
        "SearchAgent",
        lambda state: "SearchTools"
        if getattr(state["messages"][-1], "tool_calls", None)
        else "CRO",
        {
            "SearchTools": "SearchTools",
            "CRO": "Evaluating",
        },
    )
    graph.add_edge("SearchTools", "SearchAgent")

    graph.add_conditional_edges(
        "VerificationAgent",
        lambda state: "VerificationTools"
        if getattr(state["messages"][-1], "tool_calls", None)
        else "CRO",
        {
            "VerificationTools": "VerificationTools",
            "CRO": "Evaluating",
        },
    )
    graph.add_edge("VerificationTools", "VerificationAgent")
    graph.add_edge("SearchAgent", "Evaluating")
    graph.add_edge("VerificationAgent", "Evaluating")

    graph.add_conditional_edges(
        "Evaluating",
        lambda state: state.get("next", "CRO"),
        {
            "CRO": "CRO",
            "Replanning": "Replanning",
            "Compiling": "Compiling",
        },
    )
    graph.add_edge("Replanning", "CRO")
    graph.add_edge("Compiling", END)
    graph.add_edge("Failed", END)

    checkpointer = await _get_checkpointer()
    _compiled_graphs[session_id] = graph.compile(checkpointer=checkpointer)
    logger.info("multi_agent_graph_compiled", session_id=session_id)
    return _compiled_graphs[session_id]


def cleanup_session(session_id: str):
    """Clean up per-session in-memory state while preserving persisted checkpoints."""
    guard = _session_guards.get(session_id)
    if guard:
        _session_metric_snapshots[session_id] = guard.metrics()
    _session_guards.pop(session_id, None)
    _session_tool_guards.pop(session_id, None)
    _session_context_managers.pop(session_id, None)
    _session_graphs.pop(session_id, None)
    _compiled_graphs.pop(session_id, None)
    _session_last_accessed.pop(session_id, None)
    clear_failures(session_id)


async def cleanup_stale_sessions(max_age_hours: int = 24):
    """Remove sessions that have been idle past the configured TTL."""
    max_age_seconds = max_age_hours * 3600
    now = time.time()
    stale_ids = [
        session_id
        for session_id, last_accessed in list(_session_last_accessed.items())
        if now - last_accessed > max_age_seconds
    ]
    for session_id in stale_ids:
        cleanup_session(session_id)
    if stale_ids:
        logger.info("stale_sessions_cleaned", count=len(stale_ids))
    return len(stale_ids)
