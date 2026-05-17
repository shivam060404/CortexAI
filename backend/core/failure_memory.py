"""
Failure Memory — per-session tracker of failed tool calls and bad approaches.
Prevents the agent from repeating the same mistakes within a session.
"""

from backend.core.logger import get_logger

logger = get_logger(__name__)

# Per-session failure logs: session_id → list of failure records
_session_failures: dict[str, list[dict]] = {}

MAX_FAILURES_IN_CONTEXT = 10  # max failures injected into prompt


def record_failure(session_id: str, tool_name: str, input_summary: str, error: str):
    """Record a tool failure for a session."""
    if session_id not in _session_failures:
        _session_failures[session_id] = []

    _session_failures[session_id].append({
        "tool": tool_name,
        "input": input_summary[:200],
        "error": error[:300],
    })
    logger.info("failure_recorded", session_id=session_id, tool=tool_name,
                 total_failures=len(_session_failures[session_id]))


def get_failure_context(session_id: str) -> str:
    """Build a prompt-injectable summary of past failures for this session."""
    failures = _session_failures.get(session_id, [])
    if not failures:
        return ""

    recent = failures[-MAX_FAILURES_IN_CONTEXT:]
    lines = []
    for i, f in enumerate(recent, 1):
        lines.append(f"{i}. Tool `{f['tool']}` failed with input '{f['input']}' — Error: {f['error']}")

    return (
        "\n\n### ⚠️ FAILURE MEMORY — Do NOT repeat these approaches ###\n"
        "The following tool calls or approaches already failed in this session. "
        "Do not retry them with the same inputs. Try alternative strategies instead.\n"
        + "\n".join(lines)
    )


def clear_failures(session_id: str):
    """Clear failure memory for a session (called on cleanup)."""
    _session_failures.pop(session_id, None)
