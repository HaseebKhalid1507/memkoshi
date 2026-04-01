"""Search engine for memkoshi with VelociRAG integration."""

import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any

from ..core.memory import Memory, MemoryCategory
from ..storage.sqlite import SQLiteBackend

# Try to import VelociRAG components
try:
    from velocirag.store import VectorStore
    from velocirag.embedder import Embedder
    HAS_VELOCIRAG = True
except ImportError:
    HAS_VELOCIRAG = False
    # Will use SimpleSearch fallback


logger = logging.getLogger(__name__)


class SimpleSearch:
    """Simple SQL LIKE search fallback when VelociRAG is not available."""
    
    def __init__(self, db_path: str):
        """Initialize with path to memkoshi database directory."""
        self.db_path = db_path
        self._storage = None
    
    def initialize(self):
        """Set up storage backend."""
        self._storage = SQLiteBackend(self.db_path)
        self._storage.initialize()
    
    def index_memory(self, memory: Memory):
        """No-op for simple search - memories are already in SQLite."""
        pass
    
    def remove_memory(self, memory_id: str):
        """No-op for simple search."""
        pass
    
    def search(self, query: str, limit: int = 5, category: str = None, 
               recency_bias: bool = True) -> List[Dict[str, Any]]:
        """Search using SQL LIKE matching."""
        if not self._storage:
            raise RuntimeError("SimpleSearch not initialized")
        
        # Get memories from storage
        memories = self._storage.search_memories(query, limit=limit * 2)  # Get extra for filtering
        
        # Filter by category if specified
        if category:
            memories = [m for m in memories if m.category.value.lower() == category.lower()]
        
        # Convert to expected format
        results = []
        for memory in memories[:limit]:
            results.append({
                "id": memory.id,
                "score": 1.0,  # Simple search doesn't have real scores
                "title": memory.title,
                "category": memory.category,
                "abstract": memory.abstract,
            })
        
        return results
    
    def reindex_all(self, storage: SQLiteBackend) -> int:
        """No-op for simple search - return count of memories."""
        memories = storage.list_memories(limit=10000)  # Get all
        return len(memories)


class MemkoshiSearch:
    """Main search engine with VelociRAG integration and SimpleSearch fallback."""
    
    def __init__(self, db_path: str):
        """Initialize with path to memkoshi database directory."""
        self.db_path = db_path
        self._index_path = os.path.join(db_path, "search")
        self._store = None
        self._embedder = None
        self._fallback = None
        self._use_fallback = not HAS_VELOCIRAG
    
    def initialize(self):
        """Set up search engine - VelociRAG or fallback."""
        if self._use_fallback:
            logger.info("VelociRAG not available. Using SimpleSearch fallback.")
            logger.info("Install velocirag for semantic search: pip install velocirag")
            self._fallback = SimpleSearch(self.db_path)
            self._fallback.initialize()
        else:
            # Initialize VelociRAG components
            os.makedirs(self._index_path, exist_ok=True)
            self._store = VectorStore(self._index_path)
            self._embedder = Embedder()
    
    def index_memory(self, memory: Memory):
        """Add memory to search index."""
        if self._use_fallback:
            self._fallback.index_memory(memory)
            return
        
        # Combine title and content for embedding
        text = f"{memory.title}\n\n{memory.content}"
        
        # Generate embedding
        embedding = self._embedder.embed(text)
        
        # Store with metadata
        metadata = {
            "title": memory.title,
            "category": memory.category.value,
            "topic": memory.topic,
            "abstract": memory.abstract,
            "tags": memory.tags,
            "created": memory.created.isoformat() if memory.created else None,
            "confidence": memory.confidence.value if hasattr(memory, 'confidence') else None
        }
        
        self._store.add(memory.id, text, metadata, embedding)
    
    def remove_memory(self, memory_id: str):
        """Remove memory from search index."""
        if self._use_fallback:
            self._fallback.remove_memory(memory_id)
            return
        
        try:
            self._store.remove(memory_id)
        except Exception as e:
            logger.warning(f"Failed to remove memory {memory_id}: {e}")
    
    def search(self, query: str, limit: int = 5, category: str = None,
               recency_bias: bool = True) -> List[Dict[str, Any]]:
        """Search memories with optional filters and scoring adjustments."""
        if self._use_fallback:
            return self._fallback.search(query, limit, category, recency_bias)
        
        # Generate query embedding
        query_embedding = self._embedder.embed(query)
        
        # Search with higher limit to account for filtering
        search_limit = limit * 3 if category else limit * 2
        
        # Perform vector search
        results = self._store.search(query_embedding, limit=search_limit)
        
        # Filter and score
        final_results = []
        now = datetime.now(timezone.utc)
        
        for result in results:
            doc_id = result['doc_id']
            base_score = result.get('similarity', 0.0)
            metadata = result.get('metadata', {})
            # Filter by category if specified
            if category and metadata.get("category", "").lower() != category.lower():
                continue
            
            # Apply recency bias if enabled
            score = base_score
            if recency_bias and metadata.get("created"):
                try:
                    created = datetime.fromisoformat(metadata["created"])
                    days_old = (now - created).days
                    # Boost recent memories: score * (1 + 1/(1 + 0.1*days))
                    score = base_score * (1.0 + 1.0 / (1.0 + days_old * 0.1))
                except:
                    pass  # Keep original score if date parsing fails
            
            # Return search result dict — caller loads full memory from storage
            # Filter out low-relevance results
            if base_score < 0.3:
                continue

            final_results.append({
                "id": doc_id,
                "score": score,
                "title": metadata.get("title", ""),
                "category": metadata.get("category", ""),
                "abstract": metadata.get("abstract", ""),
            })
            
            if len(final_results) >= limit:
                break
        
        return final_results
    
    def reindex_all(self, storage: SQLiteBackend) -> int:
        """Rebuild search index from all permanent memories."""
        if self._use_fallback:
            return self._fallback.reindex_all(storage)
        
        # Clear existing index
        if hasattr(self._store, 'clear'):
            self._store.clear()
        
        # Get all memories
        memories = storage.list_memories(limit=10000)
        
        # Index each memory
        count = 0
        for memory in memories:
            try:
                self.index_memory(memory)
                count += 1
            except Exception as e:
                logger.error(f"Failed to index memory {memory.id}: {e}")
        
        logger.info(f"Reindexed {count} memories")
        return count
