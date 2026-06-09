"""
OpenTelemetry custom span helpers for CortexAI observability (Pillar 5 / Task 14a).

Wraps Phoenix/OTEL with CortexAI-specific span attributes for:
- Supervisor phases
- Tool calls
- Sub-agent spawns
- Session-level trace correlation
- Cost tracking per session
"""

from __future__ import annotations

from typing import Any, Optional
from contextlib import asynccontextmanager, contextmanager

from backend.core.logger import get_logger

logger = get_logger(__name__)

_tracer = None


def _get_tracer():
    """Lazily obtain the CortexAI tracer from the global OTEL provider."""
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        _tracer = trace.get_tracer("cortexai", "2.0.0")
    except Exception:
        _tracer = None
    return _tracer


@contextmanager
def trace_session(session_id: str, user_id: str | None = None):
    """Create a top-level span for an entire research session."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(
        "cortexai.research_session",
        attributes={
            "cortexai.session_id": session_id,
            "cortexai.user_id": user_id or "anonymous",
        },
    ) as span:
        yield span


@contextmanager
def trace_supervisor_phase(session_id: str, phase: str):
    """Create a span for a supervisor phase (routing, planning, evaluating, etc.)."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(
        f"cortexai.supervisor.{phase.lower()}",
        attributes={
            "cortexai.session_id": session_id,
            "cortexai.phase": phase,
        },
    ) as span:
        yield span


@contextmanager
def trace_tool_call(session_id: str, tool_name: str, **kwargs: Any):
    """Create a span for a tool call."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    attrs = {
        "cortexai.session_id": session_id,
        "cortexai.tool_name": tool_name,
    }
    for k, v in kwargs.items():
        if isinstance(v, (str, int, float, bool)):
            attrs[f"cortexai.tool.{k}"] = v

    with tracer.start_as_current_span(
        f"cortexai.tool.{tool_name}",
        attributes=attrs,
    ) as span:
        yield span


@contextmanager
def trace_subagent(session_id: str, agent_type: str):
    """Create a span for a sub-agent spawn."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(
        f"cortexai.subagent.{agent_type.lower()}",
        attributes={
            "cortexai.session_id": session_id,
            "cortexai.agent_type": agent_type,
        },
    ) as span:
        yield span


def record_session_cost(session_id: str, cost_usd: float, tokens_in: int = 0, tokens_out: int = 0):
    """Record cost data on the current session span."""
    tracer = _get_tracer()
    if tracer is None:
        return

    span = tracer.start_span(
        "cortexai.session.cost",
        attributes={
            "cortexai.session_id": session_id,
            "cortexai.cost_usd": round(cost_usd, 6),
            "cortexai.tokens_input": tokens_in,
            "cortexai.tokens_output": tokens_out,
        },
    )
    span.end()
