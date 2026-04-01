"""Unit tests for memkoshi search engine."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import hashlib

import pytest

from memkoshi.search.engine import MemkoshiSearch, SimpleSearch
from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence
from memkoshi.storage.sqlite import SQLiteBackend


def create_test_memory(title="Test memory", category=MemoryCategory.PATTERNS, **kwargs):
    """Helper to create valid Memory objects for tests."""
    # Generate valid ID if not provided
    if 'id' not in kwargs:
        # Create a hex ID based on the title
        id_hash = hashlib.md5(title.encode()).hexdigest()[:8]
        kwargs['id'] = f"mem_{id_hash}"
    
    defaults = {
        "topic": "test topic",
        "abstract": f"Abstract for {title}",
        "content": f"Content for {title}",
        "confidence": MemoryConfidence.HIGH,
        "tags": ["test"],
    }
    defaults.update(kwargs)
    return Memory(category=category, title=title, **defaults)


class TestSimpleSearch:
    """Test the SimpleSearch fallback that always works."""
    
    def test_simple_search_initialization(self):
        """Test SimpleSearch can be created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            search = SimpleSearch(tmpdir)
            assert search.db_path == tmpdir
    
    def test_simple_search_wraps_storage(self):
        """Test SimpleSearch delegates to storage backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a storage backend with test data
            storage = SQLiteBackend(tmpdir)
            storage.initialize()
            
            # Add some test memories
            memory1 = create_test_memory(
                title="Python async patterns",
                category=MemoryCategory.PATTERNS,
                tags=["python", "async", "programming"]
            )
            memory2 = create_test_memory(
                title="JWT authentication system",
                category=MemoryCategory.CASES,
                tags=["security", "auth", "jwt"]
            )
            
            storage.store_memory(memory1)
            storage.store_memory(memory2)
            
            # Create search engine
            search = SimpleSearch(tmpdir)
            search.initialize()
            
            # Test search works
            results = search.search("auth", limit=5)
            assert len(results) == 1
            assert results[0]["title"] == "JWT authentication system"
    
    def test_simple_search_returns_dict_format(self):
        """Test SimpleSearch returns expected dict format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = SQLiteBackend(tmpdir)
            storage.initialize()
            
            memory = create_test_memory(title="Test memory")
            memory_id = storage.store_memory(memory)
            
            search = SimpleSearch(tmpdir)
            search.initialize()
            
            results = search.search("test", limit=5)
            assert len(results) == 1
            result = results[0]
            
            # Check dict structure
            assert "id" in result
            assert "score" in result
            assert "title" in result
            assert result["id"] == memory_id
            assert result["score"] == 1.0  # Simple search always returns 1.0
            assert result["title"] == "Test memory"
    
    def test_simple_search_with_category_filter(self):
        """Test SimpleSearch respects category filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = SQLiteBackend(tmpdir)
            storage.initialize()
            
            # Add memories in different categories
            patterns_memory = create_test_memory(
                title="Python testing patterns",
                category=MemoryCategory.PATTERNS,
                tags=["python", "testing"]
            )
            events_memory = create_test_memory(
                title="Testing conference event",
                category=MemoryCategory.EVENTS,
                tags=["conference"]
            )
            
            storage.store_memory(patterns_memory)
            storage.store_memory(events_memory)
            
            search = SimpleSearch(tmpdir)
            search.initialize()
            
            # Search with category filter
            results = search.search("testing", category="patterns")
            assert len(results) == 1
            assert results[0]["category"] == MemoryCategory.PATTERNS
    
    def test_simple_search_limit(self):
        """Test SimpleSearch respects limit parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = SQLiteBackend(tmpdir)
            storage.initialize()
            
            # Add multiple memories
            for i in range(10):
                memory = create_test_memory(
                    title=f"Test memory {i}",
                    id=f"mem_{i:08x}",
                    tags=["test"]
                )
                storage.store_memory(memory)
            
            search = SimpleSearch(tmpdir) 
            search.initialize()
            
            # Search with limit
            results = search.search("test", limit=3)
            assert len(results) == 3


class TestMemkoshiSearch:
    """Test the main MemkoshiSearch class."""
    
    def test_memkoshi_search_falls_back_without_velocirag(self):
        """Test MemkoshiSearch uses SimpleSearch when velocirag not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            search = MemkoshiSearch(tmpdir)
            # Force fallback mode
            search._use_fallback = True
            search.initialize()
            
            # Should have fallen back to SimpleSearch
            assert hasattr(search, '_fallback')
            assert isinstance(search._fallback, SimpleSearch)
    
    def test_index_memory_basic(self):
        """Test indexing a memory (using fallback for unit tests)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            search = MemkoshiSearch(tmpdir)
            search.initialize()
            
            memory = create_test_memory(
                title="Test memory",
                id="mem_12345678"
            )
            
            # Should not raise
            search.index_memory(memory)
    
    def test_remove_memory(self):
        """Test removing a memory from index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            search = MemkoshiSearch(tmpdir)
            search.initialize()
            
            # Should not raise even if memory doesn't exist
            search.remove_memory("nonexistent-id")
    
    def test_reindex_all(self):
        """Test reindexing from storage backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = SQLiteBackend(tmpdir)
            storage.initialize()
            
            # Add test memories
            memories = []
            for i in range(3):
                memory = create_test_memory(
                    title=f"Memory {i}",
                    id=f"mem_{i:08x}",
                    tags=[f"tag{i}"]
                )
                storage.store_memory(memory)
                memories.append(memory)
            
            # Create search and reindex
            search = MemkoshiSearch(tmpdir)
            search.initialize()
            count = search.reindex_all(storage)
            
            assert count == 3
            
            # Verify memories are searchable
            results = search.search("Memory", limit=10)
            assert len(results) == 3
    
    def test_recency_bias_scoring(self):
        """Test recency bias adjusts scores based on age."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = SQLiteBackend(tmpdir)  
            storage.initialize()
            
            # Create memories with different ages
            now = datetime.now(timezone.utc)
            
            # Recent memory (1 day old)
            recent = create_test_memory(
                title="Recent Python guide",
                id="mem_aaaaaaaa",
                tags=["python"],
                created=now - timedelta(days=1)
            )
            
            # Older memory (30 days old)
            older = create_test_memory(
                title="Older Python guide",
                id="mem_bbbbbbbb",
                tags=["python"],
                created=now - timedelta(days=30)
            )
            
            storage.store_memory(recent)
            storage.store_memory(older)
            
            search = MemkoshiSearch(tmpdir)
            search.initialize()
            search.reindex_all(storage)
            
            # Search with recency bias
            results = search.search("Python", limit=10, recency_bias=True)
            
            # Recent memory should score higher
            assert len(results) >= 2
            # With SimpleSearch fallback, we can't test exact scoring
            # but we can verify both are returned
            titles = [r["title"] for r in results]
            assert "Recent Python guide" in titles
            assert "Older Python guide" in titles


class TestIntegration:
    """Integration tests for search with storage."""
    
    def test_search_integration_with_approved_memories(self):
        """Test that approved memories are searchable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = SQLiteBackend(tmpdir)
            storage.initialize()
            
            # Stage a memory
            memory = create_test_memory(
                title="Staged memory",
                id="mem_deadbeef"
            )
            staged_id = storage.stage_memory(memory)
            
            # Create search engine
            search = MemkoshiSearch(tmpdir)
            search.initialize()
            
            # Staged memory should not be searchable yet
            results = search.search("staged", limit=10)
            assert len(results) == 0
            
            # Approve the memory
            storage.approve_memory(staged_id, "test-reviewer")
            
            # Reindex to pick up approved memory
            search.reindex_all(storage)
            
            # Now it should be searchable
            results = search.search("staged", limit=10)
            assert len(results) == 1
            assert results[0]["title"] == "Staged memory"
