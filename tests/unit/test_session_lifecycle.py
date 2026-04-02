"""Tests for session lifecycle management."""

import pytest
import tempfile
import shutil
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from memkoshi.api import Memkoshi
from memkoshi.core.session import SessionContext


@pytest.fixture
def temp_storage():
    """Create temporary storage directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def memkoshi(temp_storage):
    """Create initialized Memkoshi instance."""
    mk = Memkoshi(temp_storage)
    mk.init()
    return mk


@pytest.fixture
def memkoshi_auto_extract(temp_storage):
    """Create initialized Memkoshi instance with auto-extract enabled."""
    mk = Memkoshi(temp_storage, enable_auto_extract=True)
    mk.init()
    return mk


class TestSessionContext:
    """Test SessionContext class behavior."""
    
    def test_session_context_init(self, memkoshi):
        """Test SessionContext initialization."""
        session = SessionContext(memkoshi, "test session", auto_extract=True)
        
        assert session.mk is memkoshi
        assert session.description == "test session"
        assert session.auto_extract is True
        assert session.messages == []
        assert session.tool_calls == []
        assert session.session_id.startswith("session_")
        assert isinstance(session.started_at, datetime)
    
    def test_session_context_enter_exit(self, memkoshi):
        """Test context manager enter/exit behavior."""
        session = SessionContext(memkoshi, "test session")
        
        # Mock the trigger event method
        memkoshi._trigger_event = Mock()
        
        # Test enter
        result = session.__enter__()
        assert result is session
        assert memkoshi._trigger_event.called
        assert memkoshi._trigger_event.call_args[0][0] == 'session_start'
        
        # Test exit
        session.__exit__(None, None, None)
        assert hasattr(session, 'ended_at')
        
        # Should trigger session_end event
        end_call = [call for call in memkoshi._trigger_event.call_args_list 
                   if call[0][0] == 'session_end']
        assert len(end_call) == 1
    
    def test_add_message(self, memkoshi):
        """Test adding messages to session."""
        session = SessionContext(memkoshi)
        
        session.add_message('user', 'Hello world')
        session.add_message('assistant', 'Hi there!')
        
        assert len(session.messages) == 2
        assert session.messages[0]['role'] == 'user'
        assert session.messages[0]['content'] == 'Hello world'
        assert session.messages[1]['role'] == 'assistant'
        assert session.messages[1]['content'] == 'Hi there!'
        
        # Check timestamps
        for msg in session.messages:
            assert 'timestamp' in msg
            assert isinstance(msg['timestamp'], str)
    
    def test_add_tool_call(self, memkoshi):
        """Test adding tool calls to session."""
        session = SessionContext(memkoshi)
        
        session.add_tool_call('search', {'query': 'test'}, ['result1', 'result2'])
        session.add_tool_call('write', {'path': 'test.py'})
        
        assert len(session.tool_calls) == 2
        assert session.tool_calls[0]['tool'] == 'search'
        assert session.tool_calls[0]['args'] == {'query': 'test'}
        assert session.tool_calls[0]['result'] == ['result1', 'result2']
        assert session.tool_calls[1]['tool'] == 'write'
        assert session.tool_calls[1]['args'] == {'path': 'test.py'}
        assert session.tool_calls[1]['result'] is None
        
        # Check timestamps
        for call in session.tool_calls:
            assert 'timestamp' in call
    
    def test_build_summary(self, memkoshi):
        """Test session summary generation."""
        session = SessionContext(memkoshi, "debugging issue")
        
        session.add_message('user', 'I have a bug')
        session.add_message('assistant', 'Let me help you')
        session.add_tool_call('analyze', {'code': 'test.py'})
        session.add_tool_call('fix', {'patch': 'abc123'})
        
        summary = session._build_summary()
        
        assert 'Session: debugging issue' in summary
        assert '[user]: I have a bug' in summary
        assert '[assistant]: Let me help you' in summary
        assert 'Tools used:' in summary
        assert 'analyze' in summary
        assert 'fix' in summary
    
    def test_build_summary_no_description(self, memkoshi):
        """Test summary without description."""
        session = SessionContext(memkoshi)
        session.add_message('user', 'Hello')
        
        summary = session._build_summary()
        
        assert not summary.startswith('Session:')
        assert '[user]: Hello' in summary
    
    def test_get_data(self, memkoshi):
        """Test session data dictionary generation."""
        session = SessionContext(memkoshi, "test session")
        session.add_message('user', 'Hello')
        session.add_message('assistant', 'Hi')
        session.add_message('user', 'How are you?')
        session.add_tool_call('test', {'arg': 'value'})
        
        data = session._get_data()
        
        assert data['session_id'].startswith('session_')
        assert data['description'] == 'test session'
        assert len(data['messages']) == 3
        assert len(data['tool_calls']) == 1
        assert data['message_count'] == 3
        assert data['user_message_count'] == 2
        assert 'started_at' in data
        assert isinstance(data['started_at'], str)
        
        # After ending session
        session.ended_at = datetime.now(timezone.utc)
        data = session._get_data()
        assert 'ended_at' in data


class TestMemkoshiSessionAPI:
    """Test Memkoshi session API methods."""
    
    def test_init_with_auto_extract(self, temp_storage):
        """Test initialization with auto-extract flag."""
        mk = Memkoshi(temp_storage, enable_auto_extract=True)
        assert mk.enable_auto_extract is True
        assert mk._callbacks == []
        assert mk._active_session is None
    
    def test_session_creation(self, memkoshi):
        """Test session context manager creation."""
        session = memkoshi.session("test session")
        
        assert isinstance(session, SessionContext)
        assert session.description == "test session"
        assert session.mk is memkoshi
        assert memkoshi._active_session is session
    
    def test_session_already_active_error(self, memkoshi):
        """Test error when session already active."""
        # Start first session
        memkoshi._active_session = Mock()
        
        with pytest.raises(RuntimeError, match="Session already active"):
            memkoshi.session("second session")
    
    def test_callback_registration(self, memkoshi):
        """Test event callback registration."""
        def test_callback(event, data):
            pass
        
        memkoshi.on('session_start', test_callback)
        memkoshi.on('session_end', test_callback)
        memkoshi.on('checkpoint', test_callback)
        
        assert len(memkoshi._callbacks) == 3
        assert ('session_start', test_callback) in memkoshi._callbacks
        assert ('session_end', test_callback) in memkoshi._callbacks
        assert ('checkpoint', test_callback) in memkoshi._callbacks
    
    def test_invalid_event_registration(self, memkoshi):
        """Test error on invalid event registration."""
        def test_callback(event, data):
            pass
        
        with pytest.raises(ValueError, match="Unknown event: invalid_event"):
            memkoshi.on('invalid_event', test_callback)
    
    def test_trigger_event(self, memkoshi):
        """Test event triggering mechanism."""
        callback_calls = []
        
        def test_callback(event, data):
            callback_calls.append((event, data))
        
        memkoshi.on('session_start', test_callback)
        
        test_data = {'session_id': 'test', 'message_count': 5}
        memkoshi._trigger_event('session_start', test_data)
        
        assert len(callback_calls) == 1
        assert callback_calls[0] == ('session_start', test_data)
    
    def test_trigger_event_error_handling(self, memkoshi):
        """Test callback error handling doesn't break session."""
        def broken_callback(event, data):
            raise Exception("Callback error")
        
        def working_callback(event, data):
            working_callback.called = True
        working_callback.called = False
        
        memkoshi.on('session_start', broken_callback)
        memkoshi.on('session_start', working_callback)
        
        # Should not raise exception
        memkoshi._trigger_event('session_start', {})
        
        # Working callback should still be called
        assert working_callback.called
    
    def test_checkpoint_with_session(self, memkoshi):
        """Test checkpoint creation with active session."""
        with memkoshi.session("test") as session:
            session.add_message('user', 'test message')
            
            checkpoint = memkoshi.checkpoint()
            
            assert 'id' in checkpoint
            assert checkpoint['id'].startswith('checkpoint_')
            assert 'timestamp' in checkpoint
            assert 'session_id' in checkpoint
            assert checkpoint['session_id'] == session.session_id
    
    def test_checkpoint_no_session(self, memkoshi):
        """Test checkpoint without active session falls back to context."""
        # Mock context manager
        memkoshi._context_manager = Mock()
        memkoshi._context_manager.checkpoint.return_value = {'test': 'checkpoint'}
        
        result = memkoshi.checkpoint()
        
        assert result == {'test': 'checkpoint'}
        memkoshi._context_manager.checkpoint.assert_called_once()
    
    def test_checkpoint_no_session_no_context(self, memkoshi):
        """Test checkpoint error with no session or context."""
        with pytest.raises(RuntimeError, match="No active session or context manager"):
            memkoshi.checkpoint()


class TestSessionIntegration:
    """Test full session lifecycle integration."""
    
    def test_full_session_lifecycle(self, memkoshi):
        """Test complete session from start to finish."""
        callback_events = []
        
        def track_events(event, data):
            callback_events.append(event)
        
        memkoshi.on('session_start', track_events)
        memkoshi.on('session_end', track_events)
        
        with memkoshi.session("integration test") as session:
            session.add_message('user', 'Hello')
            session.add_message('assistant', 'Hi there!')
            session.add_tool_call('search', {'q': 'test'})
        
        # Check callbacks were triggered
        assert 'session_start' in callback_events
        assert 'session_end' in callback_events
        
        # Active session should be cleared
        assert memkoshi._active_session is None
    
    @patch('memkoshi.api.Memkoshi.commit')
    def test_auto_extraction_on_exit(self, mock_commit, memkoshi_auto_extract):
        """Test auto-extraction when session has enough messages."""
        with memkoshi_auto_extract.session("auto extract test") as session:
            session.add_message('user', 'First message')
            session.add_message('assistant', 'First response')
        
        # Should call commit with session summary
        mock_commit.assert_called_once()
        args = mock_commit.call_args[0]
        assert 'Session: auto extract test' in args[0]
        assert '[user]: First message' in args[0]
    
    @patch('memkoshi.api.Memkoshi.commit')
    def test_no_auto_extraction_insufficient_messages(self, mock_commit, memkoshi_auto_extract):
        """Test no auto-extraction with insufficient messages."""
        with memkoshi_auto_extract.session("test") as session:
            session.add_message('user', 'Only message')
        
        # Should not call commit
        mock_commit.assert_not_called()
    
    @patch('memkoshi.api.Memkoshi.commit')
    def test_auto_extraction_disabled(self, mock_commit, memkoshi):
        """Test no auto-extraction when disabled."""
        with memkoshi.session("test") as session:
            session.add_message('user', 'First message')
            session.add_message('assistant', 'Response')
        
        # Should not call commit
        mock_commit.assert_not_called()
    
    def test_session_context_tracking(self, memkoshi):
        """Test session is tracked in context manager."""
        # Mock context manager
        memkoshi._context_manager = Mock()
        
        with memkoshi.session("context tracking test") as session:
            session.add_message('user', 'Test message')
        
        # Should call add_session on context manager
        memkoshi._context_manager.add_session.assert_called_once()
    
    def test_extraction_error_doesnt_break_session(self, memkoshi_auto_extract):
        """Test that extraction errors don't break session exit."""
        # Make commit raise an error
        def failing_commit(text):
            raise Exception("Extraction failed")
        
        memkoshi_auto_extract.commit = failing_commit
        
        # Session should still exit cleanly
        with memkoshi_auto_extract.session("error test") as session:
            session.add_message('user', 'Message 1')
            session.add_message('assistant', 'Message 2')
        
        # Active session should be cleared despite error
        assert memkoshi_auto_extract._active_session is None
    
    def test_session_data_format(self, memkoshi):
        """Test session data format in callbacks."""
        received_data = []
        
        def capture_data(event, data):
            received_data.append(data)
        
        memkoshi.on('session_start', capture_data)
        memkoshi.on('session_end', capture_data)
        
        with memkoshi.session("data format test") as session:
            session.add_message('user', 'Test')
            session.add_message('user', 'Another')
            session.add_tool_call('test_tool', {'arg': 'val'})
        
        # Check start data format
        start_data = received_data[0]
        assert 'session_id' in start_data
        assert start_data['description'] == 'data format test'
        assert 'started_at' in start_data
        assert start_data['message_count'] == 0  # No messages at start
        
        # Check end data format
        end_data = received_data[1]
        assert 'session_id' in end_data
        assert 'ended_at' in end_data
        assert end_data['message_count'] == 2
        assert end_data['user_message_count'] == 2
        assert len(end_data['messages']) == 2
        assert len(end_data['tool_calls']) == 1


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_session_exception_propagation(self, memkoshi):
        """Test that exceptions in session code are propagated."""
        with pytest.raises(ValueError, match="Test error"):
            with memkoshi.session("error test"):
                raise ValueError("Test error")
        
        # Session should be cleaned up
        assert memkoshi._active_session is None
    
    def test_session_context_cleanup_on_exception(self, memkoshi):
        """Test session cleanup happens even with exceptions."""
        callback_calls = []
        
        def track_end(event, data):
            if event == 'session_end':
                callback_calls.append('end')
        
        memkoshi.on('session_end', track_end)
        
        try:
            with memkoshi.session("cleanup test"):
                raise RuntimeError("Session error")
        except RuntimeError:
            pass
        
        # End callback should still be called
        assert 'end' in callback_calls
        assert memkoshi._active_session is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])