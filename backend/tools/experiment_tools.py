"""
Experiment Tracking Tools — interface to log experiments.
"""

from langchain_core.tools import tool
from backend.db.postgres import async_session, ExperimentTrack
from backend.core.logger import get_logger

logger = get_logger(__name__)

def get_experiment_tools(session_id: str):
    """Return experiment tracking tools."""

    @tool
    async def log_experiment(hypothesis: str, approach: str, result: str, conclusion: str) -> str:
        """Log a completed experiment or research iteration, including the hypothesis tested, strategy used, results gathered, and final conclusions."""
        logger.info("experiment_log", session_id=session_id)
        try:
            async with async_session() as db:
                track = ExperimentTrack(
                    session_id=session_id,
                    hypothesis=hypothesis,
                    approach=approach,
                    result=result,
                    conclusion=conclusion
                )
                db.add(track)
                await db.commit()
                return "Successfully logged experiment."
        except Exception as e:
            logger.error("experiment_log_error", error=str(e))
            return f"Failed to log experiment: {str(e)}"

    return [log_experiment]
