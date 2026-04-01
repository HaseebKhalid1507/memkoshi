"""SQLite storage backend."""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

from .base import StorageBackend
from ..core.memory import Memory, MemoryCategory, MemoryConfidence
from ..core.session import Session, SessionSummary
from ..core.context import BootContext


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
        
        # Create database connection and keep it open
        self.conn = sqlite3.connect(self.db_path)
        
        # Enable WAL mode for better concurrency
        self.conn.execute("PRAGMA journal_mode=WAL")
        
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
        
        
        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_staged_status ON staged_memories(review_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_id ON sessions(id)")

        self.conn.commit()
    
    
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
        conn = sqlite3.connect(self.db_path)
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
        conn = sqlite3.connect(self.db_path)
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
        
        # Count sessions
        cursor.execute("SELECT COUNT(*) FROM sessions")
        stats["sessions_count"] = cursor.fetchone()[0]
        
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
    
    def approve_all(self, reviewer: str) -> int:
        """Approve all pending staged memories."""
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
        
        approved_count = cursor.rowcount
        self.conn.commit()
        
        return approved_count
    
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
