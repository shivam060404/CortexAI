from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
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
            "background_watch_job": jobs_module.BACKGROUND_WATCH_JOB,
            "build_background_watch_payload": jobs_module.build_background_watch_payload,
        },
        None,
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=100)
    parser.add_argument("--queue-name", default="cortex:jobs:loadtest")
    parser.add_argument("--current-replicas", type=int, default=2)
    parser.add_argument("--cpu-utilization", type=float, default=None)
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
    background_watch_job = runtime["background_watch_job"]
    build_background_watch_payload = runtime["build_background_watch_payload"]

    await job_queue.connect()
    before_depth = await job_queue.depth(queue_name=args.queue_name)

    for index in range(args.jobs):
        await job_queue.enqueue(
            background_watch_job,
            build_background_watch_payload(
                session_id=str(uuid.uuid4()),
                user_id=f"user-{index}",
                topic=f"load-test-topic-{index}",
                organization_id=f"org-{index % 5}",
                role="analyst",
            ),
            queue_name=args.queue_name,
        )

    after_depth = await job_queue.depth(queue_name=args.queue_name)
    await job_queue.close()

    result = {
        "mode": "queue",
        "queue_name": args.queue_name,
        "jobs_enqueued": args.jobs,
        "depth_before": before_depth,
        "depth_after": after_depth,
        "scaling": calculate_desired_worker_replicas(
            queue_depth=after_depth,
            current_replicas=args.current_replicas,
            cpu_utilization_pct=args.cpu_utilization,
        ),
    }
    print(json.dumps(result, indent=2))
    return 0 if after_depth >= before_depth + args.jobs else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
