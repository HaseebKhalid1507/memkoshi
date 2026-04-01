"""Tests for MCP server functionality."""

import pytest
from unittest.mock import Mock, MagicMock
from memkoshi.mcp_server import (
    memory_boot, 
    memory_recall, 
    memory_commit, 
    memory_staged,
    memory_approve,
    memory_reject,
    memory_stats
)


def test_mcp_tools_exist():
    """All MCP tool functions exist."""
    assert memory_boot is not None
    assert memory_recall is not None
    assert memory_commit is not None
    assert memory_staged is not None
    assert memory_approve is not None
    assert memory_reject is not None
    assert memory_stats is not None


def test_memory_boot():
    """memory_boot returns boot context as text."""
    # Mock the Memkoshi API
    with patch('memkoshi.mcp_server.get_memkoshi') as mock_get:
        mock_memkoshi = Mock()
        mock_memkoshi.boot.return_value = {
            "session_count": 5,
            "memory_count": 42,
            "staged_count": 3,
            "recent_sessions": ["Session 1: Test", "Session 2: Demo"],
            "handoff_text": None
        }
        mock_get.return_value = mock_memkoshi
        
        result = memory_boot()
        
        assert isinstance(result, str)
        assert "Session count: 5" in result
        assert "Total memories: 42" in result
        assert "Staged memories: 3" in result
        assert "Session 1: Test" in result


def test_memory_recall():
    """memory_recall returns search results as text."""
    from unittest.mock import patch
    
    with patch('memkoshi.mcp_server.get_memkoshi') as mock_get:
        mock_memkoshi = Mock()
        mock_memkoshi.recall.return_value = [
            {
                "id": "mem_12345678",
                "title": "Python decision",
                "content": "Decided to use Python",
                "category": "events",
                "confidence": "high",
                "score": 0.95
            }
        ]
        mock_get.return_value = mock_memkoshi
        
        result = memory_recall("Python", limit=5)
        
        assert isinstance(result, str)
        assert "mem_12345678" in result
        assert "Python decision" in result
        assert "Decided to use Python" in result


def test_memory_commit():
    """memory_commit processes text and returns results."""
    from unittest.mock import patch
    
    with patch('memkoshi.mcp_server.get_memkoshi') as mock_get:
        mock_memkoshi = Mock()
        mock_memkoshi.commit.return_value = {
            "extracted_count": 2,
            "staged_count": 2,
            "validation_errors": [],
            "pipeline_time": 0.05
        }
        mock_get.return_value = mock_memkoshi
        
        result = memory_commit("Test session with some memories")
        
        assert isinstance(result, str)
        assert "Extracted: 2" in result
        assert "Staged: 2" in result
        assert "successful" in result.lower()


def test_memory_staged():
    """memory_staged lists staged memories."""
    from unittest.mock import patch
    
    with patch('memkoshi.mcp_server.get_memkoshi') as mock_get:
        mock_memkoshi = Mock()
        mock_memkoshi.list_staged.return_value = [
            {
                "id": "mem_11111111",
                "title": "Test memory",
                "category": "events",
                "content": "Test content",
                "staged_at": "2024-01-01T12:00:00"
            }
        ]
        mock_get.return_value = mock_memkoshi
        
        result = memory_staged()
        
        assert isinstance(result, str)
        assert "1 staged" in result
        assert "mem_11111111" in result
        assert "Test memory" in result


def test_memory_approve():
    """memory_approve approves a memory."""
    from unittest.mock import patch
    
    with patch('memkoshi.mcp_server.get_memkoshi') as mock_get:
        mock_memkoshi = Mock()
        mock_get.return_value = mock_memkoshi
        
        result = memory_approve("mem_12345678")
        
        mock_memkoshi.approve.assert_called_once_with("mem_12345678")
        assert isinstance(result, str)
        assert "approved" in result.lower()
        assert "mem_12345678" in result


def test_memory_reject():
    """memory_reject rejects a memory with reason."""
    from unittest.mock import patch
    
    with patch('memkoshi.mcp_server.get_memkoshi') as mock_get:
        mock_memkoshi = Mock()
        mock_get.return_value = mock_memkoshi
        
        result = memory_reject("mem_12345678", reason="Not relevant")
        
        mock_memkoshi.reject.assert_called_once_with("mem_12345678", "Not relevant")
        assert isinstance(result, str)
        assert "rejected" in result.lower()
        assert "mem_12345678" in result


def test_memory_stats():
    """memory_stats returns storage statistics."""
    from unittest.mock import patch
    
    with patch('memkoshi.mcp_server.get_memkoshi') as mock_get:
        mock_memkoshi = Mock()
        mock_memkoshi.stats.return_value = {
            "total_memories": 100,
            "staged_memories": 5,
            "session_count": 20,
            "database_size": 1024,
            "memory_categories": {
                "events": 40,
                "preferences": 30,
                "entities": 20,
                "cases": 10
            }
        }
        mock_get.return_value = mock_memkoshi
        
        result = memory_stats()
        
        assert isinstance(result, str)
        assert "Total memories: 100" in result
        assert "Staged memories: 5" in result
        assert "Sessions: 20" in result
        assert "events: 40" in result


# Fix import for patch
from unittest.mock import patch
