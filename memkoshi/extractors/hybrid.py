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
                r'\b(meeting with|demo\'d|presented to|presented)\b',
                r'\bsuggested\s+(we|that|to)\b',
                r'\bshould\s+(always|never)\b',
                # Trading events
                r'\b(BUY|SELL|BOUGHT|SOLD|CLOSED|OPENED|ENTERED|EXITED)\b',
                r'\bfirst trade\b',
                r'\b(position|order)\s+(filled|executed|cancelled|closed)\b',
                r'\bstarting fresh\b',
                r'\bday \d+\b',
            ],
            MemoryCategory.PREFERENCES: [
                r'\b(prefers?|like to|always use|hate|never)\b',
                r'\bprefers?\s+\w+\s+(over|to)\b',
                r'\b(customer|client|user)\s+prefers?\b',
                r'\b(we|I|team)\s+likes?\b',
                r'\b(favorite|go-to|default choice)\b',
                # Strategy preferences
                r'\b(anchor|conviction|conservative|aggressive)\b',
                r'\bmax\s+\d+%\s+(position|exposure|allocation)\b',
                r'\bnever\s+(fully|100%)\b',
                r'\balways\s+(keep|maintain|hold)\b',
            ],
            MemoryCategory.CASES: [
                r'\b(fixed|solved|bug was|issue was|learned that)\b',
                r'\bThe bug\b',
                r'\bWe fixed\b',
                r'\b(?:the\s+)?root cause was\b',
                r'\bcaused by\b',
                r'\bbecause of (?:a|the)\b',
                r'\b(?:the\s+)?workaround is\b',
                r'\b(?:a\s+)?temporary fix\b',
                r'\b(?:a\s+)?hotfix\b',
                r'\b(?:we\s+)?discovered that\b',
                r'\b(?:we\s+)?realized that\b',
                r'\b(?:it\s+)?turns out\b',
                # Trading lessons
                r'\blesson\b',
                r'\bmistake\b',
                r'\bshould have\b',
                r'\bnext time\b',
            ],
            MemoryCategory.ENTITIES: [
                r'"[A-Z][^"]{2,}"',  # Quoted proper nouns
                r'\bProject\s+[A-Z][a-zA-Z]+\b',
                r'\bSystem\s+[A-Z][a-zA-Z]+\b',
                r'\bFramework\s+[A-Z][a-zA-Z]+\b',
                # People
                r'\b[A-Z][A-Za-z]*\s+(will handle|handles)\b',
                # Companies/orgs
                r'\bcompany called\s+\w+\b',
                r'\b(client|customer|partner)\s+[A-Z]\w*\b',
                # Products (specific, not greedy)
                r'\b(built with|powered by)\s+[A-Z]\w+\b',
                # Pricing (specific contexts only, not bare $N)
                r'\b\d+\s*(?:per|/)\s*(?:month|user|seat)\b',
                r'\bcosts?\s+\$\d+\s+per\b',
                # API as explicit entity (not just any mention)
                r'\b\w+\s+API\b',
                # Companies/orgs by name (capitalized + action)
                r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:IPO|acquisition|merger|funding|valuation)\b',
                r'\b(?:acquired|bought|merged with|partnered with)\s+[A-Z]\w+\b',
            ],
            MemoryCategory.PATTERNS: [
                r'\b(workflow|process is|step \d+|the approach)\b',
                r'\bMy workflow\b',
                r'\bThe process\b',
                # Trading patterns
                r'\b(strategy|thesis|approach|playbook)\b',
                r'\b(regime|trend|consolidat|breakout|rejection)\b',
                r'\b(coiling|compressing|narrowing|expanding)\b',
                r'\bresistance\s+(at|held|rejected)\b',
                r'\bsupport\s+(at|held|bounced)\b',
            ],
        }
    
    # Patterns that indicate low-value content (timestamps, headers, raw data)
    NOISE_PATTERNS = [
        r'^\d{4}-\d{2}-\d{2}',              # Bare timestamps as content
        r'^#{1,3}\s',                         # Markdown headers
        r'^[\-\*]\s*$',                       # Empty list items
        r'^\|.*\|$',                           # Table rows
        r'^```',                               # Code fences
        r'^\s*\d+\.?\s*$',                    # Bare numbers
        r'^session\s+summary',                 # Session summary headers
        r'^portfolio\s+at\s+close',            # Portfolio dump headers
        r'\b\d+\s+replies\b',                 # Slack metadata
        r'^\s*[-=]{3,}\s*$',                   # Dividers
    ]

    def extract_memories(self, text: str) -> List[Memory]:
        """Extract memories from text using pattern matching with quality gate."""
        if not text:
            return []
        
        memories = []
        seen_sentences = set()
        seen_topics = {}  # topic -> best memory (dedup by topic)
        sentences = self._split_sentences(text)
        
        for sentence in sentences:
            # Quality gate: skip low-value content
            if not self._passes_quality_gate(sentence):
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
                    # Dedup by topic: keep the longer/richer memory per topic
                    key = f"{memory.category.value}:{memory.topic}"
                    if key in seen_topics:
                        existing = seen_topics[key]
                        if len(memory.content) > len(existing.content):
                            seen_topics[key] = memory
                    else:
                        seen_topics[key] = memory
        
        return list(seen_topics.values())
    
    def _passes_quality_gate(self, sentence: str) -> bool:
        """Filter out low-value sentences that shouldn't become memories."""
        stripped = sentence.strip()
        
        # Too short to be meaningful
        if len(stripped) < 25:
            return False
        
        # Too long — probably a data dump, not a discrete memory
        if len(stripped) > 500:
            return False
        
        # Mostly numbers/punctuation — likely raw data
        alpha_ratio = sum(1 for c in stripped if c.isalpha()) / max(len(stripped), 1)
        if alpha_ratio < 0.3:
            return False
        
        # Matches noise patterns
        for pattern in self.NOISE_PATTERNS:
            if re.search(pattern, stripped, re.IGNORECASE):
                return False
        
        # Too many numbers relative to words (likely a data row)
        words = stripped.split()
        num_count = sum(1 for w in words if re.match(r'^[\$\d,\.%\+\-]+$', w))
        if len(words) > 3 and num_count / len(words) > 0.6:
            return False
        
        return True
    
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
                # Entity patterns use case-sensitive matching by default
                if category == MemoryCategory.ENTITIES:
                    flags = 0
                else:
                    flags = re.IGNORECASE
                    
                if re.search(pattern, sentence, flags):
                    score += 1
            
            category_scores[category] = score
            
            if score > best_score:
                best_score = score
                best_category = category
        
        # Tie-breaking priority: preferences > cases > patterns > events > entities
        # This ensures "never do X" hits preferences, not events
        if best_score > 0:
            priority_order = [
                MemoryCategory.PREFERENCES,
                MemoryCategory.CASES, 
                MemoryCategory.PATTERNS,
                MemoryCategory.EVENTS,
                MemoryCategory.ENTITIES,
            ]
            for cat in priority_order:
                if category_scores.get(cat, 0) == best_score:
                    best_category = cat
                    break
        
        return best_category if best_score > 0 else None
    
    def _create_memory(self, sentence: str, category: MemoryCategory) -> Memory:
        """Create a Memory object from a sentence."""
        # Generate ID from content hash
        memory_id = "mem_" + hashlib.sha256(sentence.encode()).hexdigest()[:8]
        
        # Generate meaningful title (not just truncation)
        title = self._generate_title(sentence, category)
        
        # Abstract = condensed version, content = full
        abstract = self._generate_abstract(sentence)
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
            importance=self._score_importance(sentence, category, confidence),
            source_sessions=[],  # No session context in text extraction
            source_quotes=[]     # No quotes in simple extraction
        )
    
    # Stopwords for topic extraction — common words that don't make good topics
    STOPWORDS = frozenset({
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
        'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
        'as', 'into', 'through', 'during', 'before', 'after', 'above',
        'below', 'between', 'out', 'off', 'over', 'under', 'again',
        'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why',
        'how', 'all', 'both', 'each', 'few', 'more', 'most', 'other',
        'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 'just', 'because', 'but', 'and', 'or',
        'if', 'while', 'this', 'that', 'these', 'those', 'it', 'its',
        'i', 'me', 'my', 'we', 'our', 'you', 'your', 'he', 'she', 'they',
        'them', 'what', 'which', 'who', 'whom', 'up', 'about', 'also',
    })

    def _extract_topic(self, sentence: str, category: MemoryCategory) -> str:
        """Extract a meaningful topic from a sentence.
        
        Strategy: extract the most meaningful noun phrase, not regex on prices.
        Priority: known entities > quoted strings > capitalized phrases > key nouns.
        """
        # 1. Quoted strings — explicit entity references
        match = re.search(r'"([^"]{2,40})"', sentence)
        if match:
            return match.group(1).lower().strip()
        
        # 2. Known asset/ticker symbols (common in financial content)
        ticker_match = re.search(
            r'\b(BTC|ETH|SOL|AVAX|LINK|DOT|UNI|AAVE|ARB|DOGE|XRP|'
            r'QQQ|SPY|GLD|USO|XLE|AAPL|NVDA|TSLA|MSFT|AMZN|GOOG|META|'
            r'BTC/USD|ETH/USD|BTCUSD|ETHUSD|SOL/USD|SOLUSD)\b', 
            sentence, re.IGNORECASE
        )
        if ticker_match:
            return ticker_match.group(1).upper()
        
        # 3. Capitalized multi-word phrases (proper nouns, project names)
        cap_match = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', sentence)
        if cap_match:
            phrase = cap_match.group(1).strip()
            if len(phrase) > 3 and phrase.lower() not in self.STOPWORDS:
                return phrase.lower()
        
        # 4. Category-specific extraction
        topic = self._extract_topic_by_category(sentence, category)
        if topic:
            return topic
        
        # 5. Fallback: extract key nouns (longest non-stopword words)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', sentence)
        key_words = [w.lower() for w in words if w.lower() not in self.STOPWORDS]
        if key_words:
            # Pick the most "topical" — prefer longer, less common words
            key_words.sort(key=lambda w: len(w), reverse=True)
            return key_words[0]
        
        # 6. Last resort: first meaningful words
        words = [w for w in sentence.lower().split()[:5] if w not in self.STOPWORDS]
        return " ".join(words[:2]) if words else "unknown"
    
    def _extract_topic_by_category(self, sentence: str, category: MemoryCategory) -> str:
        """Category-specific topic extraction as fallback."""
        if category == MemoryCategory.EVENTS:
            for pattern in [
                r'(decided|chose|went with|will use)\s+(?:to\s+)?(\w{3,})',
                r'(launched|shipped|released|deployed)\s+(?:the\s+)?(\w{3,})',
                r'(agreed|committed|signed)\s+(?:to\s+|that\s+)?(\w{3,})',
            ]:
                match = re.search(pattern, sentence, re.IGNORECASE)
                if match and match.group(2).lower() not in self.STOPWORDS:
                    return match.group(2).lower()
        
        elif category == MemoryCategory.PREFERENCES:
            for pattern in [
                r'(prefers?|always use|never use)\s+(?:to\s+)?(\w{3,})',
                r'(favorite|go-to|default)\s+(\w{3,})',
            ]:
                match = re.search(pattern, sentence, re.IGNORECASE)
                if match and match.group(2).lower() not in self.STOPWORDS:
                    return match.group(2).lower()
        
        elif category == MemoryCategory.ENTITIES:
            for pattern in [
                r'(Project|System|Framework|Platform)\s+([A-Z]\w+)',
                r'(?:client|customer|partner)\s+([A-Z]\w+)',
                r'\bAPI\b',
            ]:
                match = re.search(pattern, sentence)
                if match:
                    return (match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(0)).lower()
        
        elif category == MemoryCategory.CASES:
            for pattern in [
                r'(fixed|solved|resolved)\s+(?:the\s+)?(\w{3,})',
                r'(bug|issue|error)\s+(?:in|with)?\s*(\w{3,})',
                r'root cause\s+(?:was)?\s*(\w{3,})',
            ]:
                match = re.search(pattern, sentence, re.IGNORECASE)
                if match:
                    word = match.group(2) if match.lastindex >= 2 else match.group(1)
                    if word.lower() not in self.STOPWORDS:
                        return word.lower()
        
        elif category == MemoryCategory.PATTERNS:
            match = re.search(r'(workflow|process|approach|strategy)\s+(?:for|is)?\s*(\w{3,})', sentence, re.IGNORECASE)
            if match and match.group(2).lower() not in self.STOPWORDS:
                return match.group(2).lower()
        
        return None
    
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
    
    def _score_importance(self, sentence: str, category: MemoryCategory, 
                          confidence: MemoryConfidence) -> float:
        """Score memory importance 0.0-1.0 based on content signals.
        
        High importance: trade executions, rules/lessons, key decisions
        Medium importance: market analysis, observations
        Low importance: status updates, routine observations
        """
        score = 0.5  # baseline
        lower = sentence.lower()
        
        # Category bonus: some categories inherently matter more
        category_bonus = {
            MemoryCategory.CASES: 0.15,       # Lessons learned = high value
            MemoryCategory.PREFERENCES: 0.15, # Rules = high value
            MemoryCategory.EVENTS: 0.1,       # Actions taken = above average
            MemoryCategory.PATTERNS: 0.05,    # Analysis = moderate value
            MemoryCategory.ENTITIES: 0.0,     # Named things = baseline
        }
        score += category_bonus.get(category, 0)
        
        # Confidence bonus
        if confidence == MemoryConfidence.HIGH:
            score += 0.1
        elif confidence == MemoryConfidence.LOW:
            score -= 0.1
        
        # High-value signal words
        high_signals = [
            'learned', 'lesson', 'mistake', 'never again', 'always',
            'rule', 'critical', 'important', 'key insight', 'breakthrough',
            'fixed', 'solved', 'root cause', 'decision', 'committed',
            'emergency', 'danger', 'warning', 'risk',
        ]
        for signal in high_signals:
            if signal in lower:
                score += 0.05
        
        # Trade execution signals (concrete actions > observations)
        if re.search(r'\b(BUY|SELL|BOUGHT|SOLD|CLOSED|EXECUTED)\b', sentence):
            score += 0.1
        
        # Quantified statements are more valuable than vague ones
        if re.search(r'\d+%', sentence):  # Has percentages
            score += 0.05
        
        # Low-value signals
        low_signals = ['session summary', 'portfolio at close', 'cycle', 'checking']
        for signal in low_signals:
            if signal in lower:
                score -= 0.1
        
        # Clamp to valid range
        return max(0.1, min(1.0, round(score, 2)))
    
    def _generate_title(self, sentence: str, category: MemoryCategory) -> str:
        """Generate a meaningful title, not just truncation.
        
        Strategy: [CATEGORY] key subject — action/state
        """
        # Clean markdown artifacts
        clean = re.sub(r'[\*\#\`\|\-]{2,}', '', sentence).strip()
        clean = re.sub(r'^[\-\*\>\s]+', '', clean).strip()
        
        # Try to extract a structured title based on category
        if category == MemoryCategory.EVENTS:
            # Look for action + subject: "BUY 0.23 ETH" → "ETH: bought 0.23"
            trade = re.search(
                r'\b(BUY|SELL|BOUGHT|SOLD|CLOSED|OPENED)\s+([\d\.]+)?\s*(\w+)',
                clean, re.IGNORECASE
            )
            if trade:
                action = trade.group(1).lower()
                qty = trade.group(2) or ''
                asset = trade.group(3).upper()
                return f"{asset}: {action} {qty}".strip()
            
            # Look for decisions: "decided to X" → "Decision: X"
            decision = re.search(r'\b(?:decided|chose|went with)\s+(?:to\s+)?(.{10,40})', clean, re.IGNORECASE)
            if decision:
                return f"Decision: {decision.group(1).strip()}"
        
        elif category == MemoryCategory.PATTERNS:
            # Look for asset + pattern: "BTC rejected" → "BTC: rejection pattern"
            asset_pattern = re.search(
                r'\b(BTC|ETH|SOL|GLD|SPY|QQQ|USO|XLE)\b.*?\b(reject|support|resist|coil|compress|breakout|consolidat)',
                clean, re.IGNORECASE
            )
            if asset_pattern:
                return f"{asset_pattern.group(1).upper()}: {asset_pattern.group(2).lower()} pattern"
        
        elif category == MemoryCategory.PREFERENCES:
            # Look for rules: "Never X" / "Always X" → keep as-is if short
            rule = re.search(r'\b(never|always|must|avoid)\s+(.{5,40})', clean, re.IGNORECASE)
            if rule:
                return f"Rule: {rule.group(1).lower()} {rule.group(2).strip()}"
        
        elif category == MemoryCategory.CASES:
            # Look for fix: "Fixed X" → "Fix: X"
            fix = re.search(r'\b(?:fixed|solved|resolved)\s+(.{5,40})', clean, re.IGNORECASE)
            if fix:
                return f"Fix: {fix.group(1).strip()}"
            lesson = re.search(r'\b(?:learned|realized|discovered)\s+(?:that\s+)?(.{5,40})', clean, re.IGNORECASE)
            if lesson:
                return f"Lesson: {lesson.group(1).strip()}"
        
        # Fallback: smart truncation at word boundary
        if len(clean) <= 60:
            return clean
        # Cut at last word boundary before 60 chars
        truncated = clean[:60].rsplit(' ', 1)[0]
        return truncated + '...'
    
    def _generate_abstract(self, sentence: str) -> str:
        """Generate a condensed abstract from the full sentence."""
        # Clean markdown
        clean = re.sub(r'[\*\#\`]{2,}', '', sentence).strip()
        clean = re.sub(r'^[\-\*\>\s]+', '', clean).strip()
        
        # If already short, use as-is
        if len(clean) <= 150:
            return clean
        
        # Truncate at sentence boundary if possible
        first_period = clean.find('.', 50)
        if 50 < first_period < 150:
            return clean[:first_period + 1]
        
        # Word-boundary truncation
        return clean[:150].rsplit(' ', 1)[0] + '...'
