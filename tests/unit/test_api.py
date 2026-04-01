"""Tests for the Memkoshi Python API."""

import tempfile
from pathlib import Path
import pytest
from memkoshi import Memkoshi
from memkoshi.core.memory import MemoryCategory


def test_memkoshi_import():
    """Memkoshi can be imported from package."""
    from memkoshi import Memkoshi
    assert Memkoshi is not None


def test_memkoshi_init():
    """Memkoshi can be initialized with a storage path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        assert m is not None


def test_memkoshi_init_initializes_storage():
    """Memkoshi.init() creates the storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        # Check that database file exists
        db_path = Path(tmpdir) / "memkoshi.db"
        assert db_path.exists()


def test_memkoshi_boot_fresh():
    """Memkoshi.boot() returns fresh context on new instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        ctx = m.boot()
        assert ctx is not None
        assert "session_count" in ctx
        assert ctx["session_count"] == 0
        assert "memory_count" in ctx
        assert ctx["memory_count"] == 0


def test_memkoshi_recall_empty():
    """Memkoshi.recall() returns empty list on fresh instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        results = m.recall("test query")
        assert results == []


def test_memkoshi_commit_and_recall():
    """Memkoshi.commit() processes text and recall finds it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        # Commit some text with memories
        text = "I decided to use Python for the new project. We prefer PostgreSQL over MySQL for production databases."
        result = m.commit(text)
        
        assert result is not None
        assert "staged_count" in result
        assert result["staged_count"] > 0
        
        # Should be able to see staged memories
        staged = m.list_staged()
        assert len(staged) > 0
        
        # Approve all staged memories
        for memory in staged:
            m.approve(memory["id"])
        
        # Now recall should find them
        results = m.recall("Python")
        assert len(results) > 0
        assert any("Python" in r.get("content", "") for r in results)


def test_memkoshi_list_staged():
    """Memkoshi.list_staged() returns staged memories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        # Initially empty
        staged = m.list_staged()
        assert staged == []
        
        # Commit something
        text = "The team decided to implement caching to improve performance."
        m.commit(text)
        
        # Now should have staged memories
        staged = m.list_staged()
        assert len(staged) > 0
        assert all("id" in memory for memory in staged)
        assert all("category" in memory for memory in staged)
        assert all("content" in memory for memory in staged)


def test_memkoshi_approve_reject():
    """Memkoshi.approve() and reject() manage staged memories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        # Commit something
        text = "We fixed the bug by adding proper error handling. The issue was caused by missing null checks."
        m.commit(text)
        
        staged = m.list_staged()
        assert len(staged) >= 2  # Should extract at least 2 memories
        
        # Approve first, reject second
        m.approve(staged[0]["id"])
        m.reject(staged[1]["id"], reason="not relevant")
        
        # Check they're no longer staged
        new_staged = m.list_staged()
        staged_ids = [s["id"] for s in new_staged]
        assert staged[0]["id"] not in staged_ids
        assert staged[1]["id"] not in staged_ids


def test_memkoshi_stats():
    """Memkoshi.stats() returns storage statistics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        stats = m.stats()
        assert "total_memories" in stats
        assert "staged_memories" in stats
        assert "memory_categories" in stats
        assert stats["total_memories"] == 0
        assert stats["staged_memories"] == 0
        
        # Add some memories
        m.commit("I prefer using black for code formatting.")
        stats = m.stats()
        assert stats["staged_memories"] > 0


def test_memkoshi_boot_after_sessions():
    """Memkoshi.boot() shows session history after commits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        # First boot - fresh
        ctx = m.boot()
        assert ctx["session_count"] == 0
        
        # Do some commits
        m.commit("Session 1: Decided to use pytest for testing.")
        m.commit("Session 2: Implemented the authentication module.")
        m.commit("Session 3: Fixed the race condition in async handler.")
        
        # Boot again - should show history
        ctx = m.boot()
        assert ctx["session_count"] == 3
        assert "recent_sessions" in ctx
        assert len(ctx["recent_sessions"]) == 3


def test_memkoshi_recall_with_limit():
    """Memkoshi.recall() respects limit parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = Memkoshi(tmpdir)
        m.init()
        
        # Add multiple memories about Python
        texts = [
            "I decided to use Python for data analysis.",
            "Python is great for machine learning projects.",
            "We chose Python over Java for the web backend.",
            "The team prefers Python for scripting tasks.",
            "Python's ecosystem is perfect for our needs."
        ]
        
        for text in texts:
            m.commit(text)
            
        # Approve all
        for memory in m.list_staged():
            m.approve(memory["id"])
        
        # Recall with limit
        results = m.recall("Python", limit=3)
        assert len(results) <= 3
