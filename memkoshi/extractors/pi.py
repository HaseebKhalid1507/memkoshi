"""Pi-based memory extractor — uses pi agent's OAuth auth, no API key needed."""

import subprocess
import json
import hashlib
import re
import logging
from typing import List, Optional
from datetime import datetime, timezone

from .base import MemoryExtractor
from ..core.memory import Memory, MemoryCategory, MemoryConfidence

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = 'Extract memories from this session log as a JSON array. This is a raw agent session log with USER messages, ASSISTANT responses, and tool calls. Find: decisions made, preferences stated, people/companies mentioned, bugs fixed, processes defined. Categories: events/preferences/entities/cases/patterns. Confidence: high/medium/low. Each: {"category":"...","topic":"short-topic","title":"key fact","abstract":"one sentence","content":"full context with reasoning","confidence":"...","source_quotes":["exact quote from log"],"related_topics":["..."]}. ONLY JSON array, no markdown. Session log: '

CATEGORY_MAP = {
    "events": MemoryCategory.EVENTS,
    "preferences": MemoryCategory.PREFERENCES,
    "entities": MemoryCategory.ENTITIES,
    "cases": MemoryCategory.CASES,
    "patterns": MemoryCategory.PATTERNS,
}

CONFIDENCE_MAP = {
    "high": MemoryConfidence.HIGH,
    "medium": MemoryConfidence.MEDIUM,
    "low": MemoryConfidence.LOW,
}


class PiExtractor(MemoryExtractor):
    """Extract memories using pi agent (OAuth auth, no API key needed)."""

    def __init__(self, model: Optional[str] = None, timeout: int = 120):
        """Initialize pi extractor.
        
        Args:
            model: Model to use (default: pi's default model).
            timeout: Seconds to wait for pi response.
        """
        self.model = model
        self.timeout = timeout
        self._pi_available = False

    def initialize(self) -> None:
        """Check pi is available."""
        try:
            result = subprocess.run(
                ["pi", "--help"],
                capture_output=True, text=True, timeout=10
            )
            self._pi_available = result.returncode == 0
            if not self._pi_available:
                logger.warning("pi command not available")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._pi_available = False
            logger.warning("pi command not found")

    def extract_memories(self, text: str) -> List[Memory]:
        """Extract memories by sending text to pi."""
        if not text or not text.strip():
            return []

        if not self._pi_available:
            logger.error("pi not available — falling back would need hybrid extractor")
            return []

        # Chunk long texts
        chunks = self._chunk_text(text, max_chars=6000)
        all_memories = []
        seen_titles = set()

        for chunk in chunks:
            memories = self._extract_chunk(chunk)
            # Deduplicate across chunks
            for mem in memories:
                title_key = mem.title.strip().lower()
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_memories.append(mem)

        return all_memories

    def _extract_chunk(self, text: str) -> List[Memory]:
        """Extract memories from a single chunk via pi."""
        # Pass prompt + text as argument (faster than stdin)
        prompt = EXTRACTION_PROMPT + '"' + text.replace('"', '\\"')[:5000] + '"'

        # Build command
        cmd = ["pi", "-p", "--no-session", prompt]
        if self.model:
            cmd.insert(3, "--model")
            cmd.insert(4, self.model)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=None,  # Inherit current env (pi uses its own auth)
            )

            if result.returncode != 0:
                logger.error(f"pi failed: {result.stderr[:200]}")
                return []

            return self._parse_response(result.stdout)

        except subprocess.TimeoutExpired:
            logger.error(f"pi timed out after {self.timeout}s")
            return []
        except Exception as e:
            logger.error(f"pi extraction failed: {e}")
            return []

    def _parse_response(self, response: str) -> List[Memory]:
        """Parse pi's response into Memory objects."""
        # Try to extract JSON from response
        json_str = self._extract_json(response)
        if not json_str:
            return []

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from pi response")
            return []

        if not isinstance(data, list):
            data = [data]

        memories = []
        for item in data:
            try:
                mem = self._item_to_memory(item)
                if mem:
                    memories.append(mem)
            except Exception as e:
                logger.warning(f"Failed to create memory from item: {e}")

        return memories

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON array from response text."""
        # Try raw parse first
        text = text.strip()
        if text.startswith("["):
            return text

        # Try markdown code block
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Try finding array in text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return match.group(0)

        return None

    def _item_to_memory(self, item: dict) -> Optional[Memory]:
        """Convert a parsed dict to a Memory object."""
        category = CATEGORY_MAP.get(item.get("category", ""), MemoryCategory.PATTERNS)
        confidence = CONFIDENCE_MAP.get(item.get("confidence", "medium"), MemoryConfidence.MEDIUM)

        title = str(item.get("title", ""))[:256]
        abstract = str(item.get("abstract", title))[:512]
        content = str(item.get("content", abstract))
        topic = str(item.get("topic", "imported"))[:128]

        if not title or len(title) < 3:
            return None
        if not content or len(content) < 5:
            content = abstract if abstract else title

        mem_id = "mem_" + hashlib.sha256(title.encode()).hexdigest()[:8]

        return Memory(
            id=mem_id,
            category=category,
            topic=topic,
            title=title,
            abstract=abstract,
            content=content,
            confidence=confidence,
            source_quotes=item.get("source_quotes", []),
            related_topics=item.get("related_topics", []),
            tags=item.get("related_topics", []),
            created=datetime.now(timezone.utc),
        )

    def _chunk_text(self, text: str, max_chars: int = 6000) -> List[str]:
        """Split text into chunks for processing."""
        if len(text) <= max_chars:
            return [text]

        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text)
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) > max_chars and current:
                chunks.append(current.strip())
                current = sentence
            else:
                current += " " + sentence if current else sentence

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text[:max_chars]]
