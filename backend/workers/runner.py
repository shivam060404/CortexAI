"""Async worker process entrypoint with filesystem-based readiness and liveness signals."""

from __future__ import annotations

import asyncio
import signal
import time
from pathlib import Path

from backend.config import settings
from backend.core.job_queue import job_queue
from backend.core.logger import get_logger
from backend.workers.jobs import execute_job

logger = get_logger(__name__)

_shutdown_event = asyncio.Event()


def _touch(path_value: str, content: str) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _remove(path_value: str) -> None:
    path = Path(path_value)
    if path.exists():
        path.unlink()


async def run_worker() -> None:
    await job_queue.connect()
    _touch(settings.WORKER_READINESS_FILE, "ready\n")
    _touch(settings.WORKER_HEARTBEAT_FILE, str(time.time()))
    logger.info("worker_ready", queue=settings.WORKER_QUEUE_NAME)

    try:
        while not _shutdown_event.is_set():
            _touch(settings.WORKER_HEARTBEAT_FILE, str(time.time()))
            job = await job_queue.dequeue(timeout=settings.WORKER_POLL_TIMEOUT_SECONDS)
            if job is None:
                continue

            try:
                await execute_job(job)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("worker_job_execution_failed", job_id=job.get("id"), error=str(exc))
    finally:
        _remove(settings.WORKER_READINESS_FILE)
        _remove(settings.WORKER_HEARTBEAT_FILE)
        await job_queue.close()
        logger.info("worker_stopped")


def _request_shutdown() -> None:
    _shutdown_event.set()


async def main() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)
    await run_worker()


if __name__ == "__main__":
    asyncio.run(main())
