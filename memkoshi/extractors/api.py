"""API-based memory extractor using LLMs."""

import os
import json
import hashlib
from typing import List, Optional, Union
from .base import MemoryExtractor
from ..core.memory import Memory, MemoryCategory, MemoryConfidence


class APIExtractor(MemoryExtractor):
    """Memory extractor using LLM APIs (Anthropic/OpenAI)."""
    
    def __init__(self, provider: str = "anthropic", model: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize API extractor.
        
        Args:
            provider: "anthropic" or "openai"
            model: Model name (defaults to claude-3-5-sonnet-20241022 for anthropic, gpt-4o-mini for openai)
            api_key: API key (can also be set via env var)
        """
        if provider not in ["anthropic", "openai"]:
            raise ValueError(f"Unsupported provider: {provider}")
            
        self.provider = provider
        self.model = model or self._get_default_model(provider)
        self.api_key = api_key
        self.client = None
        self.chunk_size = 4000  # Characters per chunk
    
    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider."""
        if provider == "anthropic":
            return "claude-3-5-sonnet-20241022"
        else:  # openai
            return "gpt-4o-mini"
    
    def initialize(self) -> None:
        """Initialize API client."""
        # Get API key from parameter or environment
        if not self.api_key:
            env_var = "ANTHROPIC_API_KEY" if self.provider == "anthropic" else "OPENAI_API_KEY"
            self.api_key = os.getenv(env_var)
        
        if not self.api_key:
            raise ValueError(f"API key not found. Set {env_var} or pass api_key parameter.")
        
        # Initialize client (lazy import to avoid import errors in tests)
        if self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:  # openai
            import openai
            self.client = openai.OpenAI(api_key=self.api_key)
    
    def extract_memories(self, text: str) -> List[Memory]:
        """Extract memories from text using LLM."""
        if not text or not text.strip():
            return []
        
        if not self.client:
            raise RuntimeError("Extractor not initialized. Call initialize() first.")
        
        # Chunk long texts
        chunks = self._chunk_text(text)
        all_memories = []
        
        for chunk in chunks:
            try:
                memories = self._extract_from_chunk(chunk)
                all_memories.extend(memories)
            except Exception as e:
                # Re-raise API errors
                raise e
        
        # Deduplicate memories by title
        return self._deduplicate_memories(all_memories)
    
    def _chunk_text(self, text: str) -> List[str]:
        """Split text into chunks for API processing."""
        if len(text) <= self.chunk_size:
            return [text]
        
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end near chunk boundary
                for i in range(end, max(start, end - 200), -1):
                    if text[i-1] in '.!?' and i < len(text) and text[i] == ' ':
                        end = i
                        break
            
            chunks.append(text[start:end])
            start = end
        
        return chunks
    
    def _extract_from_chunk(self, chunk: str) -> List[Memory]:
        """Extract memories from a single chunk."""
        prompt = self._build_prompt(chunk)
        
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.content[0].text
        else:  # openai
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
        
        # Parse response
        return self._parse_response(content)
    
    def _build_prompt(self, text: str) -> str:
        """Build extraction prompt."""
        return f"""You are a memory extraction system. Extract structured memories from the following session log. This may be a raw agent session log with USER/ASSISTANT messages and tool calls (BASH, WRITE, EDIT, READ), or a plain text summary. Find all significant information worth remembering.

CATEGORIES:
- events: Decisions, milestones, agreements ("decided to", "launched", "agreed")
- preferences: Behavioral patterns, choices, likes/dislikes ("prefer", "always", "hate")
- entities: People, companies, projects, tools with context ("JR handles sales", "NovaPay is a client")
- cases: Problems and solutions, bugs and fixes, lessons learned ("fixed by", "root cause was", "learned that")
- patterns: Processes, workflows, methods ("the process is", "workflow", "step 1")

CONFIDENCE:
- high: Explicitly stated decisions or facts
- medium: Implied or contextual information
- low: Uncertain, speculative, or mentioned in passing

RULES:
- Only extract information explicitly present in the text
- Each memory must have a source quote from the original text
- Generate a short descriptive topic (1-3 words, lowercase, hyphenated)
- Title should be the key sentence/fact (max 100 chars)
- Abstract is a one-sentence summary
- Content is the full context with source quotes

Return a JSON array of memories:
[
  {{
    "category": "events|preferences|entities|cases|patterns",
    "topic": "short-topic",
    "title": "Key fact or decision",
    "abstract": "One sentence summary",
    "content": "Full context including source quotes",
    "confidence": "high|medium|low",
    "source_quotes": ["exact quote from text"],
    "related_topics": ["topic1", "topic2"]
  }}
]

TEXT TO EXTRACT FROM:
{text}"""
    
    def _parse_response(self, content: str) -> List[Memory]:
        """Parse LLM response into Memory objects."""
        try:
            # Try to parse as JSON directly
            memories_data = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            json_match = re.search(r'```json\s*\n(.*?)\n```', content, re.DOTALL)
            if json_match:
                try:
                    memories_data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    return []
            else:
                return []
        
        memories = []
        for data in memories_data:
            try:
                memory = self._create_memory_from_data(data)
                memories.append(memory)
            except Exception:
                # Skip invalid memories
                continue
        
        return memories
    
    def _create_memory_from_data(self, data: dict) -> Memory:
        """Create Memory object from parsed data."""
        # Generate ID from title
        memory_id = "mem_" + hashlib.sha256(data["title"].encode()).hexdigest()[:8]
        
        # Map string values to enums
        category = MemoryCategory(data["category"])
        confidence_map = {
            "high": MemoryConfidence.HIGH,
            "medium": MemoryConfidence.MEDIUM,
            "low": MemoryConfidence.LOW
        }
        confidence = confidence_map[data["confidence"]]
        
        return Memory(
            id=memory_id,
            category=category,
            topic=data["topic"],
            title=data["title"],
            abstract=data["abstract"],
            content=data["content"],
            confidence=confidence,
            source_quotes=data.get("source_quotes", []),
            tags=data.get("related_topics", [])
        )
    
    def _deduplicate_memories(self, memories: List[Memory]) -> List[Memory]:
        """Deduplicate memories by title."""
        seen_titles = set()
        unique_memories = []
        
        for memory in memories:
            if memory.title not in seen_titles:
                seen_titles.add(memory.title)
                unique_memories.append(memory)
        
        return unique_memories
