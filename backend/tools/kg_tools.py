"""
Knowledge Graph Tools — interface to store and query the persistent second brain.
Updated to support GraphRAG paradigm (Entity extraction & community summaries).
"""

import json
import uuid
from langchain_core.tools import tool
from sqlalchemy import select
from langchain_community.chat_models import ChatLiteLLM
from langchain_core.messages import SystemMessage, HumanMessage
from backend.db.postgres import async_session, KnowledgeNode, KnowledgeEdge
from backend.db.lancedb_store import LanceDBStore
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


def get_kg_tools(session_id: str):
    """Return GraphRAG Knowledge tools for the agent."""

    @tool
    async def extract_and_store_knowledge(text_content: str, source_name: str) -> str:
        """Extract entities, relationships, and a community summary from text, then store in GraphRAG.
        Use this when you find a dense, highly informative document that should be persisted.
        """
        logger.info("kg_extract", session_id=session_id, source=source_name)
        llm = ChatLiteLLM(
            model=settings.FAST_MODEL,
            temperature=0.1
        )
        
        sys_msg = SystemMessage(content=(
            "You are a GraphRAG extractor. Extract a list of entities, relationships (subject, relation, object), "
            "and a 2-sentence community summary from the text. "
            "Return JSON exactly matching this format: "
            "{\"entities\": [\"entity1\", \"entity2\"], \"triples\": [[\"subject\", \"relation\", \"object\"]], \"summary\": \"summary text\"}"
        ))
        
        try:
            response = await llm.ainvoke([sys_msg, HumanMessage(content=text_content)])
            text = response.content.strip()
            session_uuid = uuid.UUID(str(session_id))
            
            # Clean JSON markdown if present
            if text.startswith("```json"):
                text = text[7:-3]
            elif text.startswith("```"):
                text = text[3:-3]
            
            data = json.loads(text)
            
            # 1. Store summary in LanceDB (Community Summary)
            lancedb_store = LanceDBStore()
            summary_text = data.get("summary", text_content[:500])
            if summary_text:
                lancedb_store.add_documents(
                    session_id=session_id,
                    documents=[summary_text],
                    metadatas=[{"source": source_name, "type": "community_summary"}]
                )
            
            # 2. Store entities and triples in Postgres
            async with async_session() as db:
                for triple in data.get("triples", []):
                    if len(triple) == 3:
                        subj, rel, obj = triple
                        s_id = await _get_or_create_node_id(
                            db,
                            session_uuid=session_uuid,
                            node_name=subj,
                        )
                        o_id = await _get_or_create_node_id(
                            db,
                            session_uuid=session_uuid,
                            node_name=obj,
                        )

                        edge = KnowledgeEdge(session_id=session_uuid, source_id=s_id, target_id=o_id, relation=rel[:255])
                        db.add(edge)
                await db.commit()
                
            return f"Successfully extracted and stored {len(data.get('triples', []))} relationships and community summary."
        except Exception as e:
            logger.error("kg_extract_error", error=str(e))
            return f"Failed to extract knowledge: {str(e)}"

    @tool
    async def query_community_knowledge(query: str) -> str:
        """Query the GraphRAG community summaries to answer broad questions using persistent knowledge."""
        logger.info("kg_query_community", query=query)
        try:
            lancedb_store = LanceDBStore()
            docs = lancedb_store.semantic_search(session_id, query, n_results=3)
            
            if not docs:
                return "No community summaries found for this query."
                
            summaries = "\n".join([f"- {d['content']}" for d in docs])
            return f"GraphRAG Community Summaries relevant to '{query}':\n{summaries}"
        except Exception as e:
            return f"Failed to query GraphRAG: {str(e)}"

    return [extract_and_store_knowledge, query_community_knowledge]


async def _get_or_create_node_id(db, session_uuid: uuid.UUID, node_name: str):
    safe_name = node_name[:255]
    existing = (
        await db.execute(
            select(KnowledgeNode.id).where(
                KnowledgeNode.session_id == session_uuid,
                KnowledgeNode.name == safe_name,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    node = KnowledgeNode(name=safe_name, session_id=session_uuid, node_type="concept")
    db.add(node)
    await db.flush()
    return node.id
