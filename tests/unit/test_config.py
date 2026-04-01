"""Tests for configuration management."""

import pytest
import tempfile
from pathlib import Path
import yaml

from memkoshi.core.config import MemkoshiConfig


def test_config_defaults():
    """Config has sensible defaults."""
    config = MemkoshiConfig()
    
    assert config.dedup_threshold == 0.8
    assert config.min_content_length == 20
    assert config.max_memories_per_commit == 50
    assert config.default_search_limit == 5
    assert config.recency_decay_factor == 0.1
    assert config.max_recent_sessions == 3
    assert config.storage_path == "~/.memkoshi"


def test_config_load_from_file():
    """Config can be loaded from YAML file."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        
        # Write custom config
        custom_config = {
            'dedup_threshold': 0.9,
            'min_content_length': 10,
            'default_search_limit': 10
        }
        
        with open(config_path, 'w') as f:
            yaml.dump(custom_config, f)
        
        # Load config
        config = MemkoshiConfig.load(str(config_path))
        
        assert config.dedup_threshold == 0.9
        assert config.min_content_length == 10
        assert config.default_search_limit == 10
        # Other values should have defaults
        assert config.max_memories_per_commit == 50


def test_config_save():
    """Config can be saved to YAML file."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        
        config = MemkoshiConfig(dedup_threshold=0.75, default_search_limit=20)
        config.save(str(config_path))
        
        # Read back
        with open(config_path, 'r') as f:
            saved_data = yaml.safe_load(f)
        
        assert saved_data['dedup_threshold'] == 0.75
        assert saved_data['default_search_limit'] == 20
