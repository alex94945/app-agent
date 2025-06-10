import logging
from typing import List, Dict, Any, Optional
import hashlib

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from langchain_chroma import Chroma
from langchain.storage import LocalFileStore
from langchain.embeddings import CacheBackedEmbeddings

from common.embeddings import get_embedding_model
from common.config import settings

logger = logging.getLogger(__name__)


class VectorStoreAdapter:
    """Adapter to manage the vector store and embeddings cache."""

    def __init__(self):
        # 1. Setup a cache for embeddings
        # This avoids re-calculating embeddings for the same text.
        fs_store = LocalFileStore(settings.EMBEDDING_CACHE_PATH)
        
        # 2. Get the underlying embedding model
        underlying_embedder = get_embedding_model()

        # 3. Create the cached embedder
        self.cached_embedder = CacheBackedEmbeddings.from_bytes_store(
            underlying_embedder,
            fs_store,
            namespace=underlying_embedder.model # Separate cache per model
        )

        # 4. Initialize the Chroma vector store
        # This will persist the vector store to disk at the specified path.
        self.vector_store = Chroma(
            persist_directory=settings.VECTOR_STORE_PATH,
            embedding_function=self.cached_embedder
        )
        logger.info(f"Vector store initialized at: {settings.VECTOR_STORE_PATH}")

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None) -> List[str]:
        """Add texts to the vector store."""
        logger.info(f"Adding {len(texts)} texts to the vector store.")
        return self.vector_store.add_texts(texts=texts, metadatas=metadatas)

    def search(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
        """Perform a similarity search."""
        logger.info(f"Performing vector search for query: '{query}' with k={k}")
        results = self.vector_store.similarity_search_with_score(query=query, k=k)
        
        # Format results as a list of dictionaries
        formatted_results = [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": score
            }
            for doc, score in results
        ]
        return formatted_results

# --- Singleton instance of the adapter ---
# This ensures we have one instance managing the vector store across the app.
try:
    vector_store_adapter = VectorStoreAdapter()
except Exception as e:
    logger.error(f"Failed to initialize VectorStoreAdapter: {e}", exc_info=True)
    vector_store_adapter = None

# --- Pydantic Schema for Tool Input ---

class VectorSearchInput(BaseModel):
    query: str = Field(description="The query to search for in the vector store.")
    k: int = Field(default=3, description="The number of results to return.")

# --- Tool Implementation ---

@tool(args_schema=VectorSearchInput)
async def vector_search(query: str, k: int = 3) -> List[Dict[str, Any]]:
    """
    Searches for relevant information in the vector store.
    Useful for finding code snippets, documentation, or other text-based information.
    """
    if not vector_store_adapter:
        return [{"error": "VectorStoreAdapter is not initialized."}]
    
    try:
        return vector_store_adapter.search(query=query, k=k)
    except Exception as e:
        logger.error(f"Error during vector search for query '{query}': {e}", exc_info=True)
        return [{"error": f"An unexpected error occurred: {e}"}]
