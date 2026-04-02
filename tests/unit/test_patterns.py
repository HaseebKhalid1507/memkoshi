"""Tests for pattern detection using concrete SQL queries."""

import tempfile
import json
import sqlite3
from datetime import datetime, timezone, timedelta
import pytest
from memkoshi.core.patterns import Pattern, PatternDetector
from memkoshi.storage.sqlite import SQLiteBackend


def create_test_events(storage, events_data):
    """Helper to insert test events directly into database."""
    cursor = storage.conn.cursor()
    for event in events_data:
        cursor.execute("""
            INSERT INTO events (event_type, target_id, metadata, timestamp, session_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event.get('event_type'),
            event.get('target_id'),
            json.dumps(event.get('metadata', {})),
            event.get('timestamp', datetime.now(timezone.utc).isoformat()),
            event.get('session_id'),
            event.get('confidence', 1.0)
        ))
    storage.conn.commit()


def test_pattern_model():
    """Pattern model validates correctly."""
    pattern = Pattern(
        pattern_type="frequency",
        name="Test Pattern",
        description="A test pattern",
        trigger_condition={"min_count": 3},
        confidence=0.8,
        sample_size=10
    )
    assert pattern.pattern_type == "frequency"
    assert pattern.name == "Test Pattern"
    assert pattern.confidence == 0.8
    assert pattern.sample_size == 10


def test_pattern_detector_init():
    """PatternDetector initializes with storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        detector = PatternDetector(storage)
        assert detector.storage == storage


def test_detect_frequency_patterns_with_3_accesses():
    """Frequency patterns detect memories accessed 3+ times."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create test events - memory accessed 3 times
        events = [
            {"event_type": "search", "target_id": "mem_123", "metadata": {"query": "test"}},
            {"event_type": "search", "target_id": "mem_123", "metadata": {"query": "test"}},
            {"event_type": "search", "target_id": "mem_123", "metadata": {"query": "test"}},
            {"event_type": "search", "target_id": "mem_456", "metadata": {"query": "other"}},
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect_frequency_patterns()
        
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "frequency"
        assert "mem_123" in patterns[0].name
        assert patterns[0].sample_size == 3
        assert patterns[0].confidence == 0.3  # 3/10


def test_detect_frequency_patterns_below_threshold():
    """Frequency patterns ignore memories accessed < 3 times."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create test events - memories accessed only 1-2 times
        events = [
            {"event_type": "search", "target_id": "mem_123", "metadata": {"query": "test"}},
            {"event_type": "search", "target_id": "mem_123", "metadata": {"query": "test"}},
            {"event_type": "search", "target_id": "mem_456", "metadata": {"query": "other"}},
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect_frequency_patterns()
        
        assert len(patterns) == 0  # No patterns should be detected


def test_detect_temporal_patterns():
    """Temporal patterns detect same query on same day of week."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create events on same day of week (Mondays)
        base_monday = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)  # A Monday
        events = [
            {
                "event_type": "search",
                "metadata": {"query": "weekly report"},
                "timestamp": base_monday.isoformat()
            },
            {
                "event_type": "search", 
                "metadata": {"query": "weekly report"},
                "timestamp": (base_monday + timedelta(days=7)).isoformat()  # Next Monday
            },
            {
                "event_type": "search",
                "metadata": {"query": "other query"},
                "timestamp": (base_monday + timedelta(days=1)).isoformat()  # Tuesday
            }
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect_temporal_patterns()
        
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "temporal"
        assert "Monday" in patterns[0].name
        assert "weekly report" in patterns[0].name
        assert patterns[0].sample_size == 2


def test_detect_knowledge_gaps():
    """Knowledge gap patterns detect queries with 0 results 3+ times."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create search_complete events with 0 results
        events = [
            {
                "event_type": "search_complete",
                "metadata": {"query": "missing topic", "results_count": 0}
            },
            {
                "event_type": "search_complete", 
                "metadata": {"query": "missing topic", "results_count": 0}
            },
            {
                "event_type": "search_complete",
                "metadata": {"query": "missing topic", "results_count": 0}
            },
            {
                "event_type": "search_complete",
                "metadata": {"query": "found topic", "results_count": 5}
            }
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect_knowledge_gaps()
        
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "gap"
        assert "missing topic" in patterns[0].name
        assert patterns[0].sample_size == 3
        assert patterns[0].trigger_condition["zero_results"] is True


def test_detect_knowledge_gaps_below_threshold():
    """Knowledge gaps ignore queries with < 3 failures."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create search_complete events with only 2 failures
        events = [
            {
                "event_type": "search_complete",
                "metadata": {"query": "missing topic", "results_count": 0}
            },
            {
                "event_type": "search_complete", 
                "metadata": {"query": "missing topic", "results_count": 0}
            },
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect_knowledge_gaps()
        
        assert len(patterns) == 0


def test_detect_empty_database():
    """Pattern detection returns empty list on empty database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        detector = PatternDetector(storage)
        
        # All detection methods should return empty lists
        assert detector.detect_frequency_patterns() == []
        assert detector.detect_temporal_patterns() == []
        assert detector.detect_knowledge_gaps() == []
        assert detector.detect() == []


def test_pattern_confidence_calculation():
    """Pattern confidence is calculated correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create many accesses to test confidence scaling
        events = []
        for i in range(15):
            events.append({
                "event_type": "search",
                "target_id": "popular_mem",
                "metadata": {"query": "test"}
            })
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect_frequency_patterns()
        
        assert len(patterns) == 1
        assert patterns[0].sample_size == 15
        # Confidence should be capped at 1.0 (15/10 = 1.5, but capped)
        assert patterns[0].confidence == 1.0


def test_event_cleanup_at_limit():
    """Event cleanup removes old events when limit is reached."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create many events with increasing timestamps
        events = []
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(150):  # More than default limit
            events.append({
                "event_type": "test",
                "timestamp": (base_time + timedelta(minutes=i)).isoformat()
            })
        create_test_events(storage, events)
        
        # Verify we have all events
        cursor = storage.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] == 150
        
        detector = PatternDetector(storage)
        deleted = detector.cleanup_old_events(max_events=100)
        
        assert deleted == 50  # Should delete oldest 50
        
        # Verify count after cleanup
        cursor.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] == 100
        
        # Verify oldest events were deleted (earliest timestamp should be 50th event)
        cursor.execute("SELECT MIN(timestamp) FROM events")
        min_timestamp = cursor.fetchone()[0]
        assert min_timestamp == events[50]["timestamp"]


def test_detect_runs_all_algorithms():
    """Main detect() method runs all detection algorithms."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create events that trigger different pattern types
        events = [
            # Frequency pattern
            {"event_type": "search", "target_id": "mem_123"},
            {"event_type": "search", "target_id": "mem_123"},
            {"event_type": "search", "target_id": "mem_123"},
            # Knowledge gap
            {"event_type": "search_complete", "metadata": {"query": "missing", "results_count": 0}},
            {"event_type": "search_complete", "metadata": {"query": "missing", "results_count": 0}},
            {"event_type": "search_complete", "metadata": {"query": "missing", "results_count": 0}},
            # Temporal (same day)
            {"event_type": "search", "metadata": {"query": "monday task"}, 
             "timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc).isoformat()},
            {"event_type": "search", "metadata": {"query": "monday task"},
             "timestamp": datetime(2024, 1, 8, 10, 0, tzinfo=timezone.utc).isoformat()},
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect()
        
        # Should have patterns from all types
        pattern_types = {p.pattern_type for p in patterns}
        assert "frequency" in pattern_types
        assert "gap" in pattern_types
        assert "temporal" in pattern_types
        assert len(patterns) >= 3


def test_insights_generation():
    """insights() generates human-readable strings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create events that generate insights
        events = [
            # High frequency access
            {"event_type": "search", "target_id": "popular_mem"},
            {"event_type": "search", "target_id": "popular_mem"},
            {"event_type": "search", "target_id": "popular_mem"},
            {"event_type": "search", "target_id": "popular_mem"},
            {"event_type": "search", "target_id": "popular_mem"},
            # Knowledge gaps
            {"event_type": "search_complete", "metadata": {"query": "gap1", "results_count": 0}},
            {"event_type": "search_complete", "metadata": {"query": "gap1", "results_count": 0}},
            {"event_type": "search_complete", "metadata": {"query": "gap1", "results_count": 0}},
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        insights = detector.insights()
        
        assert isinstance(insights, list)
        assert len(insights) > 0
        assert all(isinstance(i, str) for i in insights)
        # Should mention frequently accessed
        assert any("frequently accessed" in i.lower() for i in insights)


def test_stats_returns_usage_dict():
    """stats() returns dictionary with usage statistics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create various event types
        events = [
            {"event_type": "search", "metadata": {"query": "test"}},
            {"event_type": "search", "metadata": {"query": "test"}},
            {"event_type": "approve", "target_id": "mem_123"},
            {"event_type": "reject", "target_id": "mem_456"},
            {"event_type": "search_complete", "metadata": {"results_count": 3}},
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        stats = detector.stats()
        
        assert isinstance(stats, dict)
        assert stats["total_events"] == 5
        assert isinstance(stats["events_by_type"], dict)
        assert stats["events_by_type"]["search"] == 2
        assert stats["events_by_type"]["approve"] == 1
        assert stats["events_by_type"]["reject"] == 1
        assert "recent_activity_7d" in stats
        assert "last_updated" in stats


def test_json_metadata_parsing_edge_cases():
    """Pattern detection handles malformed JSON metadata gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Directly insert events with malformed metadata
        cursor = storage.conn.cursor()
        cursor.executemany("""
            INSERT INTO events (event_type, target_id, metadata, timestamp)
            VALUES (?, ?, ?, ?)
        """, [
            ("search_complete", None, "{invalid json", datetime.now(timezone.utc).isoformat()),
            ("search_complete", None, '{"query": null, "results_count": 0}', datetime.now(timezone.utc).isoformat()),
            ("search", None, "", datetime.now(timezone.utc).isoformat()),
            ("search", None, None, datetime.now(timezone.utc).isoformat()),
        ])
        storage.conn.commit()
        
        detector = PatternDetector(storage)
        # Should not crash
        patterns = detector.detect()
        insights = detector.insights()
        stats = detector.stats()
        
        assert isinstance(patterns, list)
        assert isinstance(insights, list) 
        assert isinstance(stats, dict)


def test_pattern_storage():
    """Detected patterns are stored in the patterns table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create events that will generate a pattern
        events = [
            {"event_type": "search", "target_id": "mem_123"},
            {"event_type": "search", "target_id": "mem_123"},
            {"event_type": "search", "target_id": "mem_123"},
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        patterns = detector.detect()
        
        # Check patterns were stored
        cursor = storage.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM patterns")
        count = cursor.fetchone()[0]
        assert count == len(patterns)
        
        # Verify stored pattern data
        cursor.execute("SELECT pattern_type, name, confidence FROM patterns")
        stored = cursor.fetchone()
        assert stored[0] == "frequency"
        assert "mem_123" in stored[1]
        assert stored[2] == 0.3


def test_null_and_empty_query_handling():
    """Pattern detection skips null/empty queries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        # Create events with null/empty queries
        events = [
            {"event_type": "search", "metadata": {"query": ""}},
            {"event_type": "search", "metadata": {"query": ""}},
            {"event_type": "search", "metadata": {"query": ""}},
            {"event_type": "search", "metadata": {"query": None}},
            {"event_type": "search", "metadata": {"query": None}},
            {"event_type": "search", "metadata": {"query": None}},
            {"event_type": "search", "metadata": {}},  # No query key
            {"event_type": "search", "metadata": {}},
            {"event_type": "search", "metadata": {}},
        ]
        create_test_events(storage, events)
        
        detector = PatternDetector(storage)
        
        # Should not detect patterns for empty/null queries
        temporal_patterns = detector.detect_temporal_patterns()
        assert len(temporal_patterns) == 0
        
        gap_patterns = detector.detect_knowledge_gaps() 
        assert len(gap_patterns) == 0