"""Tests for the event recording system with background buffering."""

import tempfile
import threading
import time
import json
from datetime import datetime, timezone
import pytest
from memkoshi.core.events import EventRecord, EventBuffer
from memkoshi.storage.sqlite import SQLiteBackend


def test_event_record_init():
    """EventRecord can be created with basic fields."""
    event = EventRecord(
        event_type="search",
        target_id="test_id",
        metadata={"query": "test"}
    )
    assert event.event_type == "search"
    assert event.target_id == "test_id"
    assert event.metadata == {"query": "test"}
    assert event.confidence == 1.0
    assert event.session_id is None
    # Timestamp should be set automatically
    assert event.timestamp is not None
    # Should be recent (within last second)
    dt = datetime.fromisoformat(event.timestamp)
    assert (datetime.now(timezone.utc) - dt).total_seconds() < 1.0


def test_event_buffer_init():
    """EventBuffer initializes with storage and threshold."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=10)
        assert buffer.storage == storage
        assert buffer.flush_threshold == 10
        assert len(buffer.events) == 0
        assert buffer._session_id is None


def test_event_buffer_record_basic():
    """EventBuffer records events without blocking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=100)  # High threshold to prevent auto-flush
        
        # Record an event
        buffer.record("search", metadata={"query": "test"})
        
        # Event should be in buffer, not yet in database
        assert len(buffer.events) == 1
        assert buffer.events[0]["event_type"] == "search"
        assert buffer.events[0]["metadata"] == {"query": "test"}


def test_event_buffer_flush_at_threshold():
    """EventBuffer automatically flushes when threshold is reached."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=3)
        
        # Record events up to threshold
        buffer.record("search", metadata={"query": "test1"})
        buffer.record("search", metadata={"query": "test2"})
        
        # Before threshold, events should be in buffer
        assert len(buffer.events) == 2
        
        # Record one more to trigger flush
        buffer.record("search", metadata={"query": "test3"})
        
        # Give background thread time to flush
        time.sleep(0.5)
        
        # Buffer should be cleared after automatic flush
        assert len(buffer.events) == 0
        
        # Events should be in database (either from background flush or manual flush)
        events = storage.get_events()
        assert len(events) >= 3  # At least our 3 events


def test_event_buffer_explicit_flush_sync():
    """EventBuffer.flush_sync() flushes all pending events synchronously."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=100)
        
        # Record some events
        buffer.record("search", metadata={"query": "test1"})
        buffer.record("approve", target_id="mem_123")
        buffer.record("reject", target_id="mem_456", metadata={"reason": "duplicate"})
        
        # Events should be in buffer
        assert len(buffer.events) == 3
        
        # Flush synchronously
        count = buffer.flush_sync()
        assert count == 3
        
        # Buffer should be empty
        assert len(buffer.events) == 0
        
        # Events should be in database
        events = storage.get_events()
        assert len(events) == 3
        assert events[0]["event_type"] == "reject"  # Most recent first
        assert events[1]["event_type"] == "approve"
        assert events[2]["event_type"] == "search"


def test_event_buffer_thread_safety():
    """EventBuffer handles concurrent record() calls safely."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=1000)
        
        # Function to record events in a thread
        def record_events(thread_id):
            for i in range(10):
                buffer.record("test", metadata={"thread": thread_id, "index": i})
        
        # Start multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=record_events, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should have 50 events total
        assert len(buffer.events) == 50
        
        # Flush and verify
        buffer.flush_sync()
        events = storage.get_events(limit=100)
        assert len(events) == 50


def test_event_buffer_session_id():
    """EventBuffer includes session_id when set."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=100)
        
        # Record without session_id
        buffer.record("search", metadata={"query": "test1"})
        assert buffer.events[0]["session_id"] is None
        
        # Set session_id
        buffer.set_session_id("session_123")
        
        # Record with session_id
        buffer.record("search", metadata={"query": "test2"})
        assert buffer.events[1]["session_id"] == "session_123"
        
        # Flush and verify
        buffer.flush_sync()
        events = storage.get_events()
        assert events[0]["session_id"] == "session_123"
        assert events[1]["session_id"] is None


def test_event_buffer_error_handling():
    """EventBuffer handles storage errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=100)
        
        # Close the storage connection to simulate error
        storage.close()
        
        # Recording should not crash
        buffer.record("search", metadata={"query": "test"})
        assert len(buffer.events) == 1
        
        # Flush should not crash either
        count = buffer.flush_sync()
        # Count might be 0 due to error, but shouldn't crash
        assert count >= 0


def test_event_buffer_empty_flush():
    """EventBuffer handles empty flush gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage)
        
        # Flush empty buffer
        count = buffer.flush_sync()
        assert count == 0
        
        # Should not create any events
        events = storage.get_events()
        assert len(events) == 0


def test_event_buffer_metadata_json_serialization():
    """EventBuffer properly serializes metadata to JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=100)
        
        # Record with complex metadata
        metadata = {
            "query": "test query",
            "results_count": 5,
            "filters": ["category:technical", "confidence:high"],
            "nested": {"key": "value"}
        }
        buffer.record("search_complete", metadata=metadata)
        
        # Verify JSON serialization in buffer
        assert buffer.events[0]["metadata"] == metadata
        
        # Flush and verify in storage
        buffer.flush_sync()
        events = storage.get_events()
        assert events[0]["metadata"] == metadata


def test_event_buffer_pending_count():
    """EventBuffer.pending_count() returns correct count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=100)
        
        assert buffer.pending_count() == 0
        
        buffer.record("test1")
        assert buffer.pending_count() == 1
        
        buffer.record("test2")
        buffer.record("test3")
        assert buffer.pending_count() == 3
        
        buffer.flush_sync()
        assert buffer.pending_count() == 0


def test_event_timestamps_are_iso_format():
    """Event timestamps are in ISO format with timezone."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        buffer = EventBuffer(storage, flush_threshold=100)
        buffer.record("test")
        
        timestamp = buffer.events[0]["timestamp"]
        # Should parse as valid ISO datetime
        dt = datetime.fromisoformat(timestamp)
        # Should have timezone info
        assert dt.tzinfo is not None