"""Tests for the unified context management system."""

import pytest
import json
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from memkoshi.core.context_manager import ContextManager
from memkoshi.storage.sqlite import SQLiteBackend


@pytest.fixture
def temp_storage():
    """Create a temporary storage backend for testing."""
    temp_dir = tempfile.mkdtemp()
    storage = SQLiteBackend(temp_dir)
    storage.initialize()
    yield storage
    storage.close()
    shutil.rmtree(temp_dir)


@pytest.fixture
def context_manager(temp_storage):
    """Create a ContextManager instance with temporary storage."""
    return ContextManager(temp_storage)


class TestContextManager:
    """Test the ContextManager class."""
    
    def test_init(self, temp_storage):
        """Test ContextManager initialization."""
        cm = ContextManager(temp_storage)
        assert cm._storage is temp_storage
        assert cm._boot_cache is None
        assert cm._session_data == {}
    
    # ── Core Operations Tests ────────────────────────────────────
    
    def test_set_get_session_layer(self, context_manager):
        """Test set/get for session layer."""
        # Test string value
        context_manager.set('test_key', 'test_value')
        assert context_manager.get('test_key') == 'test_value'
        
        # Test complex value
        complex_value = {'nested': {'data': [1, 2, 3]}}
        context_manager.set('complex_key', complex_value)
        assert context_manager.get('complex_key') == complex_value
    
    def test_set_get_boot_layer(self, context_manager):
        """Test set/get for boot layer."""
        context_manager.set('boot_pref', 'important_setting', layer='boot')
        assert context_manager.get('boot_pref', layer='boot') == 'important_setting'
        
        # Should not be in session layer
        assert context_manager.get('boot_pref', layer='session') is None
        assert context_manager.get('boot_pref', layer='session', default='missing') == 'missing'
    
    def test_set_get_archive_layer(self, context_manager):
        """Test set/get for archive layer.""" 
        archive_data = {'completed_task': 'Fix bug #123', 'timestamp': '2026-04-02'}
        context_manager.set('old_task', archive_data, layer='archive')
        assert context_manager.get('old_task', layer='archive') == archive_data
    
    def test_get_layer_all(self, context_manager):
        """Test get with layer='all' searches in priority order."""
        # Set in different layers
        context_manager.set('shared_key', 'session_value', layer='session')
        context_manager.set('shared_key', 'boot_value', layer='boot')
        context_manager.set('shared_key', 'archive_value', layer='archive')
        
        # Should return session value (highest priority)
        assert context_manager.get('shared_key', layer='all') == 'session_value'
        
        # Remove from session, should get boot value
        del context_manager._session_data['shared_key']
        context_manager._storage.delete_context_data('session', 'shared_key')
        assert context_manager.get('shared_key', layer='all') == 'boot_value'
    
    def test_set_invalid_layer(self, context_manager):
        """Test that invalid layer raises ValueError."""
        with pytest.raises(ValueError):
            context_manager.set('key', 'value', layer='invalid')
    
    def test_get_invalid_layer(self, context_manager):
        """Test that invalid layer raises ValueError."""
        with pytest.raises(ValueError):
            context_manager.get('key', layer='invalid')
    
    def test_checkpoint(self, context_manager):
        """Test checkpoint functionality."""
        # Set some session data
        context_manager.set('current_task', 'Testing checkpoints')
        context_manager.set('debug_mode', True)
        
        # Create checkpoint
        checkpoint = context_manager.checkpoint("Test checkpoint")
        
        assert 'id' in checkpoint
        assert 'timestamp' in checkpoint
        assert checkpoint['item_count'] == 2
        assert checkpoint['notes'] == "Test checkpoint"
    
    def test_get_checkpoint(self, context_manager):
        """Test getting the latest checkpoint."""
        # No checkpoint initially
        assert context_manager.get_checkpoint() is None
        
        # Create a checkpoint
        context_manager.set('test_data', 'for checkpoint')
        context_manager.checkpoint("First checkpoint")
        
        latest = context_manager.get_checkpoint()
        assert latest is not None
        assert 'id' in latest
        assert latest['notes'] == "First checkpoint"
    
    def test_get_boot_basic(self, context_manager):
        """Test basic boot context generation."""
        boot_context = context_manager.get_boot()
        
        # Should have required keys
        assert 'handoff' in boot_context
        assert 'recent_sessions' in boot_context
        assert 'preferences' in boot_context
        assert 'memory_stats' in boot_context
        assert 'token_count_estimate' in boot_context
        
        # Initially should be empty/None
        assert boot_context['handoff'] is None
        assert boot_context['recent_sessions'] == []
    
    def test_get_boot_with_data(self, context_manager):
        """Test boot context with actual data."""
        # Set up handoff
        context_manager.set_handoff("Test handoff task", progress="50% done")
        
        # Add session
        context_manager.add_session("Test session summary", extracted_count=3)
        
        # Set boot preferences
        context_manager.set('editor', 'vim', layer='boot')
        
        boot_context = context_manager.get_boot()
        
        assert boot_context['handoff']['task'] == "Test handoff task"
        assert len(boot_context['recent_sessions']) == 1
        assert boot_context['preferences']['editor'] == 'vim'
    
    def test_get_boot_token_budget(self, context_manager):
        """Test boot context respects token budget."""
        # Create large data that would exceed budget
        large_text = "x" * 20000  # ~5000 tokens
        context_manager.set('large_data', large_text, layer='boot')
        
        # Request small budget
        boot_context = context_manager.get_boot(token_budget=1000)
        
        # Should fit within budget
        assert boot_context['token_count_estimate'] <= 1000
        
        # Large data should be truncated or excluded
        if 'preferences' in boot_context:
            assert len(str(boot_context['preferences'])) < 4000  # Much smaller than original
    
    def test_get_boot_caching(self, context_manager):
        """Test that boot context is cached."""
        context_manager.set('test', 'value', layer='boot')
        
        # First call
        boot1 = context_manager.get_boot()
        
        # Second call should return same object (cached)
        boot2 = context_manager.get_boot()
        assert boot1 is boot2
        
        # Cache should be cleared when boot layer changes
        context_manager.set('new_key', 'new_value', layer='boot')
        boot3 = context_manager.get_boot()
        assert boot1 is not boot3
    
    # ── Handoff Operations Tests ──────────────────────────────────
    
    def test_set_handoff_basic(self, context_manager):
        """Test basic handoff setting."""
        context_manager.set_handoff("Fix login bug")
        
        handoff = context_manager.get_handoff()
        assert handoff['task'] == "Fix login bug"
        assert handoff['progress'] == ""
        assert handoff['details'] == {}
        assert handoff['next_steps'] == []
        assert handoff['priority'] == 3
        assert 'created_at' in handoff
    
    def test_set_handoff_complete(self, context_manager):
        """Test handoff with all fields."""
        details = {'file': 'auth.py', 'line': 45}
        next_steps = ['Update config', 'Test changes', 'Deploy']
        
        context_manager.set_handoff(
            task="Fix authentication timeout",
            progress="Identified root cause",
            details=details,
            next_steps=next_steps,
            priority=1
        )
        
        handoff = context_manager.get_handoff()
        assert handoff['task'] == "Fix authentication timeout"
        assert handoff['progress'] == "Identified root cause"
        assert handoff['details'] == details
        assert handoff['next_steps'] == next_steps
        assert handoff['priority'] == 1
    
    def test_get_handoff_none(self, context_manager):
        """Test getting handoff when none exists."""
        assert context_manager.get_handoff() is None
    
    def test_clear_handoff(self, context_manager):
        """Test clearing handoff."""
        # Set a handoff
        context_manager.set_handoff("Test task")
        assert context_manager.get_handoff() is not None
        
        # Clear it
        cleared = context_manager.clear_handoff()
        assert cleared is True
        assert context_manager.get_handoff() is None
        
        # Try to clear again
        cleared_again = context_manager.clear_handoff()
        assert cleared_again is False
    
    def test_handoff_clears_boot_cache(self, context_manager):
        """Test that handoff operations clear boot cache."""
        # Get boot context to populate cache
        context_manager.get_boot()
        assert context_manager._boot_cache is not None
        
        # Set handoff should clear cache
        context_manager.set_handoff("Test task")
        assert context_manager._boot_cache is None
        
        # Get boot context again
        context_manager.get_boot()
        assert context_manager._boot_cache is not None
        
        # Clear handoff should clear cache
        context_manager.clear_handoff()
        assert context_manager._boot_cache is None
    
    # ── Session Management Tests ───────────────────────────────────
    
    def test_add_session(self, context_manager):
        """Test adding session to log."""
        context_manager.add_session("Test session", extracted_count=2)
        
        sessions = context_manager.get_recent_sessions(n=1)
        assert len(sessions) == 1
        assert sessions[0]['summary'] == "Test session"
        assert sessions[0]['extracted_count'] == 2
        assert 'timestamp' in sessions[0]
        assert 'session_id' in sessions[0]
    
    def test_get_recent_sessions(self, context_manager):
        """Test getting recent sessions."""
        # Add multiple sessions
        for i in range(5):
            context_manager.add_session(f"Session {i}", extracted_count=i)
        
        # Get last 3
        recent = context_manager.get_recent_sessions(n=3)
        assert len(recent) == 3
        
        # Should be in reverse chronological order (newest first)
        assert recent[0]['summary'] == "Session 4"
        assert recent[1]['summary'] == "Session 3"
        assert recent[2]['summary'] == "Session 2"
    
    def test_add_session_clears_boot_cache(self, context_manager):
        """Test that adding session clears boot cache."""
        # Get boot context to populate cache
        context_manager.get_boot()
        assert context_manager._boot_cache is not None
        
        # Add session should clear cache
        context_manager.add_session("Test session")
        assert context_manager._boot_cache is None
    
    # ── Private Methods Tests ──────────────────────────────────────
    
    def test_estimate_tokens_string(self, context_manager):
        """Test token estimation for strings."""
        # Simple string
        tokens = context_manager._estimate_tokens("hello world")
        assert tokens == len("hello world") // 4
        
        # Empty string
        tokens = context_manager._estimate_tokens("")
        assert tokens == 0
    
    def test_estimate_tokens_complex(self, context_manager):
        """Test token estimation for complex data."""
        data = {"key": "value", "list": [1, 2, 3]}
        tokens = context_manager._estimate_tokens(data)
        expected = len(json.dumps(data)) // 4
        assert tokens == expected
    
    def test_fit_to_budget(self, context_manager):
        """Test budget fitting algorithm."""
        # Create test context
        context = {
            "handoff": {"task": "x" * 1000},  # ~250 tokens
            "preferences": {"key": "x" * 2000},  # ~500 tokens
            "recent_sessions": [{"summary": "x" * 4000}],  # ~1000 tokens
            "memory_stats": {"count": 100}  # ~50 tokens
        }
        
        # Fit to small budget
        fitted = context_manager._fit_to_budget(context, 1000)
        
        # Should include handoff and preferences (high priority)
        assert 'handoff' in fitted
        assert 'memory_stats' in fitted
        assert fitted['token_count_estimate'] <= 1000
    
    def test_truncate_dict(self, context_manager):
        """Test dictionary truncation.""" 
        large_dict = {
            'a': 'x' * 100,
            'b': 'x' * 200,
            'c': 'x' * 50,
            'd': 'x' * 300
        }
        
        # Truncate to fit in small budget
        truncated = context_manager._truncate_dict(large_dict, 150)
        
        # Should prioritize shorter keys and fit within budget
        total_tokens = context_manager._estimate_tokens(json.dumps(truncated))
        assert total_tokens <= 150
        assert 'a' in truncated or 'c' in truncated  # Shorter keys preferred


class TestBackwardCompatibility:
    """Test backward compatibility with existing APIs."""
    
    def test_legacy_boot_format(self, temp_storage):
        """Test that boot context maintains legacy format."""
        from memkoshi.api import Memkoshi
        
        # Create Memkoshi instance
        mk = Memkoshi(str(temp_storage.base_path))
        mk.init()
        
        # Set up context via new system
        mk.context.set_handoff("Test legacy task")
        mk.context.add_session("Test legacy session", extracted_count=1)
        
        # Boot should return legacy format
        boot = mk.boot()
        
        assert 'session_count' in boot
        assert 'memory_count' in boot
        assert 'staged_count' in boot
        assert 'recent_sessions' in boot
        assert 'handoff_text' in boot
        
        # Legacy handoff_text should be the task
        assert boot['handoff_text'] == "Test legacy task"
        
        # Recent sessions should be simple strings
        assert isinstance(boot['recent_sessions'], list)
        if boot['recent_sessions']:
            assert isinstance(boot['recent_sessions'][0], str)
    
    def test_context_persistence(self, temp_storage):
        """Test that context data persists across ContextManager instances."""
        # Create first context manager and set data
        cm1 = ContextManager(temp_storage)
        cm1.set('persistent_key', 'persistent_value', layer='boot')
        cm1.set_handoff("Persistent handoff")
        
        # Create second context manager
        cm2 = ContextManager(temp_storage)
        
        # Should be able to retrieve data
        assert cm2.get('persistent_key', layer='boot') == 'persistent_value'
        handoff = cm2.get_handoff()
        assert handoff['task'] == "Persistent handoff"


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_storage_errors(self):
        """Test handling of storage backend errors."""
        # Mock storage that raises exceptions
        mock_storage = Mock()
        mock_storage.set_context_data.side_effect = Exception("Storage error")
        
        cm = ContextManager(mock_storage)
        
        # Should propagate storage exceptions
        with pytest.raises(Exception, match="Storage error"):
            cm.set('key', 'value')
    
    def test_json_serialization_errors(self, context_manager):
        """Test handling of non-serializable data."""
        # Python objects that can't be JSON serialized
        class NonSerializable:
            pass
        
        # Should still work for simple types
        context_manager.set('string_key', 'string_value')
        assert context_manager.get('string_key') == 'string_value'
    
    def test_empty_boot_context(self, temp_storage):
        """Test boot context with completely empty storage."""
        cm = ContextManager(temp_storage)
        boot = cm.get_boot()
        
        # Should not crash and should have basic structure
        assert isinstance(boot, dict)
        assert 'handoff' in boot
        assert 'recent_sessions' in boot
        assert 'preferences' in boot
        assert 'memory_stats' in boot
        
        # Values should be empty/None but not cause errors
        assert boot['handoff'] is None
        assert boot['recent_sessions'] == []


class TestIntegration:
    """Integration tests with storage backend."""
    
    def test_full_workflow(self, context_manager):
        """Test a complete context management workflow."""
        # 1. Set up work context
        context_manager.set('current_branch', 'feature/context-api')
        context_manager.set('debug_enabled', True)
        
        # 2. Set handoff for end of day
        context_manager.set_handoff(
            task="Implement context manager",
            progress="Core implementation complete, need tests",
            next_steps=["Write comprehensive tests", "Add CLI commands", "Update docs"],
            priority=1
        )
        
        # 3. Create checkpoint
        checkpoint = context_manager.checkpoint("End of day - context manager MVP")
        assert checkpoint['item_count'] == 3  # 2 context items + 1 handoff
        
        # 4. Add session log
        context_manager.add_session("Implemented context manager", extracted_count=5)
        
        # 5. Get boot context for next day
        boot = context_manager.get_boot()
        
        # Should have all our data
        assert boot['handoff']['task'] == "Implement context manager"
        assert len(boot['recent_sessions']) == 1
        assert boot['recent_sessions'][0]['summary'] == "Implemented context manager"
        
        # 6. Clear handoff when work is done
        assert context_manager.clear_handoff() is True
        
        # 7. Boot context should reflect completion
        new_boot = context_manager.get_boot()
        assert new_boot['handoff'] is None