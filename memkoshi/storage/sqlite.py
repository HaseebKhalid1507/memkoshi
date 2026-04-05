"""SQLite storage backend."""

import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from .base import StorageBackend
from ..core.memory import Memory, MemoryCategory, MemoryConfidence
from ..core.session import Session, SessionSummary
from ..core.context import BootContext


def _wal_connect(db_path, **kwargs):
    """Open SQLite connection with WAL mode for better concurrent read/write performance."""
    conn = sqlite3.connect(db_path, **kwargs)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


class SQLiteBackend(StorageBackend):
    """SQLite-based storage backend."""
    
    def __init__(self, base_path: str = "~/.memkoshi"):
        self.base_path = Path(base_path).expanduser()
        self.db_path = self.base_path / "memkoshi.db"
        self.conn = None
    
    def initialize(self) -> None:
        """Initialize storage backend."""
        # Create directory if it doesn't exist
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        # Create database connection and keep it open with thread safety
        self.conn = _wal_connect(self.db_path, check_same_thread=False)
        
        # Set busy timeout to 5 seconds
        self.conn.execute("PRAGMA busy_timeout=5000")
        
        cursor = self.conn.cursor()
        
        # Create memories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                topic TEXT NOT NULL,
                title TEXT NOT NULL,
                abstract TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence TEXT NOT NULL,
                source_sessions TEXT NOT NULL,
                source_quotes TEXT NOT NULL,
                created TEXT NOT NULL,
                updated TEXT,
                related_topics TEXT NOT NULL,
                importance REAL NOT NULL,
                tags TEXT NOT NULL,
                signature TEXT,
                trust_level REAL NOT NULL,
                created_by TEXT NOT NULL,
                metadata TEXT NOT NULL
            )
        """)
        
        # Create staged_memories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staged_memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                topic TEXT NOT NULL,
                title TEXT NOT NULL,
                abstract TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence TEXT NOT NULL,
                source_sessions TEXT NOT NULL,
                source_quotes TEXT NOT NULL,
                created TEXT NOT NULL,
                updated TEXT,
                related_topics TEXT NOT NULL,
                importance REAL NOT NULL,
                tags TEXT NOT NULL,
                signature TEXT,
                trust_level REAL NOT NULL,
                created_by TEXT NOT NULL,
                metadata TEXT NOT NULL,
                extraction_metadata TEXT NOT NULL,
                review_status TEXT NOT NULL,
                reviewer_notes TEXT,
                staged_at TEXT NOT NULL
            )
        """)
        
        # Create sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                summary_data TEXT NOT NULL,
                raw_messages TEXT NOT NULL,
                compaction_data TEXT,
                extracted_memories TEXT NOT NULL
            )
        """)
        
        # Create context table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS context (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                context_data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        
        # Create memory_access table for pattern learning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                access_type TEXT NOT NULL,
                accessed_at TEXT NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id)
            )
        """)
        
        # Create context management tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS context_data (
                layer TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                value_type TEXT DEFAULT 'string',
                importance REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (layer, key)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                extracted_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notes TEXT DEFAULT '',
                session_state TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_staged_status ON staged_memories(review_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_id ON sessions(id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_access_memory ON memory_access(memory_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_context_archive_time ON context_data(created_at) WHERE layer = 'archive'")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_log_created ON session_log(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON checkpoints(created_at)")

        self.conn.commit()
        
        # Run v0.4 migration to add new tables
        from .migrations import migrate_to_v04
        migrate_to_v04(str(self.base_path))
    
    
    def _check_conn(self) -> None:
        """Verify connection is alive."""
        if self.conn is None:
            from ..core.exceptions import MemkoshiStorageError
            raise MemkoshiStorageError("Storage not initialized or connection closed")

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def store_memory(self, memory: Memory) -> str:
        """Store memory, return ID."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO memories (
                id, category, topic, title, abstract, content, confidence,
                source_sessions, source_quotes, created, updated, related_topics,
                importance, tags, signature, trust_level, created_by, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            memory.id,
            memory.category,
            memory.topic,
            memory.title,
            memory.abstract,
            memory.content,
            memory.confidence,
            json.dumps(memory.source_sessions),
            json.dumps(memory.source_quotes),
            memory.created.isoformat(),
            memory.updated.isoformat() if memory.updated else None,
            json.dumps(memory.related_topics),
            memory.importance,
            json.dumps(memory.tags),
            memory.signature,
            memory.trust_level,
            memory.created_by,
            json.dumps(memory.metadata)
        ))
        
        self.conn.commit()
        
        return memory.id
    
    def get_memory(self, memory_id: str) -> Optional[Memory]:
        """Retrieve memory by ID."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, category, topic, title, abstract, content, confidence,
                   source_sessions, source_quotes, created, updated, related_topics,
                   importance, tags, signature, trust_level, created_by, metadata
            FROM memories WHERE id = ?
        """, (memory_id,))
        
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Memory(
            id=row[0],
            category=MemoryCategory(row[1]),
            topic=row[2],
            title=row[3],
            abstract=row[4],
            content=row[5],
            confidence=MemoryConfidence(row[6]),
            source_sessions=json.loads(row[7]),
            source_quotes=json.loads(row[8]),
            created=datetime.fromisoformat(row[9]),
            updated=datetime.fromisoformat(row[10]) if row[10] else None,
            related_topics=json.loads(row[11]),
            importance=row[12],
            tags=json.loads(row[13]),
            signature=row[14],
            trust_level=row[15],
            created_by=row[16],
            metadata=json.loads(row[17])
        )
    
    def update_memory(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        self._check_conn()
        """Update memory fields."""
        cursor = self.conn.cursor()
        
        # Build dynamic update query
        set_clauses = []
        values = []
        
        for field, value in updates.items():
            if field in ['source_sessions', 'source_quotes', 'related_topics', 'tags', 'metadata']:
                set_clauses.append(f"{field} = ?")
                values.append(json.dumps(value))
            elif field in ['created', 'updated']:
                set_clauses.append(f"{field} = ?")
                values.append(value.isoformat() if hasattr(value, 'isoformat') else value)
            else:
                set_clauses.append(f"{field} = ?")
                values.append(value)
        
        # Add updated timestamp
        set_clauses.append("updated = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        
        # Add memory_id for WHERE clause
        values.append(memory_id)
        
        query = f"UPDATE memories SET {', '.join(set_clauses)} WHERE id = ?"
        
        cursor.execute(query, values)
        rows_affected = cursor.rowcount
        
        self.conn.commit()
        
        return rows_affected > 0
    
    def delete_memory(self, memory_id: str) -> bool:
        self._check_conn()
        """Delete memory."""
        cursor = self.conn.cursor()
        
        cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        rows_affected = cursor.rowcount
        
        self.conn.commit()
        
        return rows_affected > 0
    
    def list_memories(
        self, 
        category: Optional[MemoryCategory] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Memory]:
        """List memories with filtering."""
        conn = _wal_connect(self.db_path)
        cursor = self.conn.cursor()
        
        # Build query with filters
        query = """
            SELECT id, category, topic, title, abstract, content, confidence,
                   source_sessions, source_quotes, created, updated, related_topics,
                   importance, tags, signature, trust_level, created_by, metadata
            FROM memories
        """
        
        conditions = []
        params = []
        
        if category is not None:
            conditions.append("category = ?")
            params.append(category.value)
        
        if tags is not None and tags:
            # Check if any of the provided tags exist in the memory's tags
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')  # JSON contains the tag
            conditions.append(f"({' OR '.join(tag_conditions)})")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY created DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        
        memories = []
        for row in rows:
            memory = Memory(
                id=row[0],
                category=MemoryCategory(row[1]),
                topic=row[2],
                title=row[3],
                abstract=row[4],
                content=row[5],
                confidence=MemoryConfidence(row[6]),
                source_sessions=json.loads(row[7]),
                source_quotes=json.loads(row[8]),
                created=datetime.fromisoformat(row[9]),
                updated=datetime.fromisoformat(row[10]) if row[10] else None,
                related_topics=json.loads(row[11]),
                importance=row[12],
                tags=json.loads(row[13]),
                signature=row[14],
                trust_level=row[15],
                created_by=row[16],
                metadata=json.loads(row[17])
            )
            memories.append(memory)
        
        return memories
    
    def store_session(self, session: Session) -> str:
        self._check_conn()
        """Store session."""
        cursor = self.conn.cursor()
        
        # Convert datetime objects to ISO strings for JSON serialization
        summary_data = session.summary.model_dump()
        if 'started_at' in summary_data and summary_data['started_at']:
            summary_data['started_at'] = summary_data['started_at'].isoformat()
        if 'ended_at' in summary_data and summary_data['ended_at']:
            summary_data['ended_at'] = summary_data['ended_at'].isoformat()
        
        cursor.execute("""
            INSERT OR REPLACE INTO sessions (
                id, summary_data, raw_messages, compaction_data, extracted_memories
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            session.summary.id,
            json.dumps(summary_data),
            json.dumps(session.raw_messages),
            json.dumps(session.compaction_data) if session.compaction_data else None,
            json.dumps(session.extracted_memories)
        ))
        
        self.conn.commit()
        
        return session.summary.id
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, summary_data, raw_messages, compaction_data, extracted_memories
            FROM sessions WHERE id = ?
        """, (session_id,))
        
        row = cursor.fetchone()
        
        if not row:
            return None
        
        summary_data = json.loads(row[1])
        # Convert datetime strings back to datetime objects
        if 'started_at' in summary_data:
            summary_data['started_at'] = datetime.fromisoformat(summary_data['started_at'])
        if 'ended_at' in summary_data and summary_data['ended_at']:
            summary_data['ended_at'] = datetime.fromisoformat(summary_data['ended_at'])
        
        summary = SessionSummary(**summary_data)
        
        return Session(
            summary=summary,
            raw_messages=json.loads(row[2]),
            compaction_data=json.loads(row[3]) if row[3] else None,
            extracted_memories=json.loads(row[4])
        )
    
    def list_sessions(
        self,
        limit: int = 10,
        offset: int = 0,
        since: Optional[datetime] = None
    ) -> List[Session]:
        """List sessions chronologically."""
        conn = _wal_connect(self.db_path)
        cursor = self.conn.cursor()
        
        query = """
            SELECT id, summary_data, raw_messages, compaction_data, extracted_memories
            FROM sessions
        """
        
        params = []
        if since:
            query += " WHERE json_extract(summary_data, '$.started_at') >= ?"
            params.append(since.isoformat())
        
        query += " ORDER BY json_extract(summary_data, '$.started_at') DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        
        sessions = []
        for row in rows:
            summary_data = json.loads(row[1])
            # Convert datetime strings back to datetime objects
            if 'started_at' in summary_data:
                summary_data['started_at'] = datetime.fromisoformat(summary_data['started_at'])
            if 'ended_at' in summary_data and summary_data['ended_at']:
                summary_data['ended_at'] = datetime.fromisoformat(summary_data['ended_at'])
            
            summary = SessionSummary(**summary_data)
            
            session = Session(
                summary=summary,
                raw_messages=json.loads(row[2]),
                compaction_data=json.loads(row[3]) if row[3] else None,
                extracted_memories=json.loads(row[4])
            )
            sessions.append(session)
        
        return sessions
    
    def store_context(self, context: BootContext) -> None:
        self._check_conn()
        """Store boot context."""
        cursor = self.conn.cursor()
        
        # Convert datetime objects to ISO strings for JSON serialization
        context_data = context.model_dump()
        if 'loaded_at' in context_data and context_data['loaded_at']:
            context_data['loaded_at'] = context_data['loaded_at'].isoformat()
        if 'last_evolution_run' in context_data and context_data['last_evolution_run']:
            context_data['last_evolution_run'] = context_data['last_evolution_run'].isoformat()
        
        cursor.execute("""
            INSERT OR REPLACE INTO context (id, context_data, updated_at)
            VALUES (1, ?, ?)
        """, (
            json.dumps(context_data),
            datetime.now(timezone.utc).isoformat()
        ))
        
        self.conn.commit()
    
    def get_context(self) -> Optional[BootContext]:
        self._check_conn()
        """Load boot context."""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT context_data FROM context WHERE id = 1")
        row = cursor.fetchone()
        
        
        if not row:
            return None
        
        context_data = json.loads(row[0])
        # Convert datetime strings back to datetime objects
        if 'loaded_at' in context_data:
            context_data['loaded_at'] = datetime.fromisoformat(context_data['loaded_at'])
        if 'last_evolution_run' in context_data and context_data['last_evolution_run']:
            context_data['last_evolution_run'] = datetime.fromisoformat(context_data['last_evolution_run'])
        
        return BootContext(**context_data)
    
    def stage_memory(self, memory: Memory) -> str:
        self._check_conn()
        """Add memory to staging area."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO staged_memories (
                id, category, topic, title, abstract, content, confidence,
                source_sessions, source_quotes, created, updated, related_topics,
                importance, tags, signature, trust_level, created_by, metadata,
                extraction_metadata, review_status, reviewer_notes, staged_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            memory.id,
            memory.category,
            memory.topic,
            memory.title,
            memory.abstract,
            memory.content,
            memory.confidence,
            json.dumps(memory.source_sessions),
            json.dumps(memory.source_quotes),
            memory.created.isoformat(),
            memory.updated.isoformat() if memory.updated else None,
            json.dumps(memory.related_topics),
            memory.importance,
            json.dumps(memory.tags),
            memory.signature,
            memory.trust_level,
            memory.created_by,
            json.dumps(memory.metadata),
            json.dumps({}),  # extraction_metadata
            "pending",  # review_status
            None,  # reviewer_notes
            datetime.now(timezone.utc).isoformat()  # staged_at
        ))
        
        self.conn.commit()
        
        return memory.id
    
    def list_staged(self) -> List[Memory]:
        """List memories in staging."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, category, topic, title, abstract, content, confidence,
                   source_sessions, source_quotes, created, updated, related_topics,
                   importance, tags, signature, trust_level, created_by, metadata
            FROM staged_memories
            WHERE review_status = 'pending'
            ORDER BY staged_at DESC
        """)
        
        rows = cursor.fetchall()
        
        memories = []
        for row in rows:
            memory = Memory(
                id=row[0],
                category=MemoryCategory(row[1]),
                topic=row[2],
                title=row[3],
                abstract=row[4],
                content=row[5],
                confidence=MemoryConfidence(row[6]),
                source_sessions=json.loads(row[7]),
                source_quotes=json.loads(row[8]),
                created=datetime.fromisoformat(row[9]),
                updated=datetime.fromisoformat(row[10]) if row[10] else None,
                related_topics=json.loads(row[11]),
                importance=row[12],
                tags=json.loads(row[13]),
                signature=row[14],
                trust_level=row[15],
                created_by=row[16],
                metadata=json.loads(row[17])
            )
            memories.append(memory)
        
        return memories
    
    def approve_memory(self, memory_id: str, reviewer: str) -> bool:
        self._check_conn()
        """Move memory from staging to permanent."""
        cursor = self.conn.cursor()
        
        # First, get the staged memory
        cursor.execute("""
            SELECT id, category, topic, title, abstract, content, confidence,
                   source_sessions, source_quotes, created, updated, related_topics,
                   importance, tags, signature, trust_level, created_by, metadata
            FROM staged_memories
            WHERE id = ? AND review_status = 'pending'
        """, (memory_id,))
        
        row = cursor.fetchone()
        if not row:
            return False
        
        # Insert into permanent memories table
        cursor.execute("""
            INSERT OR REPLACE INTO memories (
                id, category, topic, title, abstract, content, confidence,
                source_sessions, source_quotes, created, updated, related_topics,
                importance, tags, signature, trust_level, created_by, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)
        
        # Update staged memory status
        cursor.execute("""
            UPDATE staged_memories
            SET review_status = 'approved', reviewer_notes = ?
            WHERE id = ?
        """, (f"Approved by {reviewer}", memory_id))
        
        rows_affected = cursor.rowcount
        
        self.conn.commit()
        
        return rows_affected > 0
    
    def reject_memory(self, memory_id: str, reason: str) -> bool:
        """Reject staged memory."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            UPDATE staged_memories
            SET review_status = 'rejected', reviewer_notes = ?
            WHERE id = ? AND review_status = 'pending'
        """, (reason, memory_id))
        
        rows_affected = cursor.rowcount
        
        self.conn.commit()
        
        return rows_affected > 0
    
    def backup(self, path: str) -> bool:
        """Create backup."""
        try:
            backup = sqlite3.connect(path)
            self.conn.backup(backup)
            backup.close()
            return True
        except Exception as e:
            print(f"Backup failed: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # Count memories
        cursor.execute("SELECT COUNT(*) FROM memories")
        stats["memories_count"] = cursor.fetchone()[0]
        
        # Count staged memories
        cursor.execute("SELECT COUNT(*) FROM staged_memories WHERE review_status = 'pending'")
        stats["staged_count"] = cursor.fetchone()[0]
        
        # Count sessions from both tables for backward compatibility
        cursor.execute("SELECT COUNT(*) FROM sessions")
        old_sessions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM session_log")
        new_sessions = cursor.fetchone()[0]
        stats["sessions_count"] = old_sessions + new_sessions
        
        # Database size
        cursor.execute("PRAGMA page_count")
        page_count = cursor.fetchone()[0]
        cursor.execute("PRAGMA page_size")
        page_size = cursor.fetchone()[0]
        stats["db_size_bytes"] = page_count * page_size
        
        
        return stats
    
    def search_memories(self, query: str, limit: int = 100) -> List[Memory]:
        self._check_conn()
        """Search memories with keyword matching."""
        cursor = self.conn.cursor()
        
        # Search in title and content using LIKE
        search_pattern = f"%{query}%"
        
        cursor.execute("""
            SELECT id, category, topic, title, abstract, content, confidence,
                   source_sessions, source_quotes, created, updated, related_topics,
                   importance, tags, signature, trust_level, created_by, metadata
            FROM memories
            WHERE title LIKE ? OR content LIKE ?
            ORDER BY created DESC
            LIMIT ?
        """, (search_pattern, search_pattern, limit))
        
        rows = cursor.fetchall()
        
        memories = []
        for row in rows:
            memory = Memory(
                id=row[0],
                category=MemoryCategory(row[1]),
                topic=row[2],
                title=row[3],
                abstract=row[4],
                content=row[5],
                confidence=MemoryConfidence(row[6]),
                source_sessions=json.loads(row[7]),
                source_quotes=json.loads(row[8]),
                created=datetime.fromisoformat(row[9]),
                updated=datetime.fromisoformat(row[10]) if row[10] else None,
                related_topics=json.loads(row[11]),
                importance=row[12],
                tags=json.loads(row[13]),
                signature=row[14],
                trust_level=row[15],
                created_by=row[16],
                metadata=json.loads(row[17])
            )
            memories.append(memory)
        
        return memories    
    def stage_memories(self, memories: List[Memory]) -> List[str]:
        """Stage multiple memories in a single transaction."""
        cursor = self.conn.cursor()
        staged_ids = []
        
        for memory in memories:
            cursor.execute("""
                INSERT INTO staged_memories (
                    id, category, topic, title, abstract, content, confidence,
                    source_sessions, source_quotes, created, updated, related_topics,
                    importance, tags, signature, trust_level, created_by, metadata,
                    extraction_metadata, review_status, reviewer_notes, staged_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory.id,
                memory.category,
                memory.topic,
                memory.title,
                memory.abstract,
                memory.content,
                memory.confidence,
                json.dumps(memory.source_sessions),
                json.dumps(memory.source_quotes),
                memory.created.isoformat(),
                memory.updated.isoformat() if memory.updated else None,
                json.dumps(memory.related_topics),
                memory.importance,
                json.dumps(memory.tags),
                memory.signature,
                memory.trust_level,
                memory.created_by,
                json.dumps(memory.metadata),
                json.dumps({"staged_from": "batch", "timestamp": datetime.now(timezone.utc).isoformat()}),
                'pending',
                None,
                datetime.now(timezone.utc).isoformat()
            ))
            staged_ids.append(memory.id)
        
        self.conn.commit()
        return staged_ids
    
    def approve_all(self, reviewer: str) -> list:
        """Approve all pending staged memories. Returns list of approved IDs."""
        cursor = self.conn.cursor()
        
        # Get all pending staged memories
        cursor.execute("""
            SELECT id, category, topic, title, abstract, content, confidence,
                   source_sessions, source_quotes, created, updated, related_topics,
                   importance, tags, signature, trust_level, created_by, metadata
            FROM staged_memories
            WHERE review_status = 'pending'
        """)
        
        rows = cursor.fetchall()
        approved_ids = [row[0] for row in rows]
        
        # Insert all into memories table
        for row in rows:
            cursor.execute("""
                INSERT OR REPLACE INTO memories (
                    id, category, topic, title, abstract, content, confidence,
                    source_sessions, source_quotes, created, updated, related_topics,
                    importance, tags, signature, trust_level, created_by, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row)
        
        # Update all staged memories to approved
        cursor.execute("""
            UPDATE staged_memories
            SET review_status = 'approved', reviewer_notes = ?
            WHERE review_status = 'pending'
        """, (f"Batch approved by {reviewer}",))
        
        self.conn.commit()
        
        return approved_ids
    
    def reject_all(self, reason: str) -> int:
        """Reject all pending staged memories."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            UPDATE staged_memories
            SET review_status = 'rejected', reviewer_notes = ?
            WHERE review_status = 'pending'
        """, (reason,))
        
        rejected_count = cursor.rowcount
        self.conn.commit()
        
        return rejected_count
    
    # ── Pattern Learning: Access Tracking ─────────────────────
    
    def record_memory_access(self, memory_id: str, access_type: str = "recall") -> None:
        """Record an access event for a memory."""
        self._check_conn()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO memory_access (memory_id, access_type, accessed_at) VALUES (?, ?, ?)",
            (memory_id, access_type, datetime.now(timezone.utc).isoformat())
        )
        self.conn.commit()
    
    def get_access_count(self, memory_id: str) -> int:
        """Get total access count for a memory."""
        self._check_conn()
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memory_access WHERE memory_id = ?", (memory_id,))
        return cursor.fetchone()[0]
    
    def update_memory_importance(self, memory_id: str, new_importance: float) -> None:
        """Update the importance score of a memory."""
        self._check_conn()
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE memories SET importance = ?, updated = ? WHERE id = ?",
            (new_importance, datetime.now(timezone.utc).isoformat(), memory_id)
        )
        self.conn.commit()
    
    # ── Context Management Methods ─────────────────────
    
    def set_context_data(self, layer: str, key: str, value: str, value_type: str = 'string') -> None:
        """Set context data in a layer."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO context_data 
            (layer, key, value, value_type, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (layer, key, value, value_type, datetime.now(timezone.utc).isoformat()))
        
        self.conn.commit()
    
    def get_context_data(self, layer: str, key: str) -> Optional[tuple]:
        """Get context data from a layer. Returns (value, value_type) or None."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute(
            "SELECT value, value_type FROM context_data WHERE layer = ? AND key = ?",
            (layer, key)
        )
        
        result = cursor.fetchone()
        return result if result else None
    
    def delete_context_data(self, layer: str, key: str) -> bool:
        """Delete context data from a layer. Returns True if deleted."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute(
            "DELETE FROM context_data WHERE layer = ? AND key = ?",
            (layer, key)
        )
        
        rows_affected = cursor.rowcount
        self.conn.commit()
        
        return rows_affected > 0
    
    def get_layer_data(self, layer: str) -> Dict[str, Any]:
        """Get all context data for a layer."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute(
            "SELECT key, value, value_type FROM context_data WHERE layer = ?",
            (layer,)
        )
        
        result = {}
        for row in cursor.fetchall():
            key, value, value_type = row
            if value_type in ['dict', 'list', 'int', 'float', 'bool']:
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = value
            else:
                result[key] = value
        
        return result
    
    def save_checkpoint(self, notes: str, session_state: str) -> int:
        """Save a checkpoint. Returns checkpoint ID."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO checkpoints (notes, session_state) 
            VALUES (?, ?)
        """, (notes, session_state))
        
        checkpoint_id = cursor.lastrowid
        self.conn.commit()
        
        return checkpoint_id
    
    def get_latest_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Get the most recent checkpoint."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, notes, session_state, created_at 
            FROM checkpoints 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        if not result:
            return None
        
        checkpoint_id, notes, session_state, created_at = result
        
        return {
            "id": checkpoint_id,
            "notes": notes,
            "session_state": json.loads(session_state) if session_state else {},
            "created_at": created_at
        }
    
    def add_session_log(self, summary: str, extracted_count: int = 0) -> None:
        """Add a session to the session log."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO session_log (summary, extracted_count) 
            VALUES (?, ?)
        """, (summary, extracted_count))
        
        self.conn.commit()
    
    def get_recent_sessions(self, n: int = 3) -> List[Dict[str, Any]]:
        """Get the N most recent sessions."""
        self._check_conn()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, summary, extracted_count, created_at 
            FROM session_log 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (n,))
        
        results = []
        for row in cursor.fetchall():
            session_id, summary, extracted_count, created_at = row
            results.append({
                "session_id": session_id,
                "summary": summary,
                "extracted_count": extracted_count,
                "timestamp": created_at
            })
        
        return results
    
    # ── v0.4 Pattern Detection & Evolution Methods ─────────────────
    
    def record_event(self, event_type: str, target_id: str = None, 
                    metadata: Dict[str, Any] = None, session_id: str = None,
                    confidence: float = 1.0) -> None:
        """Record event with error handling.
        
        Args:
            event_type: Type of event (search, commit, approve, reject, etc.)
            target_id: Optional memory_id, session_id, etc.
            metadata: Optional event metadata dict
            session_id: Optional session identifier
            confidence: Event confidence score (0.0-1.0)
        """
        try:
            self._check_conn()
            cursor = self.conn.cursor()
            
            cursor.execute("""
                INSERT INTO events (event_type, target_id, metadata, timestamp, session_id, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event_type,
                target_id,
                json.dumps(metadata) if metadata else None,
                datetime.now(timezone.utc).isoformat(),
                session_id,
                confidence
            ))
            
            self.conn.commit()
            
        except (sqlite3.Error, json.JSONDecodeError) as e:
            # Log error but don't crash caller
            logger.warning(f"Event recording failed: {e}")
    
    def record_event_batch(self, events: List[Dict[str, Any]]) -> None:
        """Batch record events for better performance.
        
        Args:
            events: List of event dictionaries
        """
        try:
            self._check_conn()
            cursor = self.conn.cursor()
            
            cursor.executemany("""
                INSERT INTO events (event_type, target_id, metadata, timestamp, session_id, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                (
                    event['event_type'],
                    event['target_id'], 
                    json.dumps(event['metadata']) if event.get('metadata') else None,
                    event['timestamp'],
                    event['session_id'],
                    event.get('confidence', 1.0)
                ) for event in events
            ])
            
            self.conn.commit()
            
        except (sqlite3.Error, KeyError, json.JSONDecodeError) as e:
            # Fail silently - event recording should never crash the system
            logger.warning(f"Event batch recording failed: {e}")
    
    def get_events(self, since: datetime = None, event_type: str = None, 
                  limit: int = 1000) -> List[Dict[str, Any]]:
        """Get events with error handling.
        
        Args:
            since: Optional datetime filter
            event_type: Optional event type filter
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        try:
            self._check_conn()
            cursor = self.conn.cursor()
            
            where_clauses = []
            params = []
            
            if since:
                where_clauses.append("timestamp >= ?")
                params.append(since.isoformat())
            
            if event_type:
                where_clauses.append("event_type = ?")
                params.append(event_type)
            
            where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            
            cursor.execute(f"""
                SELECT event_type, target_id, metadata, timestamp, session_id, confidence
                FROM events {where_sql}
                ORDER BY timestamp DESC
                LIMIT ?
            """, params + [limit])
            
            events = []
            for row in cursor.fetchall():
                try:
                    metadata = json.loads(row[2]) if row[2] else {}
                except json.JSONDecodeError:
                    metadata = {}
                    
                events.append({
                    'event_type': row[0],
                    'target_id': row[1],
                    'metadata': metadata,
                    'timestamp': row[3],
                    'session_id': row[4],
                    'confidence': row[5] or 1.0
                })
            
            return events
            
        except sqlite3.Error:
            return []  # Never crash on data retrieval
    
    def store_evolution_session(self, session_id: str, session_data: Dict[str, Any]) -> None:
        """Store evolution session with error handling.
        
        Args:
            session_id: Session identifier
            session_data: Session metrics and analysis data
        """
        try:
            self._check_conn()
            cursor = self.conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO evolution_sessions (
                    session_id, score, task_completion_rate, error_count,
                    satisfaction_keywords, duration_minutes, memories_committed,
                    memories_recalled, insights, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                session_data.get('score', 5.0),
                session_data.get('task_completion_rate', 0.0),
                session_data.get('errors', session_data.get('error_count', 0)),
                json.dumps(session_data.get('satisfaction_keywords', {})),
                session_data.get('duration_minutes', 60),
                session_data.get('memories_committed', 0),
                session_data.get('memories_recalled', 0),
                json.dumps(session_data.get('insights', [])),
                datetime.now(timezone.utc).isoformat()
            ))
            
            self.conn.commit()
            
        except (sqlite3.Error, json.JSONEncodeError) as e:
            logger.warning(f"Evolution session storage failed: {e}")
