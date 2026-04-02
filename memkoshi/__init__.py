"""Memkoshi - The only agent memory system that learns and improves over time."""

__version__ = "0.3.0"

from .api import Memkoshi

# Keep Mikoshi as alias for backward compat
Mikoshi = Memkoshi

__all__ = ["Memkoshi", "Mikoshi"]
