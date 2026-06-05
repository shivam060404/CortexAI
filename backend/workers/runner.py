"""Async worker process entrypoint with filesystem-based readiness and liveness signals."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.core.job_queue import job_queue
from backend.core.logger import get_logger
from backend.workers.jobs import execute_job

logger = get_logger(__name__)

_shutdown_event = asyncio.Event()


def _build_worker_id() -> str:
    return f"{os.uname().nodename}:{os.getpid()}"


def _touch(path_value: str, content: str) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _remove(path_value: str) -> None:
    path = Path(path_value)
    if path.exists():
        path.unlink()


async def _serve_metrics(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = await reader.readline()
        while True:
            header_line = await reader.readline()
            if not header_line or header_line == b"\r\n":
                break

        if not request_line.startswith(b"GET "):
            body = b"method not allowed\n"
            writer.write(
                b"HTTP/1.1 405 Method Not Allowed\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
                + body
            )
            await writer.drain()
            return

        metrics = await job_queue.queue_metrics()
        body = (
            f"queue_depth_per_pod {metrics['queue_depth_per_pod']}\n"
            f"queue_pending_depth {metrics['pending_depth']}\n"
            f"queue_processing_depth {metrics['processing_depth']}\n"
            f"queue_dead_letter_depth {metrics['dead_letter_depth']}\n"
            f"queue_active_workers {metrics['active_workers']}\n"
            f"queue_desired_replicas {metrics['desired_replicas']}\n"
            f"queue_metric_generated_at {datetime.now(timezone.utc).timestamp()}\n"
        ).encode("utf-8")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
            + body
        )
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def _worker_heartbeat_loop(worker_id: str) -> None:
    while not _shutdown_event.is_set():
        _touch(settings.WORKER_HEARTBEAT_FILE, str(time.time()))
        await job_queue.heartbeat_worker(worker_id)
        await asyncio.sleep(max(1, settings.WORKER_LEASE_RENEW_INTERVAL_SECONDS // 3))


async def _lease_heartbeat(job: dict, worker_id: str) -> None:
    while not _shutdown_event.is_set():
        await asyncio.sleep(settings.WORKER_LEASE_RENEW_INTERVAL_SECONDS)
        await job_queue.renew_lease(job, worker_id=worker_id)


async def run_worker() -> None:
    worker_id = _build_worker_id()
    await job_queue.connect()
    await job_queue.register_worker(worker_id)
    _touch(settings.WORKER_READINESS_FILE, "ready\n")
    _touch(settings.WORKER_HEARTBEAT_FILE, str(time.time()))
    logger.info("worker_ready", queue=settings.WORKER_QUEUE_NAME)
    metrics_server = await asyncio.start_server(
        _serve_metrics,
        settings.WORKER_METRICS_HOST,
        settings.WORKER_METRICS_PORT,
    )
    worker_heartbeat_task = asyncio.create_task(_worker_heartbeat_loop(worker_id))

    try:
        while not _shutdown_event.is_set():
            job = await job_queue.dequeue(
                timeout=settings.WORKER_POLL_TIMEOUT_SECONDS,
                worker_id=worker_id,
            )
            if job is None:
                continue

            lease_task = asyncio.create_task(_lease_heartbeat(job, worker_id))
            try:
                await execute_job(job)
                await job_queue.ack(job)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("worker_job_execution_failed", job_id=job.get("id"), error=str(exc))
                await job_queue.fail(job, str(exc))
            finally:
                lease_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await lease_task
    finally:
        worker_heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_heartbeat_task
        metrics_server.close()
        await metrics_server.wait_closed()
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
