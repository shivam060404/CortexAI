"""Worker autoscaling helpers used by load tests and readiness reporting."""

from __future__ import annotations

import math
from typing import Any

from backend.config import settings


def calculate_desired_worker_replicas(
    *,
    queue_depth: int,
    current_replicas: int,
    cpu_utilization_pct: float | None = None,
    min_replicas: int | None = None,
    max_replicas: int | None = None,
    target_queue_depth_per_pod: int | None = None,
    target_cpu_utilization_pct: int | None = None,
) -> dict[str, Any]:
    """Calculate the bounded worker replica target from queue and CPU pressure."""
    min_replicas = max(1, int(min_replicas or settings.WORKER_MIN_REPLICAS))
    max_replicas = max(min_replicas, int(max_replicas or settings.WORKER_MAX_REPLICAS))
    current_replicas = max(1, int(current_replicas or min_replicas))
    queue_depth = max(0, int(queue_depth or 0))
    target_queue_depth_per_pod = max(1, int(target_queue_depth_per_pod or settings.WORKER_TARGET_QUEUE_DEPTH_PER_POD))
    target_cpu_utilization_pct = max(1, int(target_cpu_utilization_pct or settings.WORKER_TARGET_CPU_UTILIZATION_PCT))

    queue_pressure_replicas = max(min_replicas, math.ceil(queue_depth / target_queue_depth_per_pod))

    cpu_pressure_replicas = min_replicas
    normalized_cpu_utilization = None
    if cpu_utilization_pct is not None:
        normalized_cpu_utilization = max(0.0, float(cpu_utilization_pct))
        cpu_pressure_replicas = max(
            min_replicas,
            math.ceil((current_replicas * normalized_cpu_utilization) / target_cpu_utilization_pct),
        )

    unbounded_desired = max(queue_pressure_replicas, cpu_pressure_replicas)
    desired_replicas = max(min_replicas, min(max_replicas, unbounded_desired))

    scale_direction = "steady"
    if desired_replicas > current_replicas:
        scale_direction = "up"
    elif desired_replicas < current_replicas:
        scale_direction = "down"

    bounded_by: str | None = None
    if desired_replicas == min_replicas and unbounded_desired < min_replicas:
        bounded_by = "min_replicas"
    elif desired_replicas == max_replicas and unbounded_desired > max_replicas:
        bounded_by = "max_replicas"

    return {
        "queue_depth": queue_depth,
        "current_replicas": current_replicas,
        "desired_replicas": desired_replicas,
        "scale_direction": scale_direction,
        "queue_pressure_replicas": queue_pressure_replicas,
        "cpu_pressure_replicas": cpu_pressure_replicas,
        "target_queue_depth_per_pod": target_queue_depth_per_pod,
        "target_cpu_utilization_pct": target_cpu_utilization_pct,
        "cpu_utilization_pct": normalized_cpu_utilization,
        "bounded_by": bounded_by,
    }
