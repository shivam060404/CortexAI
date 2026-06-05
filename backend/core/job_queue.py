"""Redis-backed job queue used by asynchronous worker processes."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from backend.config import settings
from backend.core.logger import get_logger
from backend.core.worker_scaling import calculate_desired_worker_replicas

logger = get_logger(__name__)


class JobQueue:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    @staticmethod
    def _pending_key(queue_name: str) -> str:
        return queue_name

    @staticmethod
    def _processing_key(queue_name: str) -> str:
        return f"{queue_name}:processing"

    @staticmethod
    def _leases_key(queue_name: str) -> str:
        return f"{queue_name}:leases"

    @staticmethod
    def _workers_key(queue_name: str) -> str:
        return f"{queue_name}:workers"

    @staticmethod
    def _dead_letter_key(queue_name: str) -> str:
        return f"{queue_name}:dead_letter"

    @staticmethod
    def _job_key(queue_name: str, job_id: str) -> str:
        return f"{queue_name}:job:{job_id}"

    async def _require_redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("Job queue is not connected")
        return self._redis

    async def _load_job(self, queue_name: str, job_id: str) -> dict[str, Any] | None:
        redis_client = await self._require_redis()
        payload = await redis_client.get(self._job_key(queue_name, job_id))
        return json.loads(payload) if payload else None

    async def _store_job(self, queue_name: str, job: dict[str, Any]) -> None:
        redis_client = await self._require_redis()
        await redis_client.set(self._job_key(queue_name, job["id"]), json.dumps(job))

    async def connect(self) -> None:
        if self._redis is not None:
            return
        self._redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        await self._redis.ping()
        logger.info("job_queue_connected", queue=settings.WORKER_QUEUE_NAME)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None

    async def enqueue(self, job_type: str, payload: dict[str, Any], queue_name: str | None = None) -> dict[str, Any]:
        redis_client = await self._require_redis()
        job = {
            "id": str(uuid.uuid4()),
            "type": job_type,
            "payload": payload,
            "status": "pending",
            "attempts": 0,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        await self._store_job(queue_key, job)
        await redis_client.rpush(self._pending_key(queue_key), job["id"])
        return job

    async def dequeue(
        self,
        timeout: int | None = None,
        queue_name: str | None = None,
        *,
        worker_id: str = "worker",
    ) -> dict[str, Any] | None:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        await self.requeue_expired_jobs(queue_name=queue_key)

        job_id = await redis_client.brpoplpush(
            self._pending_key(queue_key),
            self._processing_key(queue_key),
            timeout=timeout or settings.WORKER_POLL_TIMEOUT_SECONDS,
        )
        if not job_id:
            return None

        job = await self._load_job(queue_key, job_id)
        if job is None:
            await redis_client.lrem(self._processing_key(queue_key), 1, job_id)
            return None

        now = time.time()
        job["attempts"] = int(job.get("attempts", 0) or 0) + 1
        job["status"] = "leased"
        job["worker_id"] = worker_id
        job["leased_at"] = datetime.now(timezone.utc).isoformat()
        job["lease_expires_at"] = now + settings.WORKER_LEASE_SECONDS
        await self._store_job(queue_key, job)
        await redis_client.zadd(self._leases_key(queue_key), {job_id: job["lease_expires_at"]})
        return job

    async def ack(self, job: dict[str, Any], queue_name: str | None = None) -> None:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        job_id = job["id"]
        await redis_client.lrem(self._processing_key(queue_key), 1, job_id)
        await redis_client.zrem(self._leases_key(queue_key), job_id)
        await redis_client.delete(self._job_key(queue_key, job_id))

    async def fail(self, job: dict[str, Any], error: str, queue_name: str | None = None) -> dict[str, Any]:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        job_id = job["id"]
        max_attempts = settings.MAX_RETRIES + 1
        attempts = int(job.get("attempts", 0) or 0)

        job["last_error"] = error[:2000]
        job["failed_at"] = datetime.now(timezone.utc).isoformat()
        job.pop("lease_expires_at", None)
        job.pop("leased_at", None)
        job.pop("worker_id", None)

        await redis_client.lrem(self._processing_key(queue_key), 1, job_id)
        await redis_client.zrem(self._leases_key(queue_key), job_id)

        if attempts < max_attempts:
            job["status"] = "pending"
            job["requeued_at"] = datetime.now(timezone.utc).isoformat()
            await self._store_job(queue_key, job)
            await redis_client.rpush(self._pending_key(queue_key), job_id)
            return job

        job["status"] = "failed"
        await self._store_job(queue_key, job)
        await redis_client.rpush(self._dead_letter_key(queue_key), job_id)
        return job

    async def renew_lease(self, job: dict[str, Any], queue_name: str | None = None, *, worker_id: str = "worker") -> None:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        job_id = job["id"]
        lease_expires_at = time.time() + settings.WORKER_LEASE_SECONDS
        job["worker_id"] = worker_id
        job["lease_expires_at"] = lease_expires_at
        await self._store_job(queue_key, job)
        await redis_client.zadd(self._leases_key(queue_key), {job_id: lease_expires_at})

    async def requeue_expired_jobs(self, queue_name: str | None = None, *, limit: int = 100) -> int:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        expired_job_ids = await redis_client.zrangebyscore(
            self._leases_key(queue_key),
            min="-inf",
            max=time.time(),
            start=0,
            num=limit,
        )
        requeued = 0
        for job_id in expired_job_ids:
            removed = await redis_client.lrem(self._processing_key(queue_key), 1, job_id)
            await redis_client.zrem(self._leases_key(queue_key), job_id)
            if removed <= 0:
                continue
            job = await self._load_job(queue_key, job_id)
            if job is None:
                continue
            job["status"] = "pending"
            job["last_error"] = "Job lease expired before acknowledgement"
            job["requeued_at"] = datetime.now(timezone.utc).isoformat()
            job.pop("lease_expires_at", None)
            job.pop("leased_at", None)
            job.pop("worker_id", None)
            await self._store_job(queue_key, job)
            await redis_client.rpush(self._pending_key(queue_key), job_id)
            requeued += 1
        return requeued

    async def register_worker(self, worker_id: str, queue_name: str | None = None) -> None:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        await redis_client.zadd(self._workers_key(queue_key), {worker_id: time.time()})

    async def heartbeat_worker(self, worker_id: str, queue_name: str | None = None) -> None:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        now = time.time()
        await redis_client.zadd(self._workers_key(queue_key), {worker_id: now})
        await redis_client.zremrangebyscore(
            self._workers_key(queue_key),
            min="-inf",
            max=now - settings.WORKER_HEARTBEAT_TTL_SECONDS,
        )

    async def active_worker_count(self, queue_name: str | None = None) -> int:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        await self.heartbeat_worker("__metrics_probe__", queue_name=queue_key)
        await redis_client.zrem(self._workers_key(queue_key), "__metrics_probe__")
        return int(await redis_client.zcard(self._workers_key(queue_key)))

    async def depth(self, queue_name: str | None = None) -> int:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        return int(await redis_client.llen(self._pending_key(queue_key)))

    async def processing_depth(self, queue_name: str | None = None) -> int:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        return int(await redis_client.llen(self._processing_key(queue_key)))

    async def dead_letter_depth(self, queue_name: str | None = None) -> int:
        redis_client = await self._require_redis()
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        return int(await redis_client.llen(self._dead_letter_key(queue_key)))

    async def queue_metrics(self, queue_name: str | None = None) -> dict[str, Any]:
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        pending_depth = await self.depth(queue_key)
        processing_depth = await self.processing_depth(queue_key)
        dead_letter_depth = await self.dead_letter_depth(queue_key)
        active_workers = await self.active_worker_count(queue_key)
        queue_depth_per_pod = pending_depth / max(1, active_workers)
        scaling = calculate_desired_worker_replicas(
            queue_depth=pending_depth,
            current_replicas=max(1, active_workers),
        )
        return {
            "queue_name": queue_key,
            "pending_depth": pending_depth,
            "processing_depth": processing_depth,
            "dead_letter_depth": dead_letter_depth,
            "active_workers": active_workers,
            "queue_depth_per_pod": round(queue_depth_per_pod, 4),
            "desired_replicas": scaling["desired_replicas"],
            "target_queue_depth_per_pod": scaling["target_queue_depth_per_pod"],
        }


job_queue = JobQueue()
