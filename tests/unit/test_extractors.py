"""Tests for memory extractors."""

import pytest
from memkoshi.extractors.base import MemoryExtractor
from memkoshi.extractors.hybrid import HybridExtractor
from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence


def test_memory_extractor_is_abstract():
    """MemoryExtractor is abstract and cannot be instantiated."""
    with pytest.raises(TypeError):
        MemoryExtractor()


def test_hybrid_extractor_can_be_instantiated():
    """HybridExtractor can be instantiated."""
    extractor = HybridExtractor()
    assert extractor is not None


def test_hybrid_extractor_initialize():
    """HybridExtractor can be initialized."""
    extractor = HybridExtractor()
    extractor.initialize()
    # Should complete without errors


def test_hybrid_extractor_empty_input():
    """HybridExtractor handles empty input gracefully."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    # Empty string
    memories = extractor.extract_memories("")
    assert memories == []
    
    # None should also work
    memories = extractor.extract_memories(None)
    assert memories == []


def test_hybrid_extractor_no_matches():
    """HybridExtractor returns empty list when no patterns match."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = "The weather is nice today. Birds are singing."
    memories = extractor.extract_memories(text)
    assert memories == []


def test_hybrid_extractor_decision_patterns():
    """HybridExtractor extracts decision patterns."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = "After careful consideration, I decided to use Python for this project. We also chose pytest as the testing framework."
    memories = extractor.extract_memories(text)
    
    assert len(memories) >= 1
    # Check first memory
    memory = memories[0]
    assert memory.category == MemoryCategory.EVENTS
    assert "decided" in memory.content or "chose" in memory.content
    assert memory.confidence in [MemoryConfidence.HIGH, MemoryConfidence.MEDIUM]
    assert memory.id.startswith("mem_")
    assert len(memory.title) <= 60
    assert memory.abstract == memory.content  # Full sentence as abstract


def test_hybrid_extractor_preference_patterns():
    """HybridExtractor extracts preference patterns."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = "I prefer using black for code formatting. I always use type hints in Python. I never use global variables."
    memories = extractor.extract_memories(text)
    
    assert len(memories) >= 2
    for memory in memories:
        assert memory.category == MemoryCategory.PREFERENCES
        assert any(keyword in memory.content.lower() for keyword in ["prefer", "always", "never"])


def test_hybrid_extractor_entity_patterns():
    """HybridExtractor extracts entity patterns."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = 'Working on "Project Phoenix" with the team. The "SuperCorp API" is integrated now.'
    memories = extractor.extract_memories(text)
    
    assert len(memories) >= 1
    # At least one should be categorized as entity
    entity_memories = [m for m in memories if m.category == MemoryCategory.ENTITIES]
    assert len(entity_memories) >= 1


def test_hybrid_extractor_problem_solution_patterns():
    """HybridExtractor extracts problem-solution patterns."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = "The bug was a race condition in the async handler. We fixed it by adding proper locking. I learned that mutex is essential for shared state."
    memories = extractor.extract_memories(text)
    
    assert len(memories) >= 1
    case_memories = [m for m in memories if m.category == MemoryCategory.CASES]
    assert len(case_memories) >= 1
    assert any("fixed" in m.content or "bug" in m.content or "learned" in m.content for m in case_memories)


def test_hybrid_extractor_process_patterns():
    """HybridExtractor extracts process patterns."""  
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = "My workflow is to write tests first, then implement. The process is: step 1 - analyze requirements, step 2 - design API."
    memories = extractor.extract_memories(text)
    
    assert len(memories) >= 1
    pattern_memories = [m for m in memories if m.category == MemoryCategory.PATTERNS]
    assert len(pattern_memories) >= 1


def test_hybrid_extractor_multiple_matches_in_sentence():
    """HybridExtractor handles sentences with multiple pattern matches."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = "I decided to always use pytest for testing because I prefer its simple syntax."
    memories = extractor.extract_memories(text)
    
    # Should extract at least one memory
    assert len(memories) >= 1
    # The primary pattern should determine the category


def test_hybrid_extractor_deduplication_same_sentence():
    """HybridExtractor doesn't duplicate memories from the same sentence."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    # Same sentence appears twice
    text = "I prefer Python. I prefer Python."
    memories = extractor.extract_memories(text)
    
    # Should have unique IDs based on content hash
    ids = [m.id for m in memories]
    # If same content, same ID
    if len(memories) == 2 and memories[0].content == memories[1].content:
        assert memories[0].id == memories[1].id


def test_hybrid_extractor_confidence_levels():
    """HybridExtractor assigns appropriate confidence levels."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    # High confidence
    text_high = "I decided to use Rust for system programming."
    memories = extractor.extract_memories(text_high)
    assert len(memories) >= 1
    assert memories[0].confidence == MemoryConfidence.HIGH
    
    # Medium confidence (contextual, no strong markers)  
    text_medium = "Python is useful for data science tasks."
    memories = extractor.extract_memories(text_medium)
    # May or may not extract, but if it does, should be medium
    
    # Test with explicit medium markers
    text_medium2 = "I usually prefer tabs over spaces."
    memories = extractor.extract_memories(text_medium2)
    if memories:
        assert memories[0].confidence == MemoryConfidence.MEDIUM


def test_hybrid_extractor_memory_structure():
    """HybridExtractor creates properly structured memories."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    text = "I decided to implement caching to improve performance."
    memories = extractor.extract_memories(text)
    
    assert len(memories) == 1
    memory = memories[0]
    
    # Check all required fields
    assert memory.id.startswith("mem_")
    assert len(memory.id) == 12  # mem_ + 8 chars
    assert memory.category == MemoryCategory.EVENTS
    assert len(memory.topic) > 0
    assert len(memory.title) > 0
    assert len(memory.title) <= 60
    assert memory.abstract == memory.content
    assert memory.content == "I decided to implement caching to improve performance."
    assert memory.confidence is not None
    assert memory.source_sessions == []  # No session context in simple text extraction
    assert memory.source_quotes == []  # No quotes in simple extraction


def test_hybrid_extractor_minimum_content_length():
    """HybridExtractor only extracts from sentences with sufficient content."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    # Too short - less than 20 chars
    text = "I prefer X."  # 11 chars
    memories = extractor.extract_memories(text)
    assert memories == []
    
    # Just long enough
    text = "I prefer using Python for scripting."  # > 20 chars
    memories = extractor.extract_memories(text)
    assert len(memories) >= 1


def test_hybrid_extractor_preference_patterns_expanded():
    """Test expanded preference patterns."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    # Test various preference patterns
    texts = [
        "He prefers Docker over VMs for containerization.",
        "The customer prefers on-premise solutions to cloud hosting.",
        "Our client prefers quarterly billing cycles.",
        "The user prefers dark mode interfaces.",
        "We like using TypeScript for large projects.",
        "I like the simplicity of Go's error handling.",
        "The team likes having daily standups.",
        "Python is our favorite language for data analysis.",
        "VSCode is my go-to editor for development.",
        "Ubuntu is our default choice for servers."
    ]
    
    for text in texts:
        memories = extractor.extract_memories(text)
        assert len(memories) >= 1, f"Failed to extract from: {text}"
        assert memories[0].category == MemoryCategory.PREFERENCES
        assert len(memories[0].content) > 20


def test_hybrid_extractor_entity_patterns_expanded():
    """Test expanded entity patterns including people, companies, products."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    # Test entity extraction
    texts = [
        "JR will handle sales for the northeast region.",
        "Haseeb handles technical architecture decisions.",
        "We partnered with a company called TechCorp.",
        "Our client Microsoft requested additional features.",
        "The customer Amazon wants faster delivery.",
        "Our partner Google provides the infrastructure.",
        "The system is built with React and Node.js.",
        "It's powered by PostgreSQL for data persistence.",
        "The service costs $5000 per month.",
        "Pricing starts at $99 per user per seat."
    ]
    
    for text in texts:
        memories = extractor.extract_memories(text)
        assert len(memories) >= 1, f"Failed to extract from: {text}"
        assert memories[0].category == MemoryCategory.ENTITIES


def test_hybrid_extractor_event_patterns_expanded():
    """Test expanded event patterns."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    texts = [
        "We launched the new feature last Tuesday.",
        "The team shipped version 2.0 yesterday.",
        "They released the patch this morning.",
        "We deployed the new release to production.",
        "The board agreed to the new pricing model.",
        "We committed to delivering by Q3.",
        "The client signed the contract yesterday.",
        "I had a meeting with the CTO about scaling.",
        "Sarah presented to the board of directors."
    ]
    
    for text in texts:
        memories = extractor.extract_memories(text)
        assert len(memories) >= 1, f"Failed to extract from: {text}"
        assert memories[0].category == MemoryCategory.EVENTS


def test_hybrid_extractor_case_patterns_expanded():
    """Test expanded case patterns."""
    extractor = HybridExtractor()
    extractor.initialize()
    
    texts = [
        "The root cause was a missing null check.",
        "The issue was caused by incorrect caching.",
        "Performance degraded because of a memory leak.",
        "The workaround is to restart the service daily.",
        "A temporary fix is to increase the timeout.",
        "We applied a hotfix to bypass validation.",
        "We discovered that the API had rate limits.",
        "The team realized that scaling was needed.",
        "It turns out the database was misconfigured."
    ]
    
    for text in texts:
        memories = extractor.extract_memories(text)
        assert len(memories) >= 1, f"Failed to extract from: {text}"
        assert memories[0].category == MemoryCategory.CASES
