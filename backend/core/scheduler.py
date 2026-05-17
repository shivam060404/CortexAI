"""
Background Watcher (Cron Jobs via APScheduler)
Enables continuous, asynchronous research updates on specific topics.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from langchain_core.messages import HumanMessage
from backend.core.logger import get_logger
from backend.core.graph import build_graph

logger = get_logger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()

def start_scheduler():
    """Start the APScheduler engine. Should be called on FastAPI startup."""
    if not scheduler.running:
        scheduler.start()
        logger.info("background_scheduler_started")

async def _run_background_watch(session_id: str, topic: str):
    """
    The actual task executed by the scheduler.
    Spins up the LangGraph agent bound to the session in the background
    to perform an incremental watch search.
    """
    logger.info("background_watch_triggered", session_id=session_id, topic=topic[:50])
    try:
        # Build the graph
        graph = await build_graph(session_id)
        
        # We tell the agent to search for NEW developments.
        query = (
            f"BACKGROUND WATCH NOTIFICATION: Produce an update report on '{topic}'. "
            f"Search exclusively for new information, articles, or data. "
            f"Do not restate old background information unless contextually necessary. "
            f"If you find new findings, save them to the workspace as 'watch_update.md' "
            f"and update the Knowledge Graph."
        )
        
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "session_id": session_id,
            "status": "running",
            "iteration": 0,
            "consecutive_failures": 0,
            "accessed_urls": set()
        }
        
        # Run asynchronously to completion without yielding chunks to a websocket
        await graph.ainvoke(initial_state)
        
        logger.info("background_watch_completed", session_id=session_id)
    except Exception as e:
        logger.error("background_watch_failed", session_id=session_id, error=str(e))

def schedule_watch(session_id: str, topic: str, frequency_hours: float = 24.0):
    """
    Schedule a new background watch task.
    """
    job_id = f"watch_{session_id}"
    
    # Remove existing job if user modifies it
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        
    scheduler.add_job(
        _run_background_watch,
        trigger=IntervalTrigger(hours=frequency_hours),
        id=job_id,
        args=[session_id, topic],
        replace_existing=True
    )
    
    logger.info("background_watch_scheduled", session_id=session_id, frequency_hours=frequency_hours)
    return job_id
