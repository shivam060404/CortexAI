from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.worker_scaling import calculate_desired_worker_replicas


def _load_queue_runtime(jobs_requested: int, queue_name: str):
    try:
        job_queue_module = importlib.import_module("backend.core.job_queue")
        jobs_module = importlib.import_module("backend.workers.jobs")
    except ModuleNotFoundError as exc:
        return None, {
            "queue_name": queue_name,
            "jobs_requested": jobs_requested,
            "status": "blocked",
            "error": f"Missing dependency: {exc.name}",
        }

    return (
        {
            "job_queue": job_queue_module.job_queue,
            "load_test_job": jobs_module.LOAD_TEST_JOB,
            "build_load_test_payload": jobs_module.build_load_test_payload,
            "execute_job": jobs_module.execute_job,
        },
        None,
    )


async def _consume_jobs(
    *,
    job_queue,
    execute_job,
    queue_name: str,
    worker_id: str,
    deadline: float,
) -> int:
    processed = 0
    await job_queue.register_worker(worker_id, queue_name=queue_name)
    while time.time() < deadline:
        await job_queue.heartbeat_worker(worker_id, queue_name=queue_name)
        job = await job_queue.dequeue(queue_name=queue_name, timeout=1, worker_id=worker_id)
        if job is None:
            metrics = await job_queue.queue_metrics(queue_name)
            if metrics["pending_depth"] == 0 and metrics["processing_depth"] == 0:
                break
            continue
        try:
            await execute_job(job)
            await job_queue.ack(job, queue_name=queue_name)
            processed += 1
        except Exception as exc:
            await job_queue.fail(job, str(exc), queue_name=queue_name)
    return processed


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=100)
    parser.add_argument("--queue-name", default="cortex:jobs:loadtest")
    parser.add_argument("--current-replicas", type=int, default=2)
    parser.add_argument("--cpu-utilization", type=float, default=None)
    parser.add_argument("--worker-count", type=int, default=2)
    parser.add_argument("--job-duration-ms", type=int, default=25)
    parser.add_argument("--drain-timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    runtime, runtime_error = _load_queue_runtime(args.jobs, args.queue_name)
    if runtime_error is not None:
        scaling = calculate_desired_worker_replicas(
            queue_depth=args.jobs,
            current_replicas=args.current_replicas,
            cpu_utilization_pct=args.cpu_utilization,
        )
        print(
            json.dumps(
                {
                    **runtime_error,
                    "mode": "simulated",
                    "scaling": scaling,
                },
                indent=2,
            )
        )
        return 0

    job_queue = runtime["job_queue"]
    load_test_job = runtime["load_test_job"]
    build_load_test_payload = runtime["build_load_test_payload"]
    execute_job = runtime["execute_job"]

    await job_queue.connect()
    before_metrics = await job_queue.queue_metrics(args.queue_name)

    for index in range(args.jobs):
        await job_queue.enqueue(
            load_test_job,
            build_load_test_payload(
                session_id=str(uuid.uuid4()),
                user_id=f"user-{index}",
                organization_id=f"org-{index % 5}",
                role="analyst",
                sleep_ms=args.job_duration_ms,
            ),
            queue_name=args.queue_name,
        )

    after_enqueue_metrics = await job_queue.queue_metrics(args.queue_name)

    processed_jobs = 0
    drain_completed = False
    if args.worker_count > 0:
        deadline = time.time() + max(1.0, args.drain_timeout_seconds)
        processed_counts = await asyncio.gather(
            *[
                _consume_jobs(
                    job_queue=job_queue,
                    execute_job=execute_job,
                    queue_name=args.queue_name,
                    worker_id=f"loadtest-worker-{index}",
                    deadline=deadline,
                )
                for index in range(args.worker_count)
            ]
        )
        processed_jobs = sum(processed_counts)
        final_metrics = await job_queue.queue_metrics(args.queue_name)
        drain_completed = final_metrics["pending_depth"] == 0 and final_metrics["processing_depth"] == 0
    else:
        final_metrics = after_enqueue_metrics

    await job_queue.close()

    result = {
        "mode": "queue",
        "queue_name": args.queue_name,
        "jobs_enqueued": args.jobs,
        "worker_count": args.worker_count,
        "job_duration_ms": args.job_duration_ms,
        "drain_timeout_seconds": args.drain_timeout_seconds,
        "before_metrics": before_metrics,
        "after_enqueue_metrics": after_enqueue_metrics,
        "final_metrics": final_metrics,
        "processed_jobs": processed_jobs,
        "drain_completed": drain_completed,
        "scaling": calculate_desired_worker_replicas(
            queue_depth=after_enqueue_metrics["pending_depth"],
            current_replicas=args.current_replicas,
            cpu_utilization_pct=args.cpu_utilization,
        ),
    }
    print(json.dumps(result, indent=2))
    enqueue_succeeded = (
        after_enqueue_metrics["pending_depth"] + after_enqueue_metrics["processing_depth"]
        >= before_metrics["pending_depth"] + args.jobs
    )
    if args.worker_count > 0:
        return 0 if enqueue_succeeded and drain_completed and processed_jobs == args.jobs else 1
    return 0 if enqueue_succeeded else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
