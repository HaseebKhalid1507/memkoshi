"""Tests for v0.4 database migrations."""

import tempfile
import sqlite3
from pathlib import Path
import pytest
from memkoshi.storage.migrations import migrate_to_v04
from memkoshi.storage.sqlite import SQLiteBackend


def test_migration_on_fresh_database():
    """Migration creates new tables on fresh database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create and initialize storage
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Run migration
        success = migrate_to_v04(tmpdir)
        assert success is True
        
        # Verify new tables exist
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        
        # Should have all v0.4 tables
        v04_tables = {"events", "patterns", "evolution_sessions"}
        assert v04_tables.issubset(tables)
        
        # Should still have existing tables
        existing_tables = {"memories", "staged_memories", "sessions", "context"}
        assert existing_tables.issubset(tables)
        
        conn.close()


def test_migration_is_idempotent():
    """Running migration twice is safe."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Run migration twice
        success1 = migrate_to_v04(tmpdir)
        success2 = migrate_to_v04(tmpdir)
        
        assert success1 is True
        assert success2 is True
        
        # Verify tables still exist and no duplicates
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
        results = cursor.fetchall()
        assert len(results) == 1  # Only one events table
        
        conn.close()


def test_migration_preserves_existing_data():
    """Migration doesn't affect existing data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Add some test data to existing tables
        from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence
        from datetime import datetime, timezone
        
        test_memory = Memory(
            id="mem_abcd1234",
            category=MemoryCategory.PATTERNS,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH,
            created=datetime.now(timezone.utc),
            importance=0.8
        )
        
        memory_id = storage.store_memory(test_memory)
        
        # Run migration
        success = migrate_to_v04(tmpdir)
        assert success is True
        
        # Verify existing data is still there
        retrieved = storage.get_memory(memory_id)
        assert retrieved is not None
        assert retrieved.title == "Test Memory"
        assert retrieved.content == "Test content"


def test_migration_creates_all_indexes():
    """Migration creates all required indexes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Run migration
        success = migrate_to_v04(tmpdir)
        assert success is True
        
        # Verify indexes exist
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}
        
        expected_indexes = {
            "idx_events_type_time",
            "idx_events_session",
            "idx_patterns_type",
            "idx_evolution_created",
            "idx_events_target"
        }
        
        assert expected_indexes.issubset(indexes)
        
        conn.close()


def test_migration_sets_wal_mode():
    """Migration enables WAL mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Run migration
        success = migrate_to_v04(tmpdir)
        assert success is True
        
        # Verify WAL mode is set
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"
        
        conn.close()


def test_migration_on_nonexistent_database():
    """Migration handles nonexistent database gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Don't initialize storage - database doesn't exist yet
        
        # Migration should return True (tables will be created on init)
        success = migrate_to_v04(tmpdir)
        assert success is True


def test_events_table_schema():
    """Events table has correct schema after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        migrate_to_v04(tmpdir)
        
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        # Get column info
        cursor.execute("PRAGMA table_info(events)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}  # name: type
        
        expected_columns = {
            "id": "INTEGER",
            "session_id": "TEXT",
            "event_type": "TEXT",
            "target_id": "TEXT",
            "metadata": "TEXT",
            "timestamp": "TEXT",
            "confidence": "REAL"
        }
        
        for col, expected_type in expected_columns.items():
            assert col in columns
            assert columns[col] == expected_type
        
        conn.close()


def test_patterns_table_schema():
    """Patterns table has correct schema after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        migrate_to_v04(tmpdir)
        
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(patterns)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        expected_columns = {
            "id": "INTEGER",
            "pattern_type": "TEXT",
            "name": "TEXT",
            "description": "TEXT",
            "trigger_condition": "TEXT",
            "confidence": "REAL",
            "sample_size": "INTEGER",
            "last_triggered": "TEXT",
            "created_at": "TEXT"
        }
        
        for col, expected_type in expected_columns.items():
            assert col in columns
            assert columns[col] == expected_type
        
        conn.close()


def test_evolution_sessions_table_schema():
    """Evolution sessions table has correct schema after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        migrate_to_v04(tmpdir)
        
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(evolution_sessions)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        expected_columns = {
            "session_id": "TEXT",
            "score": "REAL",
            "task_completion_rate": "REAL",
            "error_count": "INTEGER",
            "satisfaction_keywords": "TEXT",
            "duration_minutes": "INTEGER",
            "memories_committed": "INTEGER",
            "memories_recalled": "INTEGER",
            "insights": "TEXT",
            "created_at": "TEXT"
        }
        
        for col, expected_type in expected_columns.items():
            assert col in columns
            assert columns[col] == expected_type
        
        conn.close()


def test_migration_handles_errors():
    """Migration handles database errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file instead of directory to cause error
        db_file = Path(tmpdir) / "memkoshi.db"
        db_file.write_text("not a database")
        
        # Make it read-only
        db_file.chmod(0o444)
        
        # Migration should return False on error
        success = migrate_to_v04(tmpdir)
        assert success is False


def test_can_use_new_tables_after_migration():
    """New tables are functional after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        migrate_to_v04(tmpdir)
        
        # Test inserting into new tables
        conn = sqlite3.connect(str(Path(tmpdir) / "memkoshi.db"))
        cursor = conn.cursor()
        
        # Insert test event
        cursor.execute("""
            INSERT INTO events (event_type, target_id, metadata, timestamp, confidence)
            VALUES (?, ?, ?, ?, ?)
        """, ("test", "test_id", "{}", "2024-01-01T00:00:00Z", 1.0))
        
        # Insert test pattern
        cursor.execute("""
            INSERT INTO patterns (pattern_type, name, description, trigger_condition, 
                                confidence, sample_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("frequency", "Test Pattern", "Test", "{}", 0.8, 5, "2024-01-01T00:00:00Z"))
        
        # Insert test evolution session
        cursor.execute("""
            INSERT INTO evolution_sessions (session_id, score, created_at)
            VALUES (?, ?, ?)
        """, ("test_session", 7.5, "2024-01-01T00:00:00Z"))
        
        conn.commit()
        
        # Verify data was inserted
        cursor.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] == 1
        
        cursor.execute("SELECT COUNT(*) FROM patterns")
        assert cursor.fetchone()[0] == 1
        
        cursor.execute("SELECT COUNT(*) FROM evolution_sessions")
        assert cursor.fetchone()[0] == 1
        
        conn.close()