"""Tests for storage backends."""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime
from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence
from memkoshi.core.session import Session, SessionSummary
from memkoshi.core.context import BootContext
from memkoshi.storage.base import StorageBackend
from memkoshi.storage.sqlite import SQLiteBackend


def test_storage_backend_is_abstract():
    """StorageBackend is abstract and cannot be instantiated."""
    with pytest.raises(TypeError):
        StorageBackend()


def test_sqlite_backend_can_be_instantiated():
    """SQLiteBackend can be instantiated."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        assert backend is not None
        assert backend.db_path == Path(temp_dir) / "memkoshi.db"


def test_sqlite_backend_initialize_creates_database():
    """SQLiteBackend.initialize() creates the database file and tables."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Database file should exist
        assert backend.db_path.exists()
        
        # Should be able to connect to it
        conn = sqlite3.connect(backend.db_path)
        cursor = conn.cursor()
        
        # Check that tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        
        expected_tables = {"memories", "staged_memories", "sessions", "context"}
        assert expected_tables.issubset(tables)
        
        conn.close()


def test_sqlite_backend_store_and_get_memory():
    """SQLiteBackend can store and retrieve memories."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH
        )
        
        # Store memory
        stored_id = backend.store_memory(memory)
        assert stored_id == "mem_12345678"
        
        # Retrieve memory
        retrieved = backend.get_memory("mem_12345678")
        assert retrieved is not None
        assert retrieved.id == memory.id
        assert retrieved.title == memory.title
        assert retrieved.content == memory.content
        assert retrieved.category == memory.category


def test_sqlite_backend_get_nonexistent_memory_returns_none():
    """SQLiteBackend.get_memory() returns None for non-existent memory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        result = backend.get_memory("mem_nonexist")
        assert result is None


def test_sqlite_backend_update_memory():
    """SQLiteBackend can update memory fields."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH
        )
        
        # Store memory
        backend.store_memory(memory)
        
        # Update memory
        updates = {
            "title": "Updated Title",
            "content": "Updated content",
            "importance": 0.8
        }
        result = backend.update_memory("mem_12345678", updates)
        assert result is True
        
        # Verify update
        updated = backend.get_memory("mem_12345678")
        assert updated.title == "Updated Title"
        assert updated.content == "Updated content"
        assert updated.importance == 0.8
        assert updated.updated is not None


def test_sqlite_backend_update_nonexistent_memory():
    """SQLiteBackend.update_memory() returns False for non-existent memory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        result = backend.update_memory("mem_nonexist", {"title": "New Title"})
        assert result is False


def test_sqlite_backend_delete_memory():
    """SQLiteBackend can delete memories."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH
        )
        
        # Store memory
        backend.store_memory(memory)
        assert backend.get_memory("mem_12345678") is not None
        
        # Delete memory
        result = backend.delete_memory("mem_12345678")
        assert result is True
        
        # Verify deletion
        assert backend.get_memory("mem_12345678") is None


def test_sqlite_backend_delete_nonexistent_memory():
    """SQLiteBackend.delete_memory() returns False for non-existent memory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        result = backend.delete_memory("mem_nonexist")
        assert result is False


def test_sqlite_backend_list_memories():
    """SQLiteBackend can list memories with filtering."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Store test memories
        memory1 = Memory(
            id="mem_11111111",
            category=MemoryCategory.PREFERENCES,
            topic="topic1",
            title="Memory 1",
            abstract="Abstract 1",
            content="Content 1",
            confidence=MemoryConfidence.HIGH,
            tags=["tag1", "common"]
        )
        
        memory2 = Memory(
            id="mem_22222222",
            category=MemoryCategory.ENTITIES,
            topic="topic2",
            title="Memory 2",
            abstract="Abstract 2",
            content="Content 2",
            confidence=MemoryConfidence.MEDIUM,
            tags=["tag2", "common"]
        )
        
        memory3 = Memory(
            id="mem_33333333",
            category=MemoryCategory.PREFERENCES,
            topic="topic3",
            title="Memory 3",
            abstract="Abstract 3",
            content="Content 3",
            confidence=MemoryConfidence.LOW,
            tags=["tag3"]
        )
        
        backend.store_memory(memory1)
        backend.store_memory(memory2)
        backend.store_memory(memory3)
        
        # Test no filtering
        all_memories = backend.list_memories()
        assert len(all_memories) == 3
        
        # Test category filtering
        prefs = backend.list_memories(category=MemoryCategory.PREFERENCES)
        assert len(prefs) == 2
        assert all(m.category == MemoryCategory.PREFERENCES for m in prefs)
        
        # Test tags filtering
        common_tagged = backend.list_memories(tags=["common"])
        assert len(common_tagged) == 2
        
        # Test limit and offset
        limited = backend.list_memories(limit=2)
        assert len(limited) == 2
        
        offset_results = backend.list_memories(limit=2, offset=2)
        assert len(offset_results) == 1


def test_sqlite_backend_session_crud():
    """SQLiteBackend can store and retrieve sessions."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Create test session
        summary = SessionSummary(
            id="S123",
            started_at=datetime.now(),
            conversation_summary="Test session summary",
            key_decisions=["Decision 1", "Decision 2"],
            tools_used=["tool1", "tool2"]
        )
        
        session = Session(
            summary=summary,
            raw_messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"}
            ],
            extracted_memories=["mem_11111111"]
        )
        
        # Store session
        stored_id = backend.store_session(session)
        assert stored_id == "S123"
        
        # Retrieve session
        retrieved = backend.get_session("S123")
        assert retrieved is not None
        assert retrieved.summary.id == "S123"
        assert retrieved.summary.conversation_summary == "Test session summary"
        assert len(retrieved.raw_messages) == 2
        assert retrieved.extracted_memories == ["mem_11111111"]


def test_sqlite_backend_list_sessions():
    """SQLiteBackend can list sessions with filtering."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Store test sessions
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        
        for i in range(5):
            summary = SessionSummary(
                id=f"S{i}",
                started_at=datetime(2024, 1, i+1, 12, 0, 0),
                conversation_summary=f"Session {i} summary"
            )
            session = Session(summary=summary)
            backend.store_session(session)
        
        # Test list all
        all_sessions = backend.list_sessions()
        assert len(all_sessions) <= 10  # default limit
        
        # Test with custom limit
        limited = backend.list_sessions(limit=3)
        assert len(limited) == 3
        
        # Test with offset
        offset_results = backend.list_sessions(limit=2, offset=2)
        assert len(offset_results) == 2
        
        # Test since filtering
        since_date = datetime(2024, 1, 3, 0, 0, 0)
        recent = backend.list_sessions(since=since_date)
        assert len(recent) == 3


def test_sqlite_backend_context_crud():
    """SQLiteBackend can store and retrieve boot context."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Create test context
        context = BootContext(
            handoff="Current work state",
            session_brief="Brief summary",
            recent_sessions=["S1", "S2", "S3"],
            active_projects=["project1", "project2"],
            staged_memories_count=5
        )
        
        # Store context
        backend.store_context(context)
        
        # Retrieve context
        retrieved = backend.get_context()
        assert retrieved is not None
        assert retrieved.handoff == "Current work state"
        assert retrieved.session_brief == "Brief summary"
        assert len(retrieved.recent_sessions) == 3
        assert retrieved.staged_memories_count == 5


def test_sqlite_backend_staging_workflow():
    """SQLiteBackend can manage staged memories workflow."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH
        )
        
        # Stage memory
        staged_id = backend.stage_memory(memory)
        assert staged_id == "mem_12345678"
        
        # List staged
        staged_list = backend.list_staged()
        assert len(staged_list) == 1
        assert staged_list[0].id == "mem_12345678"
        
        # Approve memory
        result = backend.approve_memory("mem_12345678", "test_reviewer")
        assert result is True
        
        # Memory should be in permanent storage now
        permanent = backend.get_memory("mem_12345678")
        assert permanent is not None
        
        # Should no longer be in staging
        staged_list = backend.list_staged()
        assert len(staged_list) == 0


def test_sqlite_backend_reject_staged_memory():
    """SQLiteBackend can reject staged memories."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH
        )
        
        # Stage memory
        backend.stage_memory(memory)
        
        # Reject memory
        result = backend.reject_memory("mem_12345678", "Not relevant")
        assert result is True
        
        # Memory should not be in permanent storage
        permanent = backend.get_memory("mem_12345678")
        assert permanent is None
        
        # Should not be in pending staging anymore
        staged_list = backend.list_staged()
        assert len(staged_list) == 0


def test_sqlite_backend_get_stats():
    """SQLiteBackend can return storage statistics."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Add some test data
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH
        )
        backend.store_memory(memory)
        backend.stage_memory(memory)  # Also stage it
        
        stats = backend.get_stats()
        assert "memories_count" in stats
        assert "staged_count" in stats
        assert "sessions_count" in stats
        assert stats["memories_count"] >= 1


def test_sqlite_backend_search_memories():
    """SQLiteBackend can search memories with LIKE queries."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Store test memories with different content
        memory1 = Memory(
            id="mem_11111111",
            category=MemoryCategory.PREFERENCES,
            topic="python",
            title="Python Coding Style",
            abstract="Preferences for Python coding",
            content="I prefer using black for formatting and pytest for testing",
            confidence=MemoryConfidence.HIGH
        )
        
        memory2 = Memory(
            id="mem_22222222",
            category=MemoryCategory.ENTITIES,
            topic="javascript",
            title="JavaScript Framework",
            abstract="React framework knowledge",
            content="React is my preferred frontend framework for building UIs",
            confidence=MemoryConfidence.MEDIUM
        )
        
        backend.store_memory(memory1)
        backend.store_memory(memory2)
        
        # Search for "python"
        python_results = backend.search_memories("python", limit=10)
        assert len(python_results) == 1
        assert python_results[0].id == "mem_11111111"
        
        # Search for "framework"
        framework_results = backend.search_memories("framework", limit=10)
        assert len(framework_results) >= 1
        
        # Search for non-existent term
        no_results = backend.search_memories("nonexistent", limit=10)
        assert len(no_results) == 0


def test_sqlite_backend_backup():
    """SQLiteBackend can create backups."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Add some data
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="test topic",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH
        )
        backend.store_memory(memory)
        
        # Create backup
        backup_path = str(Path(temp_dir) / "backup.db")
        result = backend.backup(backup_path)
        assert result is True
        
        # Verify backup exists and has content
        backup_file = Path(backup_path)
        assert backup_file.exists()
        
        # Verify backup contains the data
        backup_conn = sqlite3.connect(backup_path)
        cursor = backup_conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memories")
        count = cursor.fetchone()[0]
        assert count == 1
        backup_conn.close()

def test_sqlite_backend_connection_reuse():
    """SQLiteBackend reuses the same connection across operations."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Store the connection object
        conn1 = backend.conn
        
        # Create a memory
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.CASES,
            topic="test",
            title="Test Memory",
            abstract="Test abstract",
            content="Test content",
            confidence=MemoryConfidence.HIGH,
            source_sessions=["session1"],
            related_topics=["topic1"],
            created_by="test"
        )
        
        # Store and retrieve memory
        memory_id = backend.store_memory(memory)
        retrieved = backend.get_memory(memory_id)
        
        # Connection should still be the same
        assert backend.conn is conn1
        assert backend.conn is not None
        
        # Test context manager
        with backend as b:
            assert b.conn is conn1
            
        # After context manager exit, connection should be closed
        assert backend.conn is None


def test_sqlite_backend_creates_indexes():
    """SQLiteBackend creates proper indexes for performance."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Check that indexes were created
        cursor = backend.conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND sql IS NOT NULL
            ORDER BY name
        """)
        
        indexes = [row[0] for row in cursor.fetchall()]
        
        expected_indexes = [
            'idx_memories_category',
            'idx_memories_created', 
            'idx_memories_importance',
            'idx_sessions_id',
            'idx_staged_status'
        ]
        
        for expected in expected_indexes:
            assert expected in indexes, f"Index {expected} not found"


def test_sqlite_backend_error_handling():
    """SQLiteBackend raises appropriate exceptions on errors."""
    from memkoshi.core.exceptions import MemkoshiStorageError
    
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Close the connection to simulate a database error
        backend.close()
        
        # Try to perform an operation, should raise MemkoshiStorageError
        with pytest.raises(MemkoshiStorageError):
            backend.get_memory("mem_12345678")


def test_sqlite_backend_batch_operations():
    """SQLiteBackend supports batch operations."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backend = SQLiteBackend(str(temp_dir))
        backend.initialize()
        
        # Create multiple memories
        memories = []
        for i in range(5):
            memory = Memory(
                id=f"mem_{i:08x}",
                category=MemoryCategory.EVENTS,
                topic="batch test",
                title=f"Batch Memory {i}",
                abstract=f"Batch abstract {i}",
                content=f"Batch content {i}",
                confidence=MemoryConfidence.MEDIUM
            )
            memories.append(memory)
        
        # Stage all memories
        staged_ids = backend.stage_memories(memories)
        assert len(staged_ids) == 5
        
        # List staged
        staged_list = backend.list_staged()
        assert len(staged_list) == 5
        
        # Approve all
        approved_count = backend.approve_all("test_reviewer")
        assert approved_count == 5
        
        # Verify all were moved to permanent storage
        for memory in memories:
            retrieved = backend.get_memory(memory.id)
            assert retrieved is not None
            assert retrieved.id == memory.id
        
        # Stage more memories
        for i in range(3):
            memory = Memory(
                id=f"mem_{100+i:08x}",
                category=MemoryCategory.EVENTS,
                topic="reject test",
                title=f"Reject Memory {i}",
                abstract=f"Reject abstract {i}",
                content=f"Reject content {i}",
                confidence=MemoryConfidence.LOW
            )
            backend.stage_memory(memory)
        
        # Reject all
        rejected_count = backend.reject_all("Not relevant")
        assert rejected_count == 3


