"""Tests for evolution engine with session scoring and behavioral insights."""

import tempfile
import json
from datetime import datetime, timezone, timedelta
import pytest
from memkoshi.core.evolution import EvolutionScore, EvolutionEngine
from memkoshi.storage.sqlite import SQLiteBackend


def test_evolution_score_model():
    """EvolutionScore model validates correctly."""
    score = EvolutionScore(
        score=8.5,
        task_completion_rate=0.8,
        error_count=2,
        satisfaction_keywords={"positive": 5, "negative": 1},
        duration_minutes=45,
        memories_committed=3,
        memories_recalled=7,
        insights=["Good performance", "Low error rate"]
    )
    assert score.score == 8.5
    assert score.task_completion_rate == 0.8
    assert score.error_count == 2
    assert score.duration_minutes == 45
    assert len(score.insights) == 2


def test_evolution_score_validation():
    """EvolutionScore validates score range."""
    # Valid scores
    EvolutionScore(score=1.0)
    EvolutionScore(score=10.0)
    EvolutionScore(score=5.5)
    
    # Invalid scores should raise validation error
    with pytest.raises(ValueError):
        EvolutionScore(score=0.5)  # Below 1.0
    
    with pytest.raises(ValueError):
        EvolutionScore(score=11.0)  # Above 10.0


def test_evolution_engine_init():
    """EvolutionEngine initializes with storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        assert engine.storage == storage


def test_score_structured_basic():
    """Structured scoring with all fields provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        session_data = {
            "tasks_completed": 8,
            "tasks_attempted": 10,
            "errors": 1,
            "duration_minutes": 60,
            "memories_committed": 2,
            "memories_recalled": 3
        }
        
        score = engine.score_structured(session_data)
        
        # Score should be reasonable
        assert 1.0 <= score <= 10.0
        # With 80% completion, 1 error, should be good score
        assert score > 6.0


def test_score_structured_with_defaults():
    """Structured scoring handles missing fields with defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Minimal data
        session_data = {
            "tasks_completed": 5,
            # Missing: tasks_attempted, errors, duration_minutes, etc.
        }
        
        score = engine.score_structured(session_data)
        
        # Should not crash, should use defaults
        assert 1.0 <= score <= 10.0


def test_score_structured_perfect_session():
    """Perfect session gets high score."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        session_data = {
            "tasks_completed": 10,
            "tasks_attempted": 10,  # 100% completion
            "errors": 0,            # No errors
            "duration_minutes": 25,  # Efficient (bonus)
            "memories_committed": 5,
            "memories_recalled": 5
        }
        
        score = engine.score_structured(session_data)
        
        # Should get very high score
        assert score >= 9.0


def test_score_structured_poor_session():
    """Poor session gets low score."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        session_data = {
            "tasks_completed": 1,
            "tasks_attempted": 10,  # 10% completion
            "errors": 8,            # Many errors
            "duration_minutes": 180, # Too long (penalty)
            "memories_committed": 0,
            "memories_recalled": 0
        }
        
        score = engine.score_structured(session_data)
        
        # Should get low score
        assert score <= 3.0


def test_score_text_fallback_positive():
    """Text fallback detects positive keywords."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        text = """
        Great session! Completed the feature implementation successfully.
        Fixed the bug and deployed to production. Everything is working perfectly.
        Smooth process, excellent results.
        """
        
        result = engine.score_text_fallback(text)
        
        assert result["score"] > 5.0  # Positive text should score above average
        assert result["tasks_completed"] > 0
        assert result["satisfaction_keywords"]["positive"] > 0
        assert result["satisfaction_keywords"]["negative"] == 0


def test_score_text_fallback_negative():
    """Text fallback detects negative keywords."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        text = """
        Frustrated with this error. The system keeps crashing and failing.
        Stuck on this issue for hours. Very annoying and difficult to debug.
        Total waste of time.
        """
        
        result = engine.score_text_fallback(text)
        
        assert result["score"] < 5.0  # Negative text should score below average
        assert result["errors"] > 0
        assert result["satisfaction_keywords"]["negative"] > 0


def test_score_text_fallback_mixed():
    """Text fallback handles mixed positive/negative content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        text = """
        Started with some errors but managed to fix them. 
        Completed the main task successfully after some trouble.
        Good result in the end, though the process was a bit frustrating.
        """
        
        result = engine.score_text_fallback(text)
        
        assert 4.0 <= result["score"] <= 7.0  # Mixed should be middle range
        assert result["tasks_completed"] > 0
        assert result["errors"] > 0
        assert result["satisfaction_keywords"]["positive"] > 0
        assert result["satisfaction_keywords"]["negative"] > 0


def test_score_text_fallback_empty():
    """Text fallback handles empty string gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        result = engine.score_text_fallback("")
        
        assert result["score"] == 5.0  # Default neutral score
        assert result["tasks_completed"] == 0
        assert result["errors"] == 0


def test_score_dispatches_correctly():
    """score() method correctly dispatches to structured vs text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Test with dict input (structured)
        dict_input = {
            "tasks_completed": 5,
            "tasks_attempted": 6,
            "errors": 1
        }
        result1 = engine.score(dict_input)
        assert "score" in result1
        assert result1["tasks_completed"] == 5  # Original data preserved
        
        # Test with string input (text fallback)
        text_input = "Completed the task successfully"
        result2 = engine.score(text_input)
        assert "score" in result2
        assert result2["tasks_completed"] > 0  # Extracted from text


def test_session_storage():
    """Sessions are stored in database when session_id provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        session_data = {
            "tasks_completed": 7,
            "tasks_attempted": 8,
            "errors": 1,
            "duration_minutes": 45
        }
        
        # Score with session_id
        result = engine.score(session_data, session_id="test_session_123")
        
        # Verify stored in database
        cursor = storage.conn.cursor()
        cursor.execute("SELECT score, task_completion_rate, error_count FROM evolution_sessions WHERE session_id = ?", 
                      ("test_session_123",))
        row = cursor.fetchone()
        
        assert row is not None
        assert row[0] == result["score"]
        assert row[1] == 7/8  # task_completion_rate
        assert row[2] == 1    # error_count


def test_hints_with_sufficient_data():
    """hints() generates insights when enough sessions exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Create some high-scoring sessions
        for i in range(5):
            session_data = {
                "tasks_completed": 9,
                "tasks_attempted": 10,
                "errors": 0,
                "memories_committed": 3,
                "memories_recalled": 2
            }
            engine.score(session_data, session_id=f"high_{i}")
        
        # Create some low-scoring sessions
        for i in range(5):
            session_data = {
                "tasks_completed": 3,
                "tasks_attempted": 10,
                "errors": 5,
                "memories_committed": 0,
                "memories_recalled": 0
            }
            engine.score(session_data, session_id=f"low_{i}")
        
        # Get hints
        hints = engine.hints()
        
        assert isinstance(hints, list)
        assert len(hints) > 0
        assert all(isinstance(h, str) for h in hints)


def test_hints_with_insufficient_data():
    """hints() handles case with too few sessions gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Create only 2 sessions (less than typical threshold)
        engine.score({"tasks_completed": 5, "tasks_attempted": 5}, session_id="s1")
        engine.score({"tasks_completed": 3, "tasks_attempted": 5}, session_id="s2")
        
        hints = engine.hints()
        
        assert isinstance(hints, list)
        # Should get fallback message
        assert any("more session data" in h or "unavailable" in h or "still emerging" in h for h in hints)


def test_status_dashboard():
    """status() returns correct performance metrics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Create sessions with known scores
        engine.score({"tasks_completed": 10, "tasks_attempted": 10}, session_id="best")
        engine.score({"tasks_completed": 5, "tasks_attempted": 10}, session_id="avg")
        engine.score({"tasks_completed": 2, "tasks_attempted": 10}, session_id="poor")
        
        status = engine.status()
        
        assert isinstance(status, dict)
        assert status["recent_sessions_30d"] == 3
        assert 3.0 <= status["average_score_30d"] <= 7.0  # Should be middle range
        assert status["best_session"]["id"] == "best"
        assert status["best_session"]["score"] >= 8.0
        assert "trend_7d" in status
        assert "last_updated" in status


def test_score_bounds_enforcement():
    """Scores are always bounded between 1.0 and 10.0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Test extreme cases that might overflow
        
        # All failures - should still be at least 1.0
        bad_data = {
            "tasks_completed": 0,
            "tasks_attempted": 100,
            "errors": 50,
            "duration_minutes": 300
        }
        score1 = engine.score_structured(bad_data)
        assert score1 == 1.0
        
        # Extreme success - should cap at 10.0
        great_data = {
            "tasks_completed": 100,
            "tasks_attempted": 100,
            "errors": 0,
            "duration_minutes": 20,  # Very fast
            "memories_committed": 50,
            "memories_recalled": 50
        }
        score2 = engine.score_structured(great_data)
        assert abs(score2 - 10.0) <= 1.0


def test_duration_factor_applied():
    """Duration bonus/penalty is applied correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        base_data = {
            "tasks_completed": 5,
            "tasks_attempted": 10,
            "errors": 0,
            "memories_committed": 0,
            "memories_recalled": 0
        }
        
        # Quick session (< 30 min) gets bonus
        quick_data = {**base_data, "duration_minutes": 20}
        quick_score = engine.score_structured(quick_data)
        
        # Normal session
        normal_data = {**base_data, "duration_minutes": 60}
        normal_score = engine.score_structured(normal_data)
        
        # Long session (> 120 min) gets penalty
        long_data = {**base_data, "duration_minutes": 150}
        long_score = engine.score_structured(long_data)
        
        # Quick should score higher than normal
        assert quick_score > normal_score
        # Normal should score higher than long
        assert normal_score > long_score


def test_unicode_in_session_text():
    """Unicode in session text is handled properly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        text = """
        完成了任务 ✅ Successfully completed!
        Had some errors 错误 but fixed them.
        Great результат 🎉
        """
        
        # Should not crash
        result = engine.score_text_fallback(text)
        assert isinstance(result["score"], float)
        assert 1.0 <= result["score"] <= 10.0


def test_very_long_session_text():
    """Very long session text is handled without issues."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Generate 15K character text
        text = "Completed task successfully. " * 500  # ~15K chars
        
        # Should not crash or timeout
        result = engine.score_text_fallback(text)
        assert isinstance(result["score"], float)
        # Should detect many "completed" keywords
        assert result["tasks_completed"] > 100


def test_negative_numbers_clamped():
    """Negative numbers in structured scoring are handled properly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Negative values should be treated reasonably
        data = {
            "tasks_completed": -5,  # Invalid but should not crash
            "tasks_attempted": 10,
            "errors": -2,  # Invalid
            "duration_minutes": -30  # Invalid
        }
        
        # Should not crash
        score = engine.score_structured(data)
        assert 1.0 <= score <= 10.0


def test_generate_insights_sql_analysis():
    """generate_insights uses SQL to analyze high-performing sessions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Create high-scoring sessions with high completion rate (95%)
        for i in range(5):
            engine.score({
                "tasks_completed": 95,
                "tasks_attempted": 100,
                "errors": 0,
                "memories_committed": 5,
                "memories_recalled": 5
            }, session_id=f"high_{i}")
        
        # Create low-scoring sessions with low completion (30%)
        for i in range(5):
            engine.score({
                "tasks_completed": 3,
                "tasks_attempted": 10,  
                "errors": 5,
                "memories_committed": 0,
                "memories_recalled": 0
            }, session_id=f"low_{i}")
        
        insights = engine.generate_insights()
        
        assert len(insights) > 0
        # Should detect the completion rate difference
        assert any("completion" in i.lower() for i in insights)


def test_error_handling_on_score():
    """score() handles errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SQLiteBackend(tmpdir)
        storage.initialize()
        
        engine = EvolutionEngine(storage)
        
        # Test valid empty dict (should score 3.0, not error)
        result = engine.score({})
        assert result["score"] == 3.0
        
        # Close storage to simulate error during database storage
        storage.close()
        
        # Force error by trying to store session with closed storage
        result2 = engine.score({"tasks_completed": 5}, session_id="test")
        assert result2["score"] == 5.0
        assert "error" in result2