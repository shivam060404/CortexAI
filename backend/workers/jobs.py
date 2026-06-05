"""Queued job definitions and execution helpers for background workers."""

from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage

from backend.core.graph import build_graph
from backend.core.logger import get_logger
from backend.db.tenant import tenant_context

logger = get_logger(__name__)

BACKGROUND_WATCH_JOB = "background_watch"
LOAD_TEST_JOB = "load_test"


def build_background_watch_payload(
    session_id: str,
    user_id: str,
    topic: str,
    *,
    organization_id: str | None = None,
    role: str = "owner",
) -> dict:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "organization_id": organization_id or user_id,
        "role": role,
        "topic": topic,
    }


def build_load_test_payload(
    *,
    session_id: str,
    user_id: str,
    organization_id: str | None = None,
    role: str = "analyst",
    sleep_ms: int = 10,
) -> dict:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "organization_id": organization_id or user_id,
        "role": role,
        "sleep_ms": max(0, int(sleep_ms)),
    }


def build_watch_query(topic: str) -> str:
    return (
        f"BACKGROUND WATCH NOTIFICATION: Produce an update report on '{topic}'. "
        f"Search exclusively for new information, articles, or data. "
        f"Do not restate old background information unless contextually necessary. "
        f"If you find new findings, save them to the workspace as 'watch_update.md' "
        f"and update the Knowledge Graph."
    )


def build_worker_initial_state(session_id: str, query: str) -> dict:
    return {
        "messages": [HumanMessage(content=query)],
        "session_id": session_id,
        "status": "running",
        "supervisor_phase": "RECEIVED",
        "analysis_summary": "",
        "evidence_confidence": 0.0,
        "needs_replan": False,
        "final_output": "",
        "supervisor_events": [],
        "iteration": 0,
        "consecutive_failures": 0,
        "accessed_urls": set(),
        "hitl_mode": "auto",
        "pending_approval": None,
        "user_modifications": [],
        "next": "Received",
        "plan_id": None,
        "plan_version": 0,
        "plan_status": "missing",
        "plan_summary": "",
        "last_worker": None,
    }


async def execute_job(job: dict) -> None:
    job_type = job.get("type")
    payload = job.get("payload", {})

    if job_type == LOAD_TEST_JOB:
        user_id = payload["user_id"]
        organization_id = payload.get("organization_id") or user_id
        role = payload.get("role", "analyst")
        sleep_ms = int(payload.get("sleep_ms", 10) or 0)
        with tenant_context(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            source="worker",
        ):
            logger.info("worker_load_test_started", job_id=job.get("id"), sleep_ms=sleep_ms)
            await asyncio.sleep(sleep_ms / 1000.0)
            logger.info("worker_load_test_completed", job_id=job.get("id"), sleep_ms=sleep_ms)
        return

    if job_type != BACKGROUND_WATCH_JOB:
        logger.warning("worker_job_unknown", job_type=job_type, job_id=job.get("id"))
        return

    session_id = payload["session_id"]
    user_id = payload["user_id"]
    organization_id = payload.get("organization_id") or user_id
    role = payload.get("role", "owner")
    topic = payload["topic"]

    with tenant_context(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        source="worker",
    ):
        logger.info("worker_job_started", job_id=job.get("id"), job_type=job_type, session_id=session_id)
        graph = await build_graph(session_id)
        await graph.ainvoke(
            build_worker_initial_state(session_id, build_watch_query(topic)),
            {"configurable": {"thread_id": session_id}},
        )
        logger.info("worker_job_completed", job_id=job.get("id"), job_type=job_type, session_id=session_id)
