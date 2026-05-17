"""
Knowledge Graph Tools — interface to store and query the persistent second brain.
"""

from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.db.postgres import async_session, KnowledgeNode, KnowledgeEdge
from backend.core.logger import get_logger

logger = get_logger(__name__)


def get_kg_tools(session_id: str):
    """Return Knowledge Graph tools for the agent."""

    @tool
    async def add_to_knowledge_graph(subject: str, relation: str, object_concept: str, scope: str = "session") -> str:
        """Store a factual relationship in the Knowledge Graph. Use this to persist key findings. Set scope="global" if the fact is a universal truth that should survive even if the current session is deleted."""
        logger.info("kg_add", subject=subject, relation=relation, object=object_concept, scope=scope)
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            async with async_session() as db:
                db_session_id = None if scope.lower() == "global" else session_id
                
                # Upsert subject node (race-condition safe)
                stmt_subj = (
                    pg_insert(KnowledgeNode)
                    .values(name=subject, session_id=db_session_id, node_type="concept")
                    .on_conflict_do_nothing(index_elements=["name"])
                    .returning(KnowledgeNode.id)
                )
                res_subj = await db.execute(stmt_subj)
                subj_row = res_subj.first()
                if subj_row:
                    subj_id = subj_row[0]
                else:
                    # Already exists — fetch the ID
                    existing = await db.execute(select(KnowledgeNode.id).where(KnowledgeNode.name == subject))
                    subj_id = existing.scalar_one()

                # Upsert object node (race-condition safe)
                stmt_obj = (
                    pg_insert(KnowledgeNode)
                    .values(name=object_concept, session_id=db_session_id, node_type="concept")
                    .on_conflict_do_nothing(index_elements=["name"])
                    .returning(KnowledgeNode.id)
                )
                res_obj = await db.execute(stmt_obj)
                obj_row = res_obj.first()
                if obj_row:
                    obj_id = obj_row[0]
                else:
                    existing = await db.execute(select(KnowledgeNode.id).where(KnowledgeNode.name == object_concept))
                    obj_id = existing.scalar_one()

                # Create edge
                edge = KnowledgeEdge(
                    session_id=db_session_id,
                    source_id=subj_id,
                    target_id=obj_id,
                    relation=relation
                )
                db.add(edge)
                await db.commit()
                return f"Successfully recorded: ({subject}) -[{relation}]-> ({object_concept})"
        except Exception as e:
            logger.error("kg_add_error", error=str(e))
            return f"Failed to add to Knowledge Graph: {str(e)}"

    @tool
    async def query_knowledge_graph(concept: str) -> str:
        """Query the persistent Knowledge Graph for past findings related to a specific concept or paper. Returns both session-scoped and global knowledge."""
        logger.info("kg_query", concept=concept)
        try:
            async with async_session() as db:
                stmt = select(KnowledgeNode).where(KnowledgeNode.name.ilike(f"%{concept}%")).limit(5)
                res = await db.execute(stmt)
                nodes = res.scalars().all()
                
                if not nodes:
                    return f"No knowledge found for concept '{concept}'."

                node_ids = [n.id for n in nodes]
                node_names = {n.id: n.name for n in nodes}
                results = []

                # Outgoing edges: node -> target (single JOIN query instead of N+1)
                TargetNode = KnowledgeNode.__table__.alias("target_node")
                out_stmt = (
                    select(KnowledgeEdge.source_id, KnowledgeEdge.relation, TargetNode.c.name)
                    .join(TargetNode, KnowledgeEdge.target_id == TargetNode.c.id)
                    .where(KnowledgeEdge.source_id.in_(node_ids))
                    .limit(50)
                )
                out_res = await db.execute(out_stmt)
                for source_id, relation, target_name in out_res.all():
                    results.append(f"({node_names[source_id]}) -[{relation}]-> ({target_name})")

                # Incoming edges: source -> node (single JOIN query instead of N+1)
                SourceNode = KnowledgeNode.__table__.alias("source_node")
                in_stmt = (
                    select(SourceNode.c.name, KnowledgeEdge.relation, KnowledgeEdge.target_id)
                    .join(SourceNode, KnowledgeEdge.source_id == SourceNode.c.id)
                    .where(KnowledgeEdge.target_id.in_(node_ids))
                    .limit(50)
                )
                in_res = await db.execute(in_stmt)
                for source_name, relation, target_id in in_res.all():
                    results.append(f"({source_name}) -[{relation}]-> ({node_names[target_id]})")

                if results:
                    return "Knowledge Graph Findings:\n" + "\n".join(list(set(results)))
                return f"Concept '{concept}' exists but has no relationships recorded."
                
        except Exception as e:
            logger.error("kg_query_error", error=str(e))
            return f"Failed to query Knowledge Graph: {str(e)}"

    return [add_to_knowledge_graph, query_knowledge_graph]
