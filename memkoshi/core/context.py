"""Context data models."""

from typing import List, Dict, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict


class ContextTier(BaseModel):
    """Configuration for memory tier."""
    name: str
    size_limit: Optional[str] = None  # "1KB", "10MB", None for unlimited
    rotation_policy: Optional[str] = None  # "sessions:3", "days:7"
    auto_archive: bool = True
    
    


class BootContext(BaseModel):
    """Context loaded at agent boot."""
    # Identity & State
    handoff: Optional[str] = None           # In-flight work state
    session_brief: Optional[str] = None     # Current session summary
    checkpoint: Optional[str] = None        # Mid-session state
    
    # Recent History  
    recent_sessions: List[str] = Field(default_factory=list)  # Last 3 sessions
    active_projects: List[str] = Field(default_factory=list)  # Active project summaries
    current_tasks: List[str] = Field(default_factory=list)    # Pending tasks
    
    # Evolution Hints
    behavioral_hints: List[str] = Field(default_factory=list)
    improvement_areas: List[str] = Field(default_factory=list)
    
    # System State
    staged_memories_count: int = 0
    last_evolution_run: Optional[datetime] = None
    
    # Metadata
    loaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_size_bytes: int = 0
    tier_breakdown: Dict[str, int] = Field(default_factory=dict)
    
    