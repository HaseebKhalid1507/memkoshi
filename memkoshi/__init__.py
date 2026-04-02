"""Memkoshi - The only agent memory system that learns and improves over time."""

__version__ = "0.4.0"

from .api import Memkoshi
from .core.patterns import PatternDetector, Pattern
from .core.evolution import EvolutionEngine, EvolutionScore

# Keep Mikoshi as alias for backward compat
Mikoshi = Memkoshi

__all__ = ["Memkoshi", "Mikoshi", "PatternDetector", "Pattern", "EvolutionEngine", "EvolutionScore"]
