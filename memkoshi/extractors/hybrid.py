"""Hybrid extractor - rule-based pattern matching only."""

import re
import hashlib
from typing import List, Optional, Tuple
from .base import MemoryExtractor
from ..core.memory import Memory, MemoryCategory, MemoryConfidence


class HybridExtractor(MemoryExtractor):
    """Rule-based memory extractor (no ML dependencies)."""
    
    def __init__(self):
        self.patterns = {}
    
    def initialize(self) -> None:
        """Initialize rule patterns for memory extraction."""
        
        # Define patterns for each category
        # Order matters for tie-breaking - CASES before ENTITIES
        self.patterns = {
            MemoryCategory.EVENTS: [
                r'\b(decided|chose|picked|went with|will use)\b',
                r'\b(launched|shipped|released|deployed)\b',
                r'\b(agreed to|agreed that|committed to|signed)\b',
                r'\b(meeting with|demo\'d|presented to|presented)\b',  # More flexible demo pattern
                r'\bsuggested\s+(we|that|to)\b',
                r'\bshould\s+(always|never)\b',
            ],
            MemoryCategory.PREFERENCES: [
                r'\b(prefers?|like to|always use|hate|never)\b',
                r'\bprefers?\s+\w+\s+(over|to)\b',  # "prefers X over Y" or "prefers X to Y"
                r'\b(customer|client|user)\s+prefers?\b',
                r'\b(we|I|team)\s+likes?\b',  # Fixed: likes? to match both like and likes
                r'\b(favorite|go-to|default choice)\b',
            ],
            MemoryCategory.CASES: [
                r'\b(fixed|solved|bug was|issue was|learned that)\b',
                r'\bThe bug\b',  # Add explicit bug pattern
                r'\bWe fixed\b',  # Add explicit fix pattern
                r'\b(?:the\s+)?root cause was\b',
                r'\bcaused by\b',
                r'\bbecause of (?:a|the)\b',
                r'\b(?:the\s+)?workaround is\b',
                r'\b(?:a\s+)?temporary fix\b',
                r'\b(?:a\s+)?hotfix\b',
                r'\b(?:we\s+)?discovered that\b',
                r'\b(?:we\s+)?realized that\b',
                r'\b(?:it\s+)?turns out\b',
            ],
            MemoryCategory.ENTITIES: [
                r'"[A-Z][^"]{2,}"',  # Quoted proper nouns
                r'\bProject\s+[A-Z][a-zA-Z]+\b',  # Project names
                r'\bAPI\b',  # API mentions
                r'\bSystem\s+[A-Z][a-zA-Z]+\b',  # System names
                r'\bFramework\s+[A-Z][a-zA-Z]+\b',  # Framework names
                # People patterns - more flexible name matching
                r'\b[A-Z][A-Za-z]*\s+(will handle|handles)\b',
                # Companies
                r'\bcompany called\s+\w+\b',
                r'\b(client|customer|partner)\s+[A-Z]\w*\b',
                # Products - case insensitive for product names
                r'\b(using|built with|powered by)\s+\w+\b',
                # Pricing
                r'\$\d+',
                r'\b\d+\s*(?:per|/)\s*(?:month|user)\b',
                r'\bcosts?\s+\$?\d+\b',
            ],
            MemoryCategory.PATTERNS: [
                r'\b(workflow|process is|step \d+|the approach)\b',
                r'\bMy workflow\b',  # Add explicit workflow pattern
                r'\bThe process\b',  # Add explicit process pattern
            ],
        }
    
    def extract_memories(self, text: str) -> List[Memory]:
        """Extract memories from text using pattern matching."""
        if not text:
            return []
        
        memories = []
        seen_sentences = set()
        sentences = self._split_sentences(text)
        
        for sentence in sentences:
            # Skip sentences that are too short
            if len(sentence) < 20:
                continue
            
            # Skip duplicate sentences
            normalized = sentence.strip().lower()
            if normalized in seen_sentences:
                continue
            seen_sentences.add(normalized)
                
            # Find matching category
            category = self._categorize_sentence(sentence)
            if category:
                memory = self._create_memory(sentence, category)
                if memory:
                    memories.append(memory)
        
        return memories
    
    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences while preserving the full sentence."""
        # Split on sentence boundaries but keep the sentence intact
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        # Filter empty strings and strip whitespace
        return [s.strip() for s in sentences if s.strip()]
    
    def _categorize_sentence(self, sentence: str) -> Optional[MemoryCategory]:
        """Determine category based on pattern matching."""
        best_category = None
        best_score = 0
        
        # Track scores for all categories
        category_scores = {}
        
        for category, patterns in self.patterns.items():
            score = 0
            for pattern in patterns:
                # Special handling for entity patterns - some are case insensitive
                if category == MemoryCategory.ENTITIES and any(keyword in pattern for keyword in ['using', 'built with', 'powered by', 'company called']):
                    flags = re.IGNORECASE
                else:
                    flags = re.IGNORECASE if category != MemoryCategory.ENTITIES else 0
                    
                if re.search(pattern, sentence, flags):
                    score += 1
            
            category_scores[category] = score
            
            if score > best_score:
                best_score = score
                best_category = category
                
        # Special tie-breaking: prefer CASES over ENTITIES when scores are equal
        if (best_score > 0 and 
            category_scores.get(MemoryCategory.CASES, 0) == best_score and
            category_scores.get(MemoryCategory.ENTITIES, 0) == best_score):
            best_category = MemoryCategory.CASES
        
        return best_category if best_score > 0 else None
    
    def _create_memory(self, sentence: str, category: MemoryCategory) -> Memory:
        """Create a Memory object from a sentence."""
        # Generate ID from content hash
        memory_id = "mem_" + hashlib.sha256(sentence.encode()).hexdigest()[:8]
        
        # Extract title (first 60 chars max)
        title = sentence[:60] if len(sentence) <= 60 else sentence[:57] + "..."
        
        # Full sentence as both abstract and content
        abstract = sentence
        content = sentence
        
        # Derive topic from category and key nouns
        topic = self._extract_topic(sentence, category)
        
        # Assess confidence
        confidence = self._assess_confidence(sentence, category)
        
        return Memory(
            id=memory_id,
            category=category,
            topic=topic,
            title=title,
            abstract=abstract,
            content=content,
            confidence=confidence,
            source_sessions=[],  # No session context in text extraction
            source_quotes=[]     # No quotes in simple extraction
        )
    
    def _extract_topic(self, sentence: str, category: MemoryCategory) -> str:
        """Extract topic from sentence based on category."""
        # Simple approach: extract key noun after the pattern
        if category == MemoryCategory.EVENTS:
            # Look for what was decided/chosen
            match = re.search(r'(decided|chose|picked|went with|will use)\s+(?:to\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(2).lower()
            # Look for what was launched/shipped
            match = re.search(r'(launched|shipped|released|deployed)\s+(?:the\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(2).lower()
            # Look for what was agreed/committed
            match = re.search(r'(agreed to|agreed that|committed to|signed|suggested)\s+(?:the\s+|we\s+|that\s+|to\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(2).lower()
            # Look for meeting/demo context - more flexible
            match = re.search(r'(meeting with|demo\'d|presented to|presented)\s+(?:the\s+)?(?:to\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(2).lower()
        
        elif category == MemoryCategory.PREFERENCES:
            # Look for what is preferred
            match = re.search(r'(prefers?|like to|always use|hate|never)\s+(?:using\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(2).lower()
            # Look for what is liked
            match = re.search(r'likes?\s+(?:having\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(1).lower()
            # Look for favorite/go-to/default
            match = re.search(r'(favorite|go-to|default choice)\s+(?:for\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(2).lower()
                
        elif category == MemoryCategory.ENTITIES:
            # Extract the entity name
            # Try quoted strings first
            match = re.search(r'"([^"]+)"', sentence)
            if match:
                return match.group(1).lower()
            # Try specific entity patterns
            match = re.search(r'(Project|API|System|Framework)\s+([A-Z][a-zA-Z]+)', sentence)
            if match:
                return match.group(2).lower()
            # People names - more flexible
            match = re.search(r'(\b[A-Z][A-Za-z]*)\s+(?:will handle|handles)', sentence)
            if match:
                return match.group(1).lower()
            # Company names
            match = re.search(r'(?:client|customer|partner)\s+([A-Z]\w*)', sentence)
            if match:
                return match.group(1).lower()
            # Company called pattern
            match = re.search(r'company called\s+(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(1).lower()
            # Products
            match = re.search(r'(?:using|built with|powered by)\s+(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(1).lower()
            # Pricing
            match = re.search(r'\$(\d+)', sentence)
            if match:
                return f"price_{match.group(1)}"
            # Generic API mention
            if re.search(r'\bAPI\b', sentence):
                return "api"
                
        elif category == MemoryCategory.CASES:
            # Look for what was fixed/solved
            match = re.search(r'(fixed|solved)\s+(?:it|a|the)?\s*(?:by)?\s*(\w+)?', sentence, re.IGNORECASE)
            if match and match.group(2):
                return match.group(2).lower()
            # Look for bug/issue type
            match = re.search(r'(bug|issue)\s+(?:was)?\s*(?:a)?\s*(\w+)', sentence, re.IGNORECASE)
            if match and match.group(2):
                return match.group(2).lower()
            # Root cause patterns
            match = re.search(r'root cause was\s+(?:a\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(1).lower()
            # Workaround patterns
            match = re.search(r'workaround is\s+(?:to\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(1).lower()
            # Discovery patterns
            match = re.search(r'(?:discovered|realized)\s+(?:that)?\s+(?:the\s+)?(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(1).lower()
            # Learned pattern
            match = re.search(r'learned\s+(?:that)?\s+(\w+)', sentence, re.IGNORECASE)
            if match:
                return match.group(1).lower()
                
        elif category == MemoryCategory.PATTERNS:
            # Extract workflow/process name
            match = re.search(r'(workflow|process|approach)\s+(?:is|for)?\s*(?:to\s+)?(\w+)', sentence, re.IGNORECASE)
            if match and match.group(2):
                return match.group(2).lower()
        
        # Default: first few words
        words = sentence.lower().split()[:3]
        return " ".join(words)
    
    def _assess_confidence(self, sentence: str, category: MemoryCategory) -> MemoryConfidence:
        """Assess confidence based on language markers."""
        sentence_lower = sentence.lower()
        
        # High confidence markers
        high_markers = ['decided', 'chose', 'will use', 'always', 'never', 'definitely', 'confirmed', 
                       'launched', 'shipped', 'released', 'deployed', 'agreed to', 'agreed that', 'committed to', 'signed', 'suggested', 'should always', 'should never']
        if any(marker in sentence_lower for marker in high_markers):
            return MemoryConfidence.HIGH
            
        # Low confidence markers
        low_markers = ['maybe', 'possibly', 'might', 'could', 'unsure', 'unclear']
        if any(marker in sentence_lower for marker in low_markers):
            return MemoryConfidence.LOW
            
        # Default to medium for contextual matches
        return MemoryConfidence.MEDIUM
