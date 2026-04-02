"""Main Memkoshi API for programmatic access."""

import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from .storage.sqlite import SQLiteBackend
from .core.pipeline import MemoryPipeline
from .core.context import BootContext
from .core.context_manager import ContextManager
from .extractors.hybrid import HybridExtractor
from .search.engine import MemkoshiSearch


class Memkoshi:
    """Main API class for Memkoshi memory system."""
    
    def __init__(self, storage_path: str, extractor: str = "hybrid",
                 provider: str = "anthropic", model: str = None, api_key: str = None,
                 enable_auto_extract: bool = False):
        """Initialize Memkoshi with a storage path.
        
        Args:
            storage_path: Path to directory for storing all Memkoshi data.
            extractor: Extractor to use — "hybrid" (default, local) or "api" (LLM).
            provider: API provider — "anthropic" or "openai" (only used if extractor="api").
            model: Model override (default: claude-sonnet-4-20250514 / gpt-4o-mini).
            api_key: API key override (default: reads from env var).
            enable_auto_extract: If True, auto-extract memories on session end.
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._extractor_name = extractor
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self.enable_auto_extract = enable_auto_extract
        
        # Session management
        self._callbacks = []  # List of (event, callback) tuples
        self._active_session = None
        
        # Components will be initialized on init()
        self.storage = None
        self.pipeline = None
        self.search = None
        self._context_manager = None
        self._pattern_detector = None
        self._evolution_engine = None
        self._event_buffer = None
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
        self.search = MemkoshiSearch(str(self.storage_path), enable_daemon=True)
        self.search.initialize()
        
        self._initialized = True
    
    @property
    def context(self) -> ContextManager:
        """Access to unified context management."""
        if self._context_manager is None:
            self._ensure_initialized()
            self._context_manager = ContextManager(self.storage)
        return self._context_manager
    
    @property
    def patterns(self):
        """Lazy-loaded pattern detector."""
        if self._pattern_detector is None:
            self._ensure_initialized()
            from .core.patterns import PatternDetector
            self._pattern_detector = PatternDetector(self.storage)
        return self._pattern_detector
    
    @property
    def evolve(self):
        """Lazy-loaded evolution engine."""
        if self._evolution_engine is None:
            self._ensure_initialized()
            from .core.evolution import EvolutionEngine
            self._evolution_engine = EvolutionEngine(self.storage)
        return self._evolution_engine
    
    @property
    def _events(self):
        """Lazy-loaded event buffer."""
        if self._event_buffer is None:
            self._ensure_initialized()
            from .core.events import EventBuffer
            self._event_buffer = EventBuffer(self.storage)
        return self._event_buffer
    
    def boot(self) -> Dict[str, Any]:
        """Get boot context with current state.
        
        Returns:
            Dictionary with boot context information.
        """
        self._ensure_initialized()
        
        # Use new context system but maintain backward compatibility
        boot_context = self.context.get_boot()
        
        # Get total session count from storage (not just recent)
        stats = self.stats()
        
        # Map new format to legacy format for backward compatibility
        legacy_format = {
            "session_count": stats.get("session_count", 0),
            "memory_count": boot_context.get("memory_stats", {}).get("total_memories", 0),
            "staged_count": boot_context.get("memory_stats", {}).get("staged_memories", 0),
            "recent_sessions": [s.get("summary", "") for s in boot_context.get("recent_sessions", [])],
            "handoff_text": boot_context.get("handoff", {}).get("task") if boot_context.get("handoff") else None
        }
        
        return legacy_format
    
    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for memories.
        
        Args:
            query: Search query text.
            limit: Maximum number of results to return.
            
        Returns:
            List of memory dictionaries.
        """
        self._ensure_initialized()
        
        # Record search event (non-blocking)
        self._events.record('search', metadata={'query': query, 'limit': limit})
        
        # Use the search engine, fall back to SQL if semantic returns empty
        results = self.search.search(query, limit=limit)
        if not results:
            # Fallback to SQL LIKE search
            sql_results = self.storage.search_memories(query, limit=limit)
            results = [{"id": m.id} for m in sql_results]
        
        # Record search completion event
        self._events.record('search_complete', metadata={'query': query, 'results_count': len(results)})
        
        # Convert search results to API format
        memories = []
        for result in results:
            # Get the full memory from storage if we only have partial info
            memory_id = result['id']
            full_memory = self.storage.get_memory(memory_id)
            
            if full_memory:
                age = self._memory_age_days(full_memory.created)
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
                    "age_days": age,
                    "staleness_caveat": self.staleness_caveat(age),
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
        
        # Record commit event
        self._events.record('commit', metadata={
            'text_length': len(text),
            'extracted_count': result['extracted_count'],
            'staged_count': result['staged_count']
        })
        
        # Track session using new context system
        session_summary = f"{text[:100]}... ({result['staged_count']} memories)"
        self.context.add_session(session_summary, extracted_count=result['extracted_count'])
        
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
        
        # Record approval event
        self._events.record('approve', target_id=memory_id)
        
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
        
        # Record rejection event
        self._events.record('reject', target_id=memory_id, metadata={'reason': reason})
        
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
    
    # ── Session Lifecycle Management ───────────────────────────────
    
    def session(self, description: str = '') -> 'SessionContext':
        """Create a session context manager.
        
        Args:
            description: Optional description for this session
            
        Returns:
            SessionContext that auto-extracts memories on exit
        """
        from .core.session import SessionContext
        if self._active_session is not None:
            raise RuntimeError("Session already active")
        
        session = SessionContext(self, description, self.enable_auto_extract)
        self._active_session = session
        return session
    
    def on(self, event: str, callback) -> None:
        """Register a callback for an event.
        
        Args:
            event: 'session_start', 'session_end', or 'checkpoint'
            callback: Function taking (event, session_data) -> None
        """
        if event not in ['session_start', 'session_end', 'checkpoint']:
            raise ValueError(f"Unknown event: {event}")
        self._callbacks.append((event, callback))
    
    def checkpoint(self) -> Dict[str, Any]:
        """Create a checkpoint and trigger callbacks.
        
        Returns:
            Checkpoint metadata
        """
        if not self._active_session:
            # Use context manager if available
            if self._initialized and self._context_manager is not None:
                return self.context.checkpoint()
            else:
                raise RuntimeError("No active session or context manager")
        
        # Trigger checkpoint callbacks with current session data
        self._trigger_event('checkpoint', self._active_session._get_data())
        
        return {
            'id': f"checkpoint_{int(__import__('time').time())}",
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'session_id': self._active_session.session_id
        }
    
    def _trigger_event(self, event: str, session_data: Dict[str, Any]) -> None:
        """Trigger all callbacks for an event."""
        for event_name, callback in self._callbacks:
            if event_name == event:
                try:
                    callback(event, session_data)
                except Exception as e:
                    # Log error but don't fail the session
                    print(f"Callback error: {e}")

    # ── Feature: Bulk Document Import ──────────────────────────────────
    
    def ingest(self, source: str, chunk_size: int = 2000, overlap: int = 200,
               auto_approve: bool = False) -> Dict[str, Any]:
        """Bulk import a document or text into memory.
        
        Splits large text into overlapping chunks, extracts memories from each,
        deduplicates across chunks, and stages them.
        
        Args:
            source: File path or raw text. If path exists on disk, reads it.
            chunk_size: Max characters per chunk (default 2000).
            overlap: Character overlap between chunks to avoid boundary splits.
            auto_approve: If True, approve all extracted memories immediately.
            
        Returns:
            Dictionary with import statistics.
        """
        self._ensure_initialized()
        
        # Resolve source: file path or raw text
        source_path = Path(source).expanduser()
        if source_path.exists() and source_path.is_file():
            text = source_path.read_text(encoding='utf-8', errors='replace')
            source_name = source_path.name
        else:
            text = source
            source_name = f"text_{len(text)}_chars"
        
        if not text.strip():
            return {"source": source_name, "chunks": 0, "extracted": 0,
                    "staged": 0, "duplicates_skipped": 0}
        
        # Split into chunks
        chunks = self._chunk_text(text, chunk_size, overlap)
        
        total_extracted = 0
        total_staged = 0
        total_dupes = 0
        
        for chunk in chunks:
            result = self.pipeline.process(chunk)
            total_extracted += result["extracted_count"]
            total_staged += result["staged_count"]
            total_dupes += result["extracted_count"] - result["staged_count"]
        
        approved = 0
        if auto_approve and total_staged > 0:
            approved = self.approve_all("bulk_import")
        
        return {
            "source": source_name,
            "chunks": len(chunks),
            "extracted": total_extracted,
            "staged": total_staged,
            "duplicates_skipped": total_dupes,
            "approved": approved,
        }
    
    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """Split text into overlapping chunks at paragraph boundaries."""
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        # Split on double newlines (paragraphs) first
        paragraphs = re.split(r'\n\s*\n', text)
        
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 > chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                # Keep overlap from end of previous chunk
                if overlap > 0 and len(current_chunk) > overlap:
                    current_chunk = current_chunk[-overlap:] + "\n\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para
        
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks
    
    # ── Feature: Staleness Caveats ─────────────────────────────────────
    
    @staticmethod
    def _memory_age_days(created_str) -> int:
        """Calculate days since memory was created."""
        try:
            if isinstance(created_str, datetime):
                created = created_str
            else:
                created = datetime.fromisoformat(str(created_str).replace('Z', '+00:00'))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - created
            return max(0, delta.days)
        except (ValueError, TypeError, AttributeError):
            return -1  # Unknown age
    
    @staticmethod
    def staleness_caveat(age_days: int) -> str:
        """Generate a staleness warning for old memories.
        
        Returns empty string for fresh memories (<=1 day).
        """
        if age_days <= 1:
            return ""
        if age_days <= 7:
            return f"This memory is {age_days} days old. Verify before acting on it."
        if age_days <= 30:
            return (f"This memory is {age_days} days old. Claims about code, prices, "
                    f"or system state may be outdated. Verify against current data.")
        return (f"This memory is {age_days} days old. Treat as historical context only — "
                f"do NOT assert as current fact without verification.")
    
    # ── Feature: Tiered Boot ────────────────────────────────────────
    
    def boot_tiered(self, tier: int = 0, limit: int = 50) -> Dict[str, Any]:
        """Progressive memory loading by importance tiers.
        
        Tier 0 (boot): High-importance memories only (importance >= 0.7)
                       + preferences + cases. Lean and fast.
        Tier 1 (warm): Medium-importance (>= 0.5). Loaded after boot.
        Tier 2 (full): Everything. On-demand only.
        
        Args:
            tier: 0 (critical), 1 (medium), 2 (all)
            limit: Max memories per tier.
            
        Returns:
            Dict with memories, tier info, and stats.
        """
        self._ensure_initialized()
        
        all_memories = self.storage.list_memories(limit=5000)
        
        tier_config = {
            0: {"min_importance": 0.7, "categories": None,  # All cats above threshold
                "priority_categories": ["preferences", "cases"]},  # Always include these
            1: {"min_importance": 0.5, "categories": None, "priority_categories": []},
            2: {"min_importance": 0.0, "categories": None, "priority_categories": []},
        }
        
        config = tier_config.get(tier, tier_config[2])
        min_imp = config["min_importance"]
        priority_cats = config["priority_categories"]
        
        # Filter by importance threshold OR priority category
        filtered = []
        for m in all_memories:
            if m.importance >= min_imp:
                filtered.append(m)
            elif m.category.value in priority_cats:
                filtered.append(m)
        
        # Sort by importance descending, then recency
        filtered.sort(key=lambda m: (m.importance, m.created.isoformat() if m.created else ''), reverse=True)
        
        # Apply limit
        tier_memories = filtered[:limit]
        
        # Add staleness info
        results = []
        for m in tier_memories:
            age = self._memory_age_days(m.created)
            results.append({
                "id": m.id,
                "category": m.category.value,
                "topic": m.topic,
                "title": m.title,
                "content": m.content,
                "importance": m.importance,
                "confidence": m.confidence.value,
                "age_days": age,
                "staleness_caveat": self.staleness_caveat(age),
            })
        
        return {
            "tier": tier,
            "memories": results,
            "count": len(results),
            "total_available": len(all_memories),
            "filtered_by_importance": f">={min_imp}",
            "has_more": len(filtered) > limit,
        }
    
    # ── Feature: Pattern Learning ───────────────────────────────────
    
    def record_access(self, memory_id: str, access_type: str = "recall") -> None:
        """Record that a memory was accessed. Feeds the learning loop.
        
        Args:
            memory_id: The memory that was accessed.
            access_type: Type of access — 'recall', 'cited', 'acted_on'.
        """
        self._ensure_initialized()
        self.storage.record_memory_access(memory_id, access_type)
    
    def decay_and_boost(self) -> Dict[str, Any]:
        """Run the pattern learning cycle.
        
        Boosts importance of frequently accessed memories.
        Decays importance of memories that are never accessed.
        Should be called periodically (e.g., weekly maintenance).
        
        Returns:
            Statistics about what changed.
        """
        self._ensure_initialized()
        
        all_memories = self.storage.list_memories(limit=5000)
        boosted = 0
        decayed = 0
        unchanged = 0
        
        for memory in all_memories:
            access_count = self.storage.get_access_count(memory.id)
            age_days = self._memory_age_days(memory.created)
            
            old_importance = memory.importance
            new_importance = old_importance
            
            # Boost: accessed memories get more important
            if access_count > 0:
                # Logarithmic boost — diminishing returns
                import math
                boost = min(0.2, 0.05 * math.log2(access_count + 1))
                new_importance = min(1.0, old_importance + boost)
            
            # Decay: old, never-accessed memories lose importance
            elif age_days > 14 and access_count == 0:
                # Slow linear decay: -0.02 per week past 2 weeks
                weeks_stale = max(0, (age_days - 14)) / 7
                decay = min(0.3, 0.02 * weeks_stale)  # Cap at -0.3
                new_importance = max(0.1, old_importance - decay)
            
            # Apply if changed
            if abs(new_importance - old_importance) > 0.01:
                self.storage.update_memory_importance(memory.id, round(new_importance, 3))
                if new_importance > old_importance:
                    boosted += 1
                else:
                    decayed += 1
            else:
                unchanged += 1
        
        return {
            "total_processed": len(all_memories),
            "boosted": boosted,
            "decayed": decayed,
            "unchanged": unchanged,
        }
    
    # ── Daemon Control ────────────────────────────────────────
    
    def start_daemon(self) -> bool:
        """Start search daemon explicitly. Returns success status."""
        self._ensure_initialized()
        if hasattr(self.search, '_daemon_client') and self.search._daemon_client:
            try:
                return self.search._daemon_client.is_running() or self.search._daemon_client._start_daemon()
            except Exception:
                return False
        return False
    
    def stop_daemon(self) -> bool:
        """Stop search daemon if running."""
        try:
            import socket
            import os
            from .daemon.protocol import send_message, recv_message
            
            socket_path = os.environ.get('MEMKOSHI_SOCKET', f"/tmp/memkoshi-search-{os.getuid()}.sock")
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(socket_path)
            
            send_message(sock, {"cmd": "shutdown"})
            response = recv_message(sock)
            sock.close()
            
            return response["status"] == "success"
        except:
            return False
    
    def daemon_status(self) -> Dict[str, Any]:
        """Get daemon status and health info."""
        try:
            import socket
            import os
            from .daemon.protocol import send_message, recv_message
            
            socket_path = os.environ.get('MEMKOSHI_SOCKET', f"/tmp/memkoshi-search-{os.getuid()}.sock")
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(socket_path)
            
            send_message(sock, {"cmd": "health"})
            response = recv_message(sock)
            sock.close()
            
            if response["status"] == "success":
                return {"status": "running", "health": response["data"]}
            else:
                return {"status": "error", "error": response["error"]}
        except:
            return {"status": "not_running"}
    
    # ── Lifecycle ────────────────────────────────────────────
    
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
