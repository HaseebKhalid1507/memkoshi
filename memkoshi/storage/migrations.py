"""Database migrations for Memkoshi schema updates."""

import sqlite3
from pathlib import Path


def migrate_to_v04(storage_path: str) -> bool:
    """Add v0.4 tables to existing database. Idempotent.
    
    Args:
        storage_path: Path to storage directory containing memkoshi.db
        
    Returns:
        True if migration completed successfully
    """
    try:
        db_path = Path(storage_path) / "memkoshi.db"
        if not db_path.exists():
            # Database doesn't exist yet, tables will be created during initialization
            return True
        
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        
        try:
            cursor = conn.cursor()
            
            # Check if already migrated
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
            if cursor.fetchone():
                return True  # Already migrated
            
            # Add v0.4 tables (existing data untouched)
            cursor.executescript("""
                -- Event tracking (background buffered)
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    event_type TEXT NOT NULL,
                    target_id TEXT,
                    metadata TEXT,
                    timestamp TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0
                );
                
                -- Pattern storage
                CREATE TABLE patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    trigger_condition TEXT,
                    confidence REAL NOT NULL,
                    sample_size INTEGER DEFAULT 1,
                    last_triggered TEXT,
                    created_at TEXT NOT NULL
                );
                
                -- Session scoring
                CREATE TABLE evolution_sessions (
                    session_id TEXT PRIMARY KEY,
                    score REAL NOT NULL,
                    task_completion_rate REAL,
                    error_count INTEGER DEFAULT 0,
                    satisfaction_keywords TEXT,
                    duration_minutes INTEGER,
                    memories_committed INTEGER DEFAULT 0,
                    memories_recalled INTEGER DEFAULT 0,
                    insights TEXT,
                    created_at TEXT NOT NULL
                );
                
                -- Performance indexes
                CREATE INDEX idx_events_type_time ON events(event_type, timestamp);
                CREATE INDEX idx_events_session ON events(session_id);
                CREATE INDEX idx_patterns_type ON patterns(pattern_type);
                CREATE INDEX idx_evolution_created ON evolution_sessions(created_at);
                CREATE INDEX idx_events_target ON events(target_id);
            """)
            
            conn.commit()
            return True
            
        except sqlite3.Error:
            return False
        finally:
            conn.close()
            
    except sqlite3.DatabaseError:
        return False