"""Background job scheduler that enqueues recurring watch jobs onto Redis."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.core.job_queue import job_queue
from backend.core.logger import get_logger
from backend.workers.jobs import BACKGROUND_WATCH_JOB, build_background_watch_payload

logger = get_logger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()

def start_scheduler():
    """Start the APScheduler engine. Should be called on FastAPI startup."""
    if not scheduler.running:
        scheduler.start()
        logger.info("background_scheduler_started")

async def _enqueue_background_watch(
    session_id: str,
    user_id: str,
    topic: str,
    organization_id: str | None,
    role: str,
):
    """Enqueue a recurring watch job for dedicated worker execution."""
    try:
        await job_queue.connect()
        job = await job_queue.enqueue(
            BACKGROUND_WATCH_JOB,
            build_background_watch_payload(
                session_id=session_id,
                user_id=user_id,
                topic=topic,
                organization_id=organization_id,
                role=role,
            ),
        )
        logger.info(
            "background_watch_enqueued",
            session_id=session_id,
            topic=topic[:50],
            job_id=job["id"],
        )
    except Exception as e:
        logger.error("background_watch_enqueue_failed", session_id=session_id, error=str(e))


def schedule_watch(
    session_id: str,
    user_id: str,
    topic: str,
    frequency_hours: float = 24.0,
    *,
    organization_id: str | None = None,
    role: str = "owner",
):
    """Schedule a recurring queue-backed watch task."""
    job_id = f"watch_{session_id}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        _enqueue_background_watch,
        trigger=IntervalTrigger(hours=frequency_hours),
        id=job_id,
        args=[session_id, user_id, topic, organization_id, role],
        replace_existing=True,
    )

    logger.info(
        "background_watch_scheduled",
        session_id=session_id,
        user_id=user_id,
        frequency_hours=frequency_hours,
    )
    return job_id
