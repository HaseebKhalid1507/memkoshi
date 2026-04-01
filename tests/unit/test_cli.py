"""Tests for CLI interface."""

import pytest
import tempfile
import os
import json
import sys
from click.testing import CliRunner
from pathlib import Path
from memkoshi.cli.main import cli
from memkoshi.storage.sqlite import SQLiteBackend
from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence
from memkoshi.core.context import BootContext


def test_cli_boot_command_fresh_start():
    """CLI boot command shows fresh start when no context exists."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Run boot
        result = runner.invoke(cli, ['--storage', temp_dir, 'boot'])
        assert result.exit_code == 0
        assert "Fresh start" in result.output


def test_cli_boot_command_with_context():
    """CLI boot command shows handoff when context exists."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Store context
        context = BootContext(
            handoff="Previous work on project X",
            session_brief="Last session focused on memory extraction",
            recent_sessions=["S001", "S002"],
            active_projects=["memkoshi", "velocirag"],
            staged_memories_count=3
        )
        storage.store_context(context)
        
        # Stage a memory
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="testing",
            title="Test memory",
            abstract="This is a staged test memory",
            content="This is a staged test memory for boot testing",
            confidence=MemoryConfidence.HIGH
        )
        storage.stage_memory(memory)
        
        # Run boot
        result = runner.invoke(cli, ['--storage', temp_dir, 'boot'])
        assert result.exit_code == 0
        assert "Previous work on project X" in result.output
        assert "Staged memories: 1" in result.output


def test_cli_boot_command_json_output():
    """CLI boot command can output JSON format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Run boot with --json flag
        result = runner.invoke(cli, ['--storage', temp_dir, 'boot', '--json'])
        assert result.exit_code == 0
        
        # Parse JSON output
        data = json.loads(result.output)
        assert 'handoff' in data
        assert 'session_count' in data
        assert 'memory_count' in data


def test_cli_commit_command():
    """CLI commit processes text from stdin."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Ingest text
        text = "I decided to use Python for all backend development. I prefer TypeScript for frontend work."
        result = runner.invoke(cli, ['--storage', temp_dir, 'commit'], input=text)
        
        assert result.exit_code == 0
        assert "extracted" in result.output
        assert "staged" in result.output


def test_cli_review_command_empty():
    """CLI review shows message when no memories pending."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Review with no staged memories
        result = runner.invoke(cli, ['--storage', temp_dir, 'review'])
        
        assert result.exit_code == 0
        assert "No staged memories to review" in result.output


def test_cli_review_command_interactive():
    """CLI review allows interactive approval/rejection."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.PREFERENCES,
            topic="testing",
            title="Test preference",
            abstract="I prefer pytest for testing",
            content="I prefer pytest for testing Python code",
            confidence=MemoryConfidence.HIGH
        )
        storage.stage_memory(memory)
        
        # Review with approval
        result = runner.invoke(cli, ['--storage', temp_dir, 'review'], input='a\nq\n')
        
        assert result.exit_code == 0
        assert "Test preference" in result.output
        assert "Approved" in result.output
        assert "Reviewed 1 memories" in result.output


def test_cli_review_command_reject_with_reason():
    """CLI review allows rejection with reason."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        memory = Memory(
            id="mem_87654321",
            category=MemoryCategory.EVENTS,
            topic="testing",
            title="Bad memory",
            abstract="This memory is not useful",
            content="This memory contains no valuable information",
            confidence=MemoryConfidence.LOW
        )
        storage.stage_memory(memory)
        
        # Review with rejection
        result = runner.invoke(cli, ['--storage', temp_dir, 'review'], input='r\nNot relevant\nq\n')
        
        assert result.exit_code == 0
        assert "Rejected" in result.output
        assert "Reviewed 1 memories" in result.output


def test_cli_recall_command_basic_search():
    """CLI recall searches memories."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage and add memories
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Add test memories
        memory1 = Memory(
            id="mem_aaaaaaaa",
            category=MemoryCategory.PATTERNS,
            topic="python",
            title="Python async patterns",
            abstract="Guide to async programming",
            content="Understanding async/await in Python",
            confidence=MemoryConfidence.HIGH,
            tags=["python", "async"]
        )
        memory2 = Memory(
            id="mem_bbbbbbbb",
            category=MemoryCategory.CASES,
            topic="security",
            title="JWT authentication",
            abstract="JWT auth implementation",
            content="Building secure auth with tokens",
            confidence=MemoryConfidence.HIGH,
            tags=["security", "auth"]
        )
        
        storage.store_memory(memory1)
        storage.store_memory(memory2)
        
        # Search
        result = runner.invoke(cli, ['--storage', temp_dir, 'recall', 'auth'])
        
        assert result.exit_code == 0
        assert "JWT authentication" in result.output


def test_cli_recall_command_with_filters():
    """CLI recall respects category filter."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage and add memories
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Add memories in different categories
        memory1 = Memory(
            id="mem_cccccccc",
            category=MemoryCategory.PATTERNS,
            topic="testing",
            title="Testing patterns",
            abstract="Best practices for testing",
            content="Unit testing patterns and practices",
            confidence=MemoryConfidence.HIGH,
            tags=["testing", "patterns"]
        )
        memory2 = Memory(
            id="mem_dddddddd",
            category=MemoryCategory.EVENTS,
            topic="conference",
            title="Testing conference",
            abstract="Annual testing conf",
            content="Conference about testing tools",
            confidence=MemoryConfidence.HIGH,
            tags=["conference", "testing"]
        )
        
        storage.store_memory(memory1)
        storage.store_memory(memory2)
        
        # Search with category filter
        result = runner.invoke(cli, ['--storage', temp_dir, 'recall', 'testing', '--category', 'patterns'])
        
        assert result.exit_code == 0
        assert "Testing patterns" in result.output
        assert "Testing conference" not in result.output


def test_cli_recall_command_json_output():
    """CLI recall can output JSON format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage and add a memory
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        memory = Memory(
            id="mem_eeeeeeee",
            category=MemoryCategory.PREFERENCES,
            topic="tooling",
            title="Code formatter preference",
            abstract="I prefer black for Python",
            content="Black formatter with default settings",
            confidence=MemoryConfidence.HIGH,
            tags=["python", "tooling"]
        )
        storage.store_memory(memory)
        
        # Search with JSON output
        result = runner.invoke(cli, ['--storage', temp_dir, 'recall', 'black', '--json'])
        
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]['title'] == "Code formatter preference"


def test_cli_stats_command():
    """CLI stats shows storage statistics."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage and add data
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Add memories
        for i in range(3):
            memory = Memory(
                id=f"mem_{i:08x}",
                category=MemoryCategory.PATTERNS,
                topic="test",
                title=f"Memory {i}",
                abstract=f"Abstract {i}",
                content=f"Content {i}",
                confidence=MemoryConfidence.HIGH,
                tags=["test"]
            )
            if i < 2:
                storage.store_memory(memory)
            else:
                storage.stage_memory(memory)
        
        # Run stats
        result = runner.invoke(cli, ['--storage', temp_dir, 'stats'])
        
        assert result.exit_code == 0
        assert "Total memories: 2" in result.output
        assert "Staged memories: 1" in result.output


def test_cli_recall_with_search():
    """CLI recall uses search engine when available."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage and add some memories
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Create and store test memories
        memory1 = Memory(
            id="mem_12345678",
            category=MemoryCategory.PATTERNS,
            topic="python",
            title="Python async patterns",
            abstract="Guide to async programming",
            content="Understanding async/await in Python",
            confidence=MemoryConfidence.HIGH,
            tags=["python", "async"]
        )
        memory2 = Memory(
            id="mem_87654321", 
            category=MemoryCategory.CASES,
            topic="security",
            title="JWT authentication",
            abstract="JWT auth implementation",
            content="Building secure auth with tokens",
            confidence=MemoryConfidence.HIGH,
            tags=["security", "auth", "jwt"]
        )
        
        storage.store_memory(memory1)
        storage.store_memory(memory2)
        
        # Run recall with verbose to see which engine is used
        result = runner.invoke(cli, ['--storage', temp_dir, '--verbose', 'recall', 'auth'])
        
        assert result.exit_code == 0
        assert "JWT authentication" in result.output
        # Should indicate search mode in verbose
        assert "semantic search" in result.output or "SQL fallback" in result.output


def test_cli_reindex_command():
    """CLI reindex command rebuilds search index."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage and add memories
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Add test memories
        for i in range(3):
            memory = Memory(
                id=f"mem_{i:08x}",
                category=MemoryCategory.PATTERNS,
                topic="test",
                title=f"Test memory {i}",
                abstract=f"Abstract {i}",
                content=f"Content {i}",
                confidence=MemoryConfidence.HIGH,
                tags=["test"]
            )
            storage.store_memory(memory)
        
        # Run reindex
        result = runner.invoke(cli, ['--storage', temp_dir, 'reindex'])
        
        assert result.exit_code == 0
        assert "Rebuilding search index" in result.output
        assert "Indexed 3 memories" in result.output


def test_cli_boot_warns_about_missing_index():
    """CLI boot command warns when search index is missing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Run boot - should warn about missing index
        result = runner.invoke(cli, ['--storage', temp_dir, 'boot'])
        
        assert result.exit_code == 0
        assert "Search index not found" in result.output
        assert "memkoshi reindex" in result.output


def test_cli_review_indexes_approved_memories():
    """CLI review command indexes memories when approved."""
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = CliRunner()
        
        # Initialize storage
        storage = SQLiteBackend(temp_dir)
        storage.initialize()
        
        # Stage a memory
        memory = Memory(
            id="mem_abcdef12",
            category=MemoryCategory.PATTERNS,
            topic="test",
            title="Test staged memory",
            abstract="Test abstract",
            content="Test content for approval",
            confidence=MemoryConfidence.HIGH,
            tags=["test", "staged"]
        )
        storage.stage_memory(memory)
        
        # Run review and approve
        result = runner.invoke(cli, ['--storage', temp_dir, 'review'], input='a\nq\n')
        
        assert result.exit_code == 0
        assert "Approved" in result.output
        assert "Reviewed 1 memories" in result.output
        
        # Verify memory was approved
        approved = storage.get_memory("mem_abcdef12")
        assert approved is not None
