"""Event recording system with background buffering."""

import json
import threading
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EventRecord(BaseModel):
    """Event record data structure."""
    event_type: str = Field(..., min_length=1)
    target_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EventBuffer:
    """Background event buffer to avoid blocking hot path operations."""
    
    def __init__(self, storage, flush_threshold: int = 20, max_buffer_size: int = 10000):
        """Initialize event buffer.
        
        Args:
            storage: Storage backend instance
            flush_threshold: Number of events before background flush
        """
        self.events: List[Dict[str, Any]] = []
        self.storage = storage
        self.flush_threshold = flush_threshold
        self.max_buffer_size = max_buffer_size
        self._lock = threading.Lock()
        self._session_id = None
    
    def set_session_id(self, session_id: str) -> None:
        """Set session ID for subsequent events."""
        with self._lock:
            self._session_id = session_id
    
    def record(self, event_type: str, target_id: Optional[str] = None, 
               metadata: Optional[Dict[str, Any]] = None) -> None:
        """Non-blocking event recording.
        
        Args:
            event_type: Type of event (access, commit, search, approve, reject, session_end)
            target_id: Optional memory_id, session_id, etc.
            metadata: Optional event metadata dict
        """
        try:
            # Create event record
            event_record = EventRecord(
                event_type=event_type,
                target_id=target_id,
                metadata=metadata or {},
                session_id=self._session_id
            )
            
            # Convert to dict for storage - let SQLite handle JSON serialization
            event_dict = {
                'event_type': event_record.event_type,
                'target_id': event_record.target_id,
                'metadata': event_record.metadata,  # Keep as dict, let SQLiteBackend serialize
                'timestamp': event_record.timestamp,
                'session_id': event_record.session_id,
                'confidence': event_record.confidence
            }
            
            with self._lock:
                # Check for buffer overflow and drop old events if needed
                if len(self.events) >= self.max_buffer_size:
                    logger.warning(f"Event buffer full ({self.max_buffer_size}), dropping oldest events")
                    self.events = self.events[-self.flush_threshold:]  # Keep recent ones
                
                self.events.append(event_dict)
                should_flush = len(self.events) >= self.flush_threshold
            
            # Spawn flush outside the lock
            if should_flush:
                self._flush_async()
                    
        except Exception as e:
            # Event recording should never crash the system
            logger.warning(f"Event recording failed: {e}")
    
    def _flush_async(self) -> None:
        """Flush buffer to database in background thread."""
        with self._lock:
            if not self.events:
                return
            events_to_flush = self.events[:]
            self.events.clear()
        
        # Background thread flush (spawn OUTSIDE lock)
        threading.Thread(
            target=self._flush_to_db, 
            args=(events_to_flush,),
            daemon=True
        ).start()
    
    def _flush_to_db(self, events: List[Dict[str, Any]]) -> None:
        """Background database write with error handling.
        
        Args:
            events: List of event dictionaries to write
        """
        try:
            import sqlite3
            # Create thread-local connection (SQLite connections aren't thread-safe)
            conn = sqlite3.connect(str(self.storage.db_path))
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            cursor = conn.cursor()
            cursor.executemany(
                "INSERT INTO events (event_type, target_id, metadata, timestamp, session_id, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                [(e['event_type'], e['target_id'], json.dumps(e.get('metadata')) if e.get('metadata') else None, e['timestamp'], e['session_id'], e.get('confidence', 1.0)) for e in events]
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Event flush failed: {e}")
    
    def flush_sync(self) -> int:
        """Synchronously flush all pending events.
        
        Returns:
            Number of events flushed
        """
        try:
            with self._lock:
                if not self.events:
                    return 0
                
                events_to_flush = self.events[:]
                self.events.clear()
            
            self._flush_to_db(events_to_flush)
            return len(events_to_flush)
            
        except Exception as e:
            logger.warning(f"Sync flush failed: {e}")
            return 0
    
    def pending_count(self) -> int:
        """Get number of pending events in buffer.
        
        Returns:
            Number of events waiting to be flushed
        """
        with self._lock:
            return len(self.events)