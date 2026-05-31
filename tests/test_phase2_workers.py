from __future__ import annotations

import pytest

from backend.core.worker_scaling import calculate_desired_worker_replicas
from backend.db.tenant import get_tenant_context
from backend.workers import jobs as jobs_module


def test_worker_scaling_scales_up_for_queue_pressure():
    result = calculate_desired_worker_replicas(
        queue_depth=37,
        current_replicas=2,
        cpu_utilization_pct=40.0,
        min_replicas=2,
        max_replicas=12,
        target_queue_depth_per_pod=10,
        target_cpu_utilization_pct=70,
    )

    assert result["desired_replicas"] == 4
    assert result["queue_pressure_replicas"] == 4
    assert result["cpu_pressure_replicas"] == 2
    assert result["scale_direction"] == "up"


def test_worker_scaling_scales_down_when_queue_and_cpu_are_low():
    result = calculate_desired_worker_replicas(
        queue_depth=0,
        current_replicas=6,
        cpu_utilization_pct=20.0,
        min_replicas=2,
        max_replicas=12,
        target_queue_depth_per_pod=10,
        target_cpu_utilization_pct=70,
    )

    assert result["desired_replicas"] == 2
    assert result["scale_direction"] == "down"


def test_background_watch_payload_defaults_organization_to_user():
    payload = jobs_module.build_background_watch_payload(
        session_id="session-1",
        user_id="user-1",
        topic="competitive intelligence",
        role="analyst",
    )

    assert payload["organization_id"] == "user-1"
    assert payload["role"] == "analyst"


@pytest.mark.asyncio
async def test_execute_job_propagates_worker_tenant_context(monkeypatch):
    captured: dict = {}

    class DummyGraph:
        async def ainvoke(self, state, config):
            context = get_tenant_context()
            captured["organization_id"] = context.organization_id
            captured["user_id"] = context.user_id
            captured["role"] = context.role
            captured["source"] = context.source
            captured["session_id"] = state["session_id"]
            captured["thread_id"] = config["configurable"]["thread_id"]

    async def fake_build_graph(session_id: str):
        captured["build_graph_session_id"] = session_id
        return DummyGraph()

    monkeypatch.setattr(jobs_module, "build_graph", fake_build_graph)

    await jobs_module.execute_job(
        {
            "id": "job-1",
            "type": jobs_module.BACKGROUND_WATCH_JOB,
            "payload": {
                "session_id": "session-1",
                "user_id": "user-1",
                "organization_id": "org-1",
                "role": "operator",
                "topic": "market signals",
            },
        }
    )

    assert captured == {
        "build_graph_session_id": "session-1",
        "organization_id": "org-1",
        "user_id": "user-1",
        "role": "operator",
        "source": "worker",
        "session_id": "session-1",
        "thread_id": "session-1",
    }
