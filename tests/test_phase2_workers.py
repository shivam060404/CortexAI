from __future__ import annotations

import pytest

from backend.core.job_queue import JobQueue
from backend.core.worker_scaling import calculate_desired_worker_replicas
from backend.db.tenant import get_tenant_context
from backend.workers import jobs as jobs_module


class _FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.values: dict[str, str] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    async def ping(self):
        return True

    async def close(self):
        return None

    async def set(self, key: str, value: str):
        self.values[key] = value

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, key: str):
        self.values.pop(key, None)

    async def rpush(self, key: str, value: str):
        self.lists.setdefault(key, []).append(value)

    async def brpoplpush(self, source: str, destination: str, timeout: int = 0):
        source_list = self.lists.setdefault(source, [])
        if not source_list:
            return None
        value = source_list.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    async def lrem(self, key: str, count: int, value: str):
        items = self.lists.setdefault(key, [])
        removed = 0
        kept: list[str] = []
        for item in items:
            if item == value and (count == 0 or removed < count):
                removed += 1
                continue
            kept.append(item)
        self.lists[key] = kept
        return removed

    async def llen(self, key: str):
        return len(self.lists.setdefault(key, []))

    async def zadd(self, key: str, mapping: dict[str, float]):
        bucket = self.sorted_sets.setdefault(key, {})
        bucket.update(mapping)

    async def zrangebyscore(self, key: str, min="-inf", max="+inf", start: int = 0, num: int | None = None):
        lower = float("-inf") if min == "-inf" else float(min)
        upper = float("inf") if max == "+inf" else float(max)
        bucket = self.sorted_sets.setdefault(key, {})
        values = [member for member, score in sorted(bucket.items(), key=lambda item: item[1]) if lower <= score <= upper]
        sliced = values[start:]
        return sliced if num is None else sliced[:num]

    async def zrem(self, key: str, member: str):
        self.sorted_sets.setdefault(key, {}).pop(member, None)

    async def zremrangebyscore(self, key: str, min="-inf", max="+inf"):
        lower = float("-inf") if min == "-inf" else float(min)
        upper = float("inf") if max == "+inf" else float(max)
        bucket = self.sorted_sets.setdefault(key, {})
        for member, score in list(bucket.items()):
            if lower <= score <= upper:
                bucket.pop(member, None)

    async def zcard(self, key: str):
        return len(self.sorted_sets.setdefault(key, {}))


def _build_queue() -> JobQueue:
    queue = JobQueue()
    queue._redis = _FakeRedis()
    return queue


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
async def test_job_queue_ack_removes_completed_job():
    queue = _build_queue()
    job = await queue.enqueue("load_test", {"value": 1}, queue_name="test:queue")

    leased = await queue.dequeue(queue_name="test:queue", worker_id="worker-1")

    assert leased is not None
    assert leased["id"] == job["id"]
    assert leased["attempts"] == 1
    await queue.ack(leased, queue_name="test:queue")

    assert await queue.depth("test:queue") == 0
    assert await queue.processing_depth("test:queue") == 0


@pytest.mark.asyncio
async def test_job_queue_fail_requeues_before_retry_budget_exhausted(monkeypatch):
    monkeypatch.setattr("backend.core.job_queue.settings.MAX_RETRIES", 1)
    queue = _build_queue()
    await queue.enqueue("load_test", {"value": 1}, queue_name="test:retry")

    leased = await queue.dequeue(queue_name="test:retry", worker_id="worker-1")
    failed = await queue.fail(leased, "boom", queue_name="test:retry")

    assert failed["status"] == "pending"
    assert await queue.depth("test:retry") == 1
    assert await queue.dead_letter_depth("test:retry") == 0

    leased_again = await queue.dequeue(queue_name="test:retry", worker_id="worker-1")
    failed_again = await queue.fail(leased_again, "boom", queue_name="test:retry")

    assert failed_again["status"] == "failed"
    assert await queue.depth("test:retry") == 0
    assert await queue.dead_letter_depth("test:retry") == 1


@pytest.mark.asyncio
async def test_job_queue_requeues_expired_leases():
    queue = _build_queue()
    await queue.enqueue("load_test", {"value": 1}, queue_name="test:leases")
    leased = await queue.dequeue(queue_name="test:leases", worker_id="worker-1")
    leased["lease_expires_at"] = 0
    await queue._store_job("test:leases", leased)
    await queue._redis.zadd(queue._leases_key("test:leases"), {leased["id"]: 0})

    requeued = await queue.requeue_expired_jobs(queue_name="test:leases")

    assert requeued == 1
    assert await queue.depth("test:leases") == 1
    assert await queue.processing_depth("test:leases") == 0


@pytest.mark.asyncio
async def test_job_queue_metrics_include_active_workers_and_queue_depth_per_pod():
    queue = _build_queue()
    await queue.enqueue("load_test", {"value": 1}, queue_name="test:metrics")
    await queue.enqueue("load_test", {"value": 2}, queue_name="test:metrics")
    await queue.register_worker("worker-1", queue_name="test:metrics")
    await queue.register_worker("worker-2", queue_name="test:metrics")

    metrics = await queue.queue_metrics("test:metrics")

    assert metrics["pending_depth"] == 2
    assert metrics["active_workers"] == 2
    assert metrics["queue_depth_per_pod"] == 1.0


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
