"""Session data models and context management."""

import uuid
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
    

class SessionContext:
    """Context manager for tracking agent sessions."""
    
    def __init__(self, memkoshi_instance, description='', auto_extract=True):
        self.mk = memkoshi_instance
        self.description = description
        self.auto_extract = auto_extract
        self.messages = []
        self.tool_calls = []
        self.started_at = datetime.now(timezone.utc)
        self.session_id = f"session_{uuid.uuid4().hex[:8]}"
    
    def __enter__(self):
        self.mk._trigger_event('session_start', self._get_data())
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.ended_at = datetime.now(timezone.utc)
        data = self._get_data()
        
        # Auto-extract memories from session
        if self.auto_extract and len(self.messages) >= 2:
            summary = self._build_summary()
            try:
                self.mk.commit(summary)
            except Exception:
                pass  # Don't fail session exit on extraction error
        
        # Track session in context
        if hasattr(self.mk, 'context') and self.mk.context:
            summary = self._build_summary()
            self.mk.context.add_session(summary)
        
        self.mk._trigger_event('session_end', data)
        self.mk._active_session = None
        return False  # Don't suppress exceptions
    
    def add_message(self, role, content):
        self.messages.append({
            'role': role, 
            'content': content, 
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    def add_tool_call(self, tool_name, args=None, result=None):
        self.tool_calls.append({
            'tool': tool_name, 
            'args': args, 
            'result': result, 
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    def _build_summary(self):
        parts = [f"Session: {self.description}"] if self.description else []
        for msg in self.messages:
            parts.append(f"[{msg['role']}]: {msg['content']}")
        if self.tool_calls:
            tools = ', '.join(set(tc['tool'] for tc in self.tool_calls))
            parts.append(f"Tools used: {tools}")
        return '\n'.join(parts)
    
    def _get_data(self):
        data = {
            'session_id': self.session_id,
            'description': self.description,
            'messages': self.messages,
            'tool_calls': self.tool_calls,
            'started_at': self.started_at.isoformat(),
            'message_count': len(self.messages),
            'user_message_count': sum(1 for m in self.messages if m['role'] == 'user'),
        }
        
        if hasattr(self, 'ended_at'):
            data['ended_at'] = self.ended_at.isoformat()
        
        return data
    
    