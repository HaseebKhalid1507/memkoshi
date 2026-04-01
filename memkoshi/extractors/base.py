"""Abstract memory extraction interface."""

from abc import ABC, abstractmethod
from typing import List
from ..core.memory import Memory


class MemoryExtractor(ABC):
    """Abstract memory extraction interface."""
    
    @abstractmethod
    def initialize(self) -> None:
        """Initialize extractor (load models, etc.)."""
        pass
    
    @abstractmethod
    def extract_memories(self, text: str) -> List[Memory]:
        """Extract structured memories from text."""
        pass
