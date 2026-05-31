"""Redis-backed job queue used by asynchronous worker processes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class JobQueue:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

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
        if self._redis is None:
            raise RuntimeError("Job queue is not connected")

        job = {
            "id": str(uuid.uuid4()),
            "type": job_type,
            "payload": payload,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        await self._redis.rpush(queue_key, json.dumps(job))
        return job

    async def dequeue(self, timeout: int | None = None, queue_name: str | None = None) -> dict[str, Any] | None:
        if self._redis is None:
            raise RuntimeError("Job queue is not connected")

        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        result = await self._redis.blpop(queue_key, timeout=timeout or settings.WORKER_POLL_TIMEOUT_SECONDS)
        if not result:
            return None

        _, serialized_job = result
        return json.loads(serialized_job)

    async def depth(self, queue_name: str | None = None) -> int:
        if self._redis is None:
            raise RuntimeError("Job queue is not connected")
        queue_key = queue_name or settings.WORKER_QUEUE_NAME
        return int(await self._redis.llen(queue_key))


job_queue = JobQueue()
