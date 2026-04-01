"""Abstract storage interface."""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from datetime import datetime

from ..core.memory import Memory, MemoryCategory
from ..core.session import Session
from ..core.context import BootContext


class StorageBackend(ABC):
    """Abstract storage interface - sync-first design."""
    
    @abstractmethod
    def initialize(self) -> None:
        """Initialize storage backend."""
        pass
    
    # Memory CRUD
    @abstractmethod 
    def store_memory(self, memory: Memory) -> str:
        """Store memory, return ID."""
        pass
    
    @abstractmethod
    def get_memory(self, memory_id: str) -> Optional[Memory]:
        """Retrieve memory by ID."""
        pass
    
    @abstractmethod
    def update_memory(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        """Update memory fields."""
        pass
    
    @abstractmethod
    def delete_memory(self, memory_id: str) -> bool:
        """Delete memory."""
        pass
    
    @abstractmethod
    def list_memories(
        self, 
        category: Optional[MemoryCategory] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Memory]:
        """List memories with filtering."""
        pass
    
    # Session CRUD
    @abstractmethod
    def store_session(self, session: Session) -> str:
        """Store session."""
        pass
    
    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session."""
        pass
    
    @abstractmethod
    def list_sessions(
        self,
        limit: int = 10,
        offset: int = 0,
        since: Optional[datetime] = None
    ) -> List[Session]:
        """List sessions chronologically."""
        pass
    
    # Context Management
    @abstractmethod
    def store_context(self, context: BootContext) -> None:
        """Store boot context."""
        pass
    
    @abstractmethod
    def get_context(self) -> Optional[BootContext]:
        """Load boot context."""
        pass
    
    # Staging Operations
    @abstractmethod
    def stage_memory(self, memory: Memory) -> str:
        """Add memory to staging area."""
        pass
    
    @abstractmethod
    def list_staged(self) -> List[Memory]:
        """List memories in staging."""
        pass
    
    @abstractmethod
    def approve_memory(self, memory_id: str, reviewer: str) -> bool:
        """Move memory from staging to permanent."""
        pass
    
    @abstractmethod
    def reject_memory(self, memory_id: str, reason: str) -> bool:
        """Reject staged memory."""
        pass
    
    # Utility
    @abstractmethod
    def backup(self, path: str) -> bool:
        """Create backup."""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        pass
    
    @abstractmethod
    def search_memories(self, query: str, limit: int = 100) -> List[Memory]:
        """Search memories with keyword matching."""
        pass