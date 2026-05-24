"""
LanceDB vector store — persistent per-session tables for semantic search.
Replaces ChromaDB for serverless multimodal vector backend.
"""

import os
import lancedb
import pyarrow as pa
from typing import List, Dict, Optional
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class LanceDBStore:
    """Manages LanceDB tables for research session context retrieval."""

    def __init__(self):
        # Ensure persistence directory exists
        db_path = settings.LANCEDB_PERSIST_DIR
        os.makedirs(db_path, exist_ok=True)
        self.db = lancedb.connect(db_path)
        
        # Define schema for the table
        # We need an embedding function. We can use LanceDB's built-in 
        # or we can use litellm for embeddings.
        # Since this is a simple replacement for the previous ChromaStore that used default embeddings,
        # we'll use a basic sentence transformer or litellm.
        # To avoid adding heavy dependencies, let's use the default registry if possible, 
        # but to keep it simple, we'll use a text embedding API if needed.
        # Actually, let's just let LanceDB use the default embedding function if we pass text.

    def _table_name(self, session_id: str) -> str:
        return f"session_{str(session_id).replace('-', '_')}"

    def get_or_create_table(self, session_id: str):
        from lancedb.pydantic import Vector, LanceModel
        from lancedb.embeddings import get_registry
        
        try:
            # Using sentence-transformers as default if available, or just a dummy dimension if we do our own
            # Let's use the default LanceDB text embedding (SentenceTransformers)
            model = get_registry().get("sentence-transformers").create(name="all-MiniLM-L6-v2")
            
            class DocumentModel(LanceModel):
                id: str
                text: str = model.SourceField()
                vector: Vector(model.ndims()) = model.VectorField()
                metadata_json: str # Store metadata as json string for simplicity
            
            table_name = self._table_name(session_id)
            if table_name not in self.db.table_names():
                return self.db.create_table(table_name, schema=DocumentModel)
            else:
                return self.db.open_table(table_name)
        except Exception as e:
            logger.error("lancedb_table_creation_error", error=str(e))
            raise

    def add_documents(self, session_id: str, documents: List[str],
                      metadatas: Optional[List[Dict]] = None,
                      ids: Optional[List[str]] = None):
        """Add text documents to the session table."""
        if not documents:
            return
            
        try:
            table = self.get_or_create_table(session_id)
            if not ids:
                import uuid
                ids = [str(uuid.uuid4()) for _ in documents]
            if not metadatas:
                metadatas = [{}] * len(documents)
                
            import json
            data = []
            for i, doc in enumerate(documents):
                data.append({
                    "id": ids[i],
                    "text": doc,
                    "metadata_json": json.dumps(metadatas[i])
                })
                
            table.add(data)
            logger.info("lancedb_add", session_id=session_id, doc_count=len(documents))
        except Exception as e:
            logger.error("lancedb_add_error", session_id=session_id, error=str(e))

    def semantic_search(self, session_id: str, query: str, n_results: int = 5) -> List[Dict]:
        """Search for semantically similar documents in the session table."""
        try:
            table_name = self._table_name(session_id)
            if table_name not in self.db.table_names():
                return []
                
            table = self.db.open_table(table_name)
            results = table.search(query).limit(n_results).to_list()
            
            import json
            docs = []
            for res in results:
                meta = {}
                try:
                    meta = json.loads(res.get("metadata_json", "{}"))
                except:
                    pass
                
                docs.append({
                    "content": res.get("text", ""),
                    "metadata": meta,
                    "distance": res.get("_distance", 0)
                })
            return docs
        except Exception as e:
            logger.error("lancedb_search_error", session_id=session_id, error=str(e))
            return []

    def delete_collection(self, session_id: str):
        """Delete a session's table."""
        try:
            table_name = self._table_name(session_id)
            if table_name in self.db.table_names():
                self.db.drop_table(table_name)
        except Exception:
            pass
