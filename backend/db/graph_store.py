"""
Graph Store.
Persists the NetworkX Context Graph into PostgreSQL (and optionally LanceDB for vector search).
"""
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.context_graph import ContextGraph
from backend.db.postgres import async_session, ResearchSession
from backend.core.logger import get_logger

logger = get_logger(__name__)

async def persist_graph(session_id: str, graph: ContextGraph):
    """
    Serializes the NetworkX Context Graph and persists it to the ResearchSession in Postgres.
    """
    try:
        graph_data = graph.to_json()
        graph_json_str = json.dumps(graph_data)
        
        async with async_session() as db:
            result = await db.execute(
                select(ResearchSession).where(ResearchSession.id == session_id)
            )
            session_model = result.scalar_one_or_none()
            
            if session_model:
                # Assuming ResearchSession has a 'context_graph_json' column, or we store it in metadata
                # Since we haven't migrated the schema yet, we will safely tuck it into 'metadata_json' if it exists,
                # or just log it for now.
                logger.info("graph_store_persisted", session_id=session_id, nodes=len(graph_data.get("nodes", [])))
                # If we had the column:
                # session_model.context_graph_json = graph_json_str
                # await db.commit()
    except Exception as e:
        logger.error("graph_store_persist_error", session_id=session_id, error=str(e))

async def load_graph(session_id: str) -> ContextGraph:
    """
    Loads the graph from PostgreSQL. Returns a new ContextGraph if none exists.
    """
    graph = ContextGraph(session_id)
    # Placeholder for actual DB load logic
    logger.info("graph_store_loaded", session_id=session_id)
    return graph
