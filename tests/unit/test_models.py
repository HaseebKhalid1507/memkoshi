"""Tests for core data models."""

import pytest
from datetime import datetime
from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence, StagedMemory
from memkoshi.core.session import SessionSummary, Session
from memkoshi.core.context import ContextTier, BootContext


def test_memory_creation_with_required_fields():
    """Memory can be created with all required fields."""
    memory = Memory(
        id="mem_12345678",
        category=MemoryCategory.PREFERENCES,
        topic="test topic",
        title="Test Title",
        abstract="Test abstract",
        content="Test content",
        confidence=MemoryConfidence.HIGH
    )
    
    assert memory.id == "mem_12345678"
    assert memory.category == MemoryCategory.PREFERENCES
    assert memory.topic == "test topic"
    assert memory.title == "Test Title"
    assert memory.abstract == "Test abstract"
    assert memory.content == "Test content"
    assert memory.confidence == MemoryConfidence.HIGH
    assert isinstance(memory.created, datetime)


def test_memory_category_enum():
    """MemoryCategory enum has expected values."""
    assert MemoryCategory.PREFERENCES == "preferences"
    assert MemoryCategory.ENTITIES == "entities"
    assert MemoryCategory.EVENTS == "events"
    assert MemoryCategory.CASES == "cases"
    assert MemoryCategory.PATTERNS == "patterns"


def test_memory_confidence_enum():
    """MemoryConfidence enum has expected values."""
    assert MemoryConfidence.HIGH == "high"
    assert MemoryConfidence.MEDIUM == "medium"
    assert MemoryConfidence.LOW == "low"


def test_staged_memory_creation():
    """StagedMemory can be created and has staging-specific fields."""
    staged = StagedMemory(
        id="mem_87654321",
        category=MemoryCategory.EVENTS,
        topic="test event",
        title="Test Event",
        abstract="Test event abstract",
        content="Test event content",
        confidence=MemoryConfidence.MEDIUM
    )
    
    assert staged.id == "mem_87654321"
    assert staged.review_status == "pending"
    assert staged.reviewer_notes is None
    assert isinstance(staged.staged_at, datetime)


def test_session_summary_creation():
    """SessionSummary can be created with required fields."""
    session_summary = SessionSummary(
        id="S123",
        started_at=datetime.now(),
        conversation_summary="Test conversation summary"
    )
    
    assert session_summary.id == "S123"
    assert isinstance(session_summary.started_at, datetime)
    assert session_summary.conversation_summary == "Test conversation summary"
    assert session_summary.ended_at is None
    assert session_summary.key_decisions == []
    assert session_summary.tools_used == []
    assert session_summary.files_modified == []
    assert session_summary.productivity_score is None
    assert session_summary.insight_count == 0
    assert session_summary.decision_count == 0
    assert session_summary.agent_version == "unknown"
    assert session_summary.extraction_version == "1.0"


def test_session_creation():
    """Session can be created with a SessionSummary."""
    session_summary = SessionSummary(
        id="S456",
        started_at=datetime.now(),
        conversation_summary="Another test session"
    )
    
    session = Session(
        summary=session_summary
    )
    
    assert session.summary.id == "S456"
    assert session.raw_messages == []
    assert session.compaction_data is None
    assert session.extracted_memories == []


def test_context_tier_creation():
    """ContextTier can be created with required fields."""
    tier = ContextTier(name="test-tier")
    
    assert tier.name == "test-tier"
    assert tier.size_limit is None
    assert tier.rotation_policy is None
    assert tier.auto_archive is True


def test_boot_context_creation():
    """BootContext can be created with default values."""
    context = BootContext()
    
    assert context.handoff is None
    assert context.session_brief is None
    assert context.checkpoint is None
    assert context.recent_sessions == []
    assert context.active_projects == []
    assert context.current_tasks == []
    assert context.behavioral_hints == []
    assert context.improvement_areas == []
    assert context.staged_memories_count == 0
    assert context.last_evolution_run is None
    assert isinstance(context.loaded_at, datetime)
    assert context.total_size_bytes == 0
    assert context.tier_breakdown == {}