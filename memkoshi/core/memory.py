"""Memory data models."""

from typing import List, Dict, Optional, Any, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class MemoryCategory(str, Enum):
    """Memory categories for organizing different types of memories."""
    PREFERENCES = "preferences"
    ENTITIES = "entities"
    EVENTS = "events"
    CASES = "cases"
    PATTERNS = "patterns"


class MemoryConfidence(str, Enum):
    """Confidence levels for memory accuracy."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Memory(BaseModel):
    """Core memory data structure."""
    id: str = Field(..., pattern=r"mem_[a-f0-9]{8}")
    category: MemoryCategory
    topic: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=256)
    abstract: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1)
    
    # Source attribution
    confidence: MemoryConfidence
    source_sessions: List[str] = Field(default_factory=list)
    source_quotes: List[str] = Field(default_factory=list)
    
    # Metadata
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated: Optional[datetime] = None
    related_topics: List[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    
    # Security
    signature: Optional[str] = None  # HMAC-SHA256 signature
    trust_level: float = Field(default=1.0, ge=0.0, le=1.0)
    created_by: str = Field(default="system")
    
    # Storage
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    


class StagedMemory(Memory):
    """Memory pending review."""
    extraction_metadata: Dict[str, Any] = Field(default_factory=dict)
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    reviewer_notes: Optional[str] = None
    staged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))