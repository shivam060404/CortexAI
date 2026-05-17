"""
ChromaDB vector store — persistent per-session collections for semantic search.
"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class ChromaStore:
    """Manages ChromaDB collections for research session context retrieval."""

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _collection_name(self, session_id: str) -> str:
        return f"session_{str(session_id).replace('-', '_')}"

    def get_or_create_collection(self, session_id: str):
        return self.client.get_or_create_collection(
            name=self._collection_name(session_id),
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(self, session_id: str, documents: list[str],
                      metadatas: list[dict] | None = None,
                      ids: list[str] | None = None):
        """Add text documents to the session collection."""
        collection = self.get_or_create_collection(session_id)
        if not ids:
            import uuid
            ids = [str(uuid.uuid4()) for _ in documents]
        if not metadatas:
            metadatas = [{}] * len(documents)
        try:
            collection.add(documents=documents, metadatas=metadatas, ids=ids)
            logger.info("chromadb_add", session_id=session_id, doc_count=len(documents))
        except Exception as e:
            logger.error("chromadb_add_error", session_id=session_id, error=str(e))

    def semantic_search(self, session_id: str, query: str, n_results: int = 5) -> list[dict]:
        """Search for semantically similar documents in the session collection."""
        collection = self.get_or_create_collection(session_id)
        try:
            results = collection.query(query_texts=[query], n_results=n_results)
            docs = []
            for i, doc in enumerate(results.get("documents", [[]])[0]):
                meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                dist = results.get("distances", [[]])[0][i] if results.get("distances") else 0
                docs.append({"content": doc, "metadata": meta, "distance": dist})
            return docs
        except Exception as e:
            logger.error("chromadb_search_error", session_id=session_id, error=str(e))
            return []

    def delete_collection(self, session_id: str):
        """Delete a session's collection."""
        try:
            self.client.delete_collection(self._collection_name(session_id))
        except Exception:
            pass
