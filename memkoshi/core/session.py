"""Session data models."""

from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict


class SessionSummary(BaseModel):
    """Session summary for memory extraction."""
    id: str = Field(..., pattern=r"S\d+")
    started_at: datetime
    ended_at: Optional[datetime] = None
    
    # Content
    conversation_summary: str
    key_decisions: List[str] = Field(default_factory=list)
    tools_used: List[str] = Field(default_factory=list)
    files_modified: List[str] = Field(default_factory=list)
    
    # Quality metrics
    productivity_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    insight_count: int = Field(default=0, ge=0)
    decision_count: int = Field(default=0, ge=0)
    
    # Metadata
    agent_version: str = Field(default="unknown")
    extraction_version: str = Field(default="1.0")
    
    


class Session(BaseModel):
    """Full session record."""
    summary: SessionSummary
    raw_messages: List[Dict[str, Any]] = Field(default_factory=list)
    compaction_data: Optional[Dict[str, Any]] = None
    extracted_memories: List[str] = Field(default_factory=list)  # Memory IDs
    
    