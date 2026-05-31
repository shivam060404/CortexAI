from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.postgres import build_rls_sql
from backend.tools.planning_tools import _normalize_todo_items
from backend.core.graph import decide_next_step
from backend.core.worker_scaling import calculate_desired_worker_replicas
from backend.workers.jobs import build_background_watch_payload


def _measure(fn, *, repeats: int = 5) -> float:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="evals/phase2_baseline.json")
    parser.add_argument("--max-regression-pct", type=float, default=5.0)
    parser.add_argument("--output", default="artifacts/phase2-benchmark.json")
    args = parser.parse_args()

    todos = [{"text": f"Task {index}", "status": "pending"} for index in range(250)]

    results = {
        "build_rls_sql_ms": _measure(build_rls_sql),
        "normalize_todo_items_250_ms": _measure(lambda: _normalize_todo_items(todos)),
        "supervisor_decision_10000_ms": _measure(
            lambda: [
                decide_next_step(plan_version=2, plan_status="in_progress", iteration=i % 5, last_worker="SearchAgent")
                for i in range(10_000)
            ]
        ),
        "worker_payload_build_10000_ms": _measure(
            lambda: [
                build_background_watch_payload(
                    session_id=f"session-{i}",
                    user_id=f"user-{i}",
                    topic="competitive intelligence",
                    organization_id=f"org-{i}",
                    role="analyst",
                )
                for i in range(10_000)
            ]
        ),
        "worker_scaling_10000_ms": _measure(
            lambda: [
                calculate_desired_worker_replicas(
                    queue_depth=i % 250,
                    current_replicas=4,
                    cpu_utilization_pct=float((i % 100) + 1),
                )
                for i in range(10_000)
            ]
        ),
    }

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    regressions = {}
    for key, value in results.items():
        allowed = baseline[key] * (1 + (args.max_regression_pct / 100.0))
        if value > allowed:
            regressions[key] = {
                "actual_ms": value,
                "baseline_ms": baseline[key],
                "allowed_ms": round(allowed, 4),
            }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "baseline": baseline,
                "results": results,
                "max_regression_pct": args.max_regression_pct,
                "regressions": regressions,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(json.dumps({"results": results, "regressions": regressions}, indent=2))
    if regressions:
        print("Performance regression exceeded the allowed threshold.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
