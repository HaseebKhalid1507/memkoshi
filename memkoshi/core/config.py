"""Memkoshi configuration management."""

from dataclasses import dataclass, field
from pathlib import Path
import yaml
from typing import Optional


@dataclass
class MemkoshiConfig:
    """Configuration for Memkoshi system."""
    
    # Deduplication
    dedup_threshold: float = 0.8
    
    # Extraction
    min_content_length: int = 20
    max_memories_per_commit: int = 50
    
    # Search
    default_search_limit: int = 5
    recency_decay_factor: float = 0.1
    
    # Storage
    max_recent_sessions: int = 3
    
    # Paths
    storage_path: str = "~/.memkoshi"
    
    @classmethod
    def load(cls, path: Optional[str] = None) -> "MemkoshiConfig":
        """Load configuration from YAML file."""
        if path is None:
            path = Path.home() / ".memkoshi" / "config.yaml"
        else:
            path = Path(path)
        
        if path.exists():
            with open(path, 'r') as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        
        return cls()
    
    def save(self, path: Optional[str] = None) -> None:
        """Save configuration to YAML file."""
        if path is None:
            path = Path.home() / ".memkoshi" / "config.yaml"
        else:
            path = Path(path)
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            yaml.dump(self.__dict__, f, default_flow_style=False)
