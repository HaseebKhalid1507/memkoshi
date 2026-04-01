"""Tests for the API extractor."""

import json
import sys
import pytest
from unittest.mock import Mock, MagicMock, patch
from memkoshi.extractors.api import APIExtractor
from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence


class TestAPIExtractor:
    """Test API-based memory extractor."""
    
    def test_init_default_provider(self):
        """Test initialization with default provider."""
        extractor = APIExtractor()
        assert extractor.provider == "anthropic"
        assert extractor.model == "claude-3-5-sonnet-20241022"
        assert extractor.api_key is None
    
    def test_init_openai_provider(self):
        """Test initialization with OpenAI provider."""
        extractor = APIExtractor(provider="openai", api_key="test-key")
        assert extractor.provider == "openai"
        assert extractor.model == "gpt-4o-mini"
        assert extractor.api_key == "test-key"
    
    def test_init_custom_model(self):
        """Test initialization with custom model."""
        extractor = APIExtractor(model="gpt-4")
        assert extractor.model == "gpt-4"
    
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-api-key"})
    def test_initialize_with_env_key(self):
        """Test initialization gets API key from environment."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            extractor = APIExtractor()
            extractor.initialize()
            assert extractor.api_key == "env-api-key"
            mock_anthropic.Anthropic.assert_called_with(api_key="env-api-key")
    
    def test_initialize_no_api_key(self):
        """Test initialization fails without API key."""
        extractor = APIExtractor()
        with pytest.raises(ValueError, match="API key not found"):
            extractor.initialize()
    
    def test_extract_memories_anthropic(self):
        """Test memory extraction with Anthropic."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        # Mock API response
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps([
            {
                "category": "events",
                "topic": "project-launch",
                "title": "Launched the new API",
                "abstract": "The team successfully launched the new API yesterday.",
                "content": "We launched the new API yesterday after months of work.",
                "confidence": "high",
                "source_quotes": ["We launched the new API yesterday"],
                "related_topics": ["api", "launch"]
            }
        ]))]
        mock_client.messages.create.return_value = mock_response
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            memories = extractor.extract_memories("We launched the new API yesterday after months of work.")
            
            assert len(memories) == 1
            assert memories[0].category == MemoryCategory.EVENTS
            assert memories[0].topic == "project-launch"
            assert memories[0].title == "Launched the new API"
            assert memories[0].confidence == MemoryConfidence.HIGH
            assert memories[0].id.startswith("mem_")
            assert len(memories[0].id) == 12  # mem_ + 8 chars
            assert memories[0].tags == ["api", "launch"]
    
    def test_extract_memories_openai(self):
        """Test memory extraction with OpenAI."""
        # Mock openai module
        mock_openai = MagicMock()
        mock_client = Mock()
        mock_openai.OpenAI.return_value = mock_client
        
        # Mock API response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content=json.dumps([
            {
                "category": "preferences",
                "topic": "testing-approach",
                "title": "Team prefers TDD",
                "abstract": "The team strongly prefers test-driven development.",
                "content": "The team prefers TDD for all new features.",
                "confidence": "high",
                "source_quotes": ["The team prefers TDD"],
                "related_topics": ["testing", "tdd"]
            }
        ])))]
        mock_client.chat.completions.create.return_value = mock_response
        
        with patch.dict(sys.modules, {'openai': mock_openai}):
            # Test extraction
            extractor = APIExtractor(provider="openai", api_key="test-key")
            extractor.initialize()
            memories = extractor.extract_memories("The team prefers TDD for all new features.")
            
            assert len(memories) == 1
            assert memories[0].category == MemoryCategory.PREFERENCES
            assert memories[0].topic == "testing-approach"
            assert memories[0].title == "Team prefers TDD"
    
    def test_extract_memories_with_json_in_markdown(self):
        """Test extraction when JSON is wrapped in markdown code blocks."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        # Mock API response with markdown
        mock_response = Mock()
        mock_response.content = [Mock(text="""
Here are the extracted memories:

```json
[
    {
        "category": "entities",
        "topic": "john-doe",
        "title": "John handles backend development",
        "abstract": "John is responsible for backend development.",
        "content": "John handles all the backend development work.",
        "confidence": "high",
        "source_quotes": ["John handles all the backend development"],
        "related_topics": ["backend", "development"]
    }
]
```
        """)]
        mock_client.messages.create.return_value = mock_response
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            memories = extractor.extract_memories("John handles all the backend development work.")
            
            assert len(memories) == 1
            assert memories[0].category == MemoryCategory.ENTITIES
            assert memories[0].topic == "john-doe"
    
    def test_chunk_long_text(self):
        """Test chunking of long texts."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        # Create a long text that should be chunked
        long_text = "This is a test sentence. " * 300  # ~4800 chars
        
        # Mock API response
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps([]))]
        mock_client.messages.create.return_value = mock_response
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            memories = extractor.extract_memories(long_text)
            
            # Should have made multiple API calls
            assert mock_client.messages.create.call_count > 1
    
    def test_deduplicate_memories(self):
        """Test deduplication of memories across chunks."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        # Same memory returned in multiple chunks
        memory_data = {
            "category": "events",
            "topic": "meeting",
            "title": "Team meeting scheduled",
            "abstract": "Team meeting scheduled for Monday.",
            "content": "Team meeting scheduled for Monday at 10am.",
            "confidence": "high",
            "source_quotes": ["Team meeting scheduled for Monday"],
            "related_topics": ["meeting"]
        }
        
        # Create enough mock responses for all chunks
        mock_responses = []
        for _ in range(10):  # More than enough
            mock_response = Mock()
            mock_response.content = [Mock(text=json.dumps([memory_data]))]
            mock_responses.append(mock_response)
        
        mock_client.messages.create.side_effect = mock_responses
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction with chunked text
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            extractor.chunk_size = 100  # Force chunking
            memories = extractor.extract_memories("Team meeting scheduled for Monday at 10am. " * 10)
            
            # Should deduplicate to one memory
            assert len(memories) == 1
    
    def test_handle_api_error(self):
        """Test handling of API errors."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API Error")
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            
            with pytest.raises(Exception, match="API Error"):
                extractor.extract_memories("test text")
    
    def test_handle_invalid_json(self):
        """Test handling of invalid JSON response."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        # Mock invalid JSON response
        mock_response = Mock()
        mock_response.content = [Mock(text="This is not valid JSON")]
        mock_client.messages.create.return_value = mock_response
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            
            # Should handle gracefully and return empty list
            memories = extractor.extract_memories("test text")
            assert memories == []
    
    def test_memory_id_generation(self):
        """Test that memory IDs are generated correctly."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        # Mock API response
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps([
            {
                "category": "events",
                "topic": "test",
                "title": "Test event",
                "abstract": "Test abstract",
                "content": "Test content",
                "confidence": "high",
                "source_quotes": ["test"],
                "related_topics": []
            }
        ]))]
        mock_client.messages.create.return_value = mock_response
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            memories = extractor.extract_memories("test")
            
            # Check ID format
            assert memories[0].id.startswith("mem_")
            assert len(memories[0].id) == 12
            assert all(c in "0123456789abcdef" for c in memories[0].id[4:])
    
    def test_empty_text_extraction(self):
        """Test extraction with empty text."""
        extractor = APIExtractor(api_key="test-key")
        # Don't need to initialize for empty text
        
        memories = extractor.extract_memories("")
        assert memories == []
        
        memories = extractor.extract_memories("   ")
        assert memories == []
    
    def test_extract_not_initialized(self):
        """Test extraction fails if not initialized."""
        extractor = APIExtractor(api_key="test-key")
        
        with pytest.raises(RuntimeError, match="Extractor not initialized"):
            extractor.extract_memories("test text")
    
    def test_invalid_provider(self):
        """Test initialization with invalid provider."""
        with pytest.raises(ValueError, match="Unsupported provider"):
            APIExtractor(provider="invalid")
    
    def test_confidence_mapping(self):
        """Test mapping of confidence levels."""
        # Mock anthropic module
        mock_anthropic = MagicMock()
        mock_client = Mock()
        mock_anthropic.Anthropic.return_value = mock_client
        
        # Mock API response with different confidence levels
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps([
            {
                "category": "events",
                "topic": "test",
                "title": "Test 1",
                "abstract": "Test",
                "content": "Test",
                "confidence": "high",
                "source_quotes": ["test"],
                "related_topics": []
            },
            {
                "category": "events",
                "topic": "test",
                "title": "Test 2",
                "abstract": "Test",
                "content": "Test",
                "confidence": "medium",
                "source_quotes": ["test"],
                "related_topics": []
            },
            {
                "category": "events",
                "topic": "test",
                "title": "Test 3",
                "abstract": "Test",
                "content": "Test",
                "confidence": "low",
                "source_quotes": ["test"],
                "related_topics": []
            }
        ]))]
        mock_client.messages.create.return_value = mock_response
        
        with patch.dict(sys.modules, {'anthropic': mock_anthropic}):
            # Test extraction
            extractor = APIExtractor(api_key="test-key")
            extractor.initialize()
            memories = extractor.extract_memories("test")
            
            assert memories[0].confidence == MemoryConfidence.HIGH
            assert memories[1].confidence == MemoryConfidence.MEDIUM
            assert memories[2].confidence == MemoryConfidence.LOW
