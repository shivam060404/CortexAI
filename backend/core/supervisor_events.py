"""Helpers for translating supervisor state updates into client-facing events."""

from __future__ import annotations


SUPERVISOR_STREAM_EVENT_TYPES = {
    "supervisor.plan.created": "plan_created",
    "supervisor.batch.dispatched": "batch_started",
    "worker.task.started": "task_started",
    "worker.task.completed": "task_completed",
    "worker.task.failed": "task_failed",
    "supervisor.replan.created": "replan_created",
    "supervisor.report.finalized": "report_ready",
    "supervisor.workflow.failed": "policy_block",
}


def extract_supervisor_stream_messages(
    output: dict | None,
    *,
    last_phase: str | None,
    sent_event_count: int,
) -> tuple[list[dict], str | None, int]:
    """Convert persisted supervisor state updates into websocket event payloads."""
    if not isinstance(output, dict):
        return [], last_phase, sent_event_count

    messages: list[dict] = []
    phase = output.get("supervisor_phase")
    if phase and phase != last_phase:
        messages.append({"type": "phase_change", "data": {"phase": phase}})
        last_phase = phase

    raw_events = output.get("supervisor_events")
    if not isinstance(raw_events, list):
        return messages, last_phase, sent_event_count

    for event in raw_events[sent_event_count:]:
        if not isinstance(event, dict):
            continue
        internal_event_type = str(event.get("event_type") or "")
        stream_event_type = SUPERVISOR_STREAM_EVENT_TYPES.get(internal_event_type)
        if not stream_event_type:
            continue
        payload = {
            key: value
            for key, value in event.items()
            if key != "event_type"
        }
        payload["event_type"] = internal_event_type
        messages.append({"type": stream_event_type, "data": payload})

    return messages, last_phase, len(raw_events)
