"""Main Memkoshi API for programmatic access."""

from pathlib import Path
from typing import List, Dict, Any, Optional
from .storage.sqlite import SQLiteBackend
from .core.pipeline import MemoryPipeline
from .core.context import BootContext
from .extractors.hybrid import HybridExtractor
from .search.engine import MemkoshiSearch


class Memkoshi:
    """Main API class for Memkoshi memory system."""
    
    def __init__(self, storage_path: str, extractor: str = "hybrid",
                 provider: str = "anthropic", model: str = None, api_key: str = None):
        """Initialize Memkoshi with a storage path.
        
        Args:
            storage_path: Path to directory for storing all Memkoshi data.
            extractor: Extractor to use — "hybrid" (default, local) or "api" (LLM).
            provider: API provider — "anthropic" or "openai" (only used if extractor="api").
            model: Model override (default: claude-sonnet-4-20250514 / gpt-4o-mini).
            api_key: API key override (default: reads from env var).
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._extractor_name = extractor
        self._provider = provider
        self._model = model
        self._api_key = api_key
        
        # Components will be initialized on init()
        self.storage = None
        self.pipeline = None
        self.search = None
        self._initialized = False
    
    def init(self) -> None:
        """Initialize storage and components."""
        if self._initialized:
            return
            
        # Initialize storage backend (SQLiteBackend expects a directory, not a file path)
        self.storage = SQLiteBackend(str(self.storage_path))
        self.storage.initialize()
        
        # Initialize extractor
        if self._extractor_name == "api":
            from .extractors.api import APIExtractor
            extractor = APIExtractor(
                provider=self._provider,
                model=self._model,
                api_key=self._api_key,
            )
        elif self._extractor_name == "pi":
            from .extractors.pi import PiExtractor
            extractor = PiExtractor(model=self._model)
        else:
            extractor = HybridExtractor()
        extractor.initialize()
        
        # Initialize pipeline
        self.pipeline = MemoryPipeline(self.storage, extractor)
        
        # Initialize search engine - pass the db file path, not directory
        self.search = MemkoshiSearch(str(self.storage_path))
        self.search.initialize()
        
        self._initialized = True
    
    def boot(self) -> Dict[str, Any]:
        """Get boot context with current state.
        
        Returns:
            Dictionary with boot context information.
        """
        self._ensure_initialized()
        
        # Get context from storage
        context = self.storage.get_context()
        
        # Get memory statistics
        stats = self.stats()
        
        # Extract session count from recent sessions
        session_count = 0
        recent_sessions = []
        
        if context and context.recent_sessions:
            session_count = len(context.recent_sessions)
            recent_sessions = context.recent_sessions
        
        # Build boot context
        boot_ctx = {
            "session_count": session_count,
            "memory_count": stats["total_memories"],
            "staged_count": stats["staged_memories"],
            "recent_sessions": recent_sessions,
            "handoff_text": context.handoff if context else None
        }
        
        return boot_ctx
    
    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for memories.
        
        Args:
            query: Search query text.
            limit: Maximum number of results to return.
            
        Returns:
            List of memory dictionaries.
        """
        self._ensure_initialized()
        
        # Use the search engine, fall back to SQL if semantic returns empty
        results = self.search.search(query, limit=limit)
        if not results:
            # Fallback to SQL LIKE search
            sql_results = self.storage.search_memories(query, limit=limit)
            results = [{"id": m.id} for m in sql_results]
        
        # Convert search results to API format
        memories = []
        for result in results:
            # Get the full memory from storage if we only have partial info
            memory_id = result['id']
            full_memory = self.storage.get_memory(memory_id)
            
            if full_memory:
                memories.append({
                    "id": full_memory.id,
                    "category": full_memory.category.value,
                    "topic": full_memory.topic,
                    "title": full_memory.title,
                    "content": full_memory.content,
                    "confidence": full_memory.confidence.value,
                    "created": full_memory.created.isoformat() if full_memory.created else '',
                    "score": result.get('score', 0.0),
                    "source_layers": result.get('source_layers', ''),
                    "rrf_score": result.get('rrf_score', 0),
                    "graph_connections": result.get('graph_connections', []),
                })
            else:
                # Fallback to search result data
                memories.append({
                    "id": result['id'],
                    "category": result.get('category', 'unknown').value if hasattr(result.get('category', 'unknown'), 'value') else result.get('category', 'unknown'),
                    "topic": result.get('topic', ''),
                    "title": result.get('title', ''),
                    "content": result.get('abstract', result.get('text', '')),  # Use abstract as content
                    "confidence": result.get('confidence', 'medium'),
                    "created": result.get('created', ''),
                    "score": result.get('score', 0.0)
                })
            
        return memories
    
    def commit(self, text: str) -> Dict[str, Any]:
        """Process and commit text to memory.
        
        Args:
            text: Text to process for memory extraction.
            
        Returns:
            Pipeline result dictionary with statistics.
        
        Raises:
            ValueError: If text is empty or whitespace only.
        """
        if not text or not text.strip():
            raise ValueError("Cannot commit empty text")
        self._ensure_initialized()
        
        # Process through pipeline
        result = self.pipeline.process(text)
        
        # Always update context to track all sessions
        context = self.storage.get_context()
        if not context:
            context = BootContext()
        
        # Add session summary regardless of whether memories were extracted
        session_summary = f"{text[:100]}... ({result['staged_count']} memories)"
        context.recent_sessions.append(session_summary)
        context.recent_sessions = context.recent_sessions[-3:]  # Keep last 3
        
        # Update staged memories count
        context.staged_memories_count = self.storage.get_stats().get('staged_count', 0)
        
        # Save updated context
        self.storage.store_context(context)
        
        return result
    
    def list_staged(self) -> List[Dict[str, Any]]:
        """List all staged memories pending review.
        
        Returns:
            List of staged memory dictionaries.
        """
        self._ensure_initialized()
        
        staged = self.storage.list_staged()
        return [{
            "id": memory.id,
            "category": memory.category.value,
            "topic": memory.topic,
            "title": memory.title,
            "content": memory.content,
            "confidence": memory.confidence.value,
            "staged_at": getattr(memory, 'staged_at', memory.created).isoformat()
        } for memory in staged]
    
    def approve(self, memory_id: str) -> None:
        """Approve a staged memory.
        
        Args:
            memory_id: ID of the memory to approve.
        """
        self._ensure_initialized()
        
        # Get the staged memory first
        staged_list = self.storage.list_staged()
        staged_memory = None
        for memory in staged_list:
            if memory.id == memory_id:
                staged_memory = memory
                break
                
        if not staged_memory:
            raise ValueError(f"Staged memory {memory_id} not found")
        
        # Approve it (this should move it to permanent storage)
        self.storage.approve_memory(memory_id, "api")
        
        # Get the approved memory and index it
        approved_memory = self.storage.get_memory(memory_id)
        if approved_memory:
            self.search.index_memory(approved_memory)
    
    def reject(self, memory_id: str, reason: str = "") -> None:
        """Reject a staged memory.
        
        Args:
            memory_id: ID of the memory to reject.
            reason: Reason for rejection.
        
        Raises:
            ValueError: If memory_id not found in staging.
        """
        self._ensure_initialized()
        
        # Verify it exists in staging
        staged = self.storage.list_staged()
        if not any(m.id == memory_id for m in staged):
            raise ValueError(f"Staged memory {memory_id} not found")
        
        self.storage.reject_memory(memory_id, reason)
    
    def approve_all(self, reviewer: str = "api") -> int:
        """Approve all staged memories and reindex. Returns count approved."""
        self._ensure_initialized()
        count = self.storage.approve_all(reviewer)
        if count > 0:
            self.search.reindex_all(self.storage)
        return count

    def reject_all(self, reason: str = "") -> int:
        """Reject all staged memories. Returns count rejected."""
        self._ensure_initialized()
        return self.storage.reject_all(reason)

    def stats(self) -> Dict[str, Any]:
        """Get storage statistics.
        
        Returns:
            Dictionary with storage statistics.
        """
        self._ensure_initialized()
        
        stats = self.storage.get_stats()
        
        # Add category breakdown
        all_memories = self.storage.list_memories(limit=1000)
        category_counts = {}
        for memory in all_memories:
            category = memory.category.value
            category_counts[category] = category_counts.get(category, 0) + 1
        
        stats["memory_categories"] = category_counts
        
        # Usage stats from search tracker
        most_accessed = []
        never_accessed_count = 0
        if self.search and hasattr(self.search, 'get_most_accessed'):
            most_accessed = self.search.get_most_accessed(5)
            never_accessed = self.search.get_never_accessed()
            never_accessed_count = len(never_accessed)

        return {
            "total_memories": stats.get("memories_count", 0),
            "staged_memories": stats.get("staged_count", 0),
            "session_count": stats.get("sessions_count", 0),
            "database_size": stats.get("database_size_kb", 0),
            "memory_categories": category_counts,
            "most_accessed": [{"id": m.get("filename", ""), "title": m.get("title", ""), "hits": m.get("search_hits", 0)} for m in most_accessed],
            "never_accessed_count": never_accessed_count,
        }
    
    def close(self) -> None:
        """Clean up resources."""
        if self.storage:
            self.storage.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def _ensure_initialized(self) -> None:
        """Ensure Memkoshi is initialized."""
        if not self._initialized:
            raise RuntimeError("Memkoshi not initialized. Call init() first.")
