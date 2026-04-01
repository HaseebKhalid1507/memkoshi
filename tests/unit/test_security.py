"""Tests for security module."""

import os
import tempfile
import pytest
from pathlib import Path
from memkoshi.core.security import MemorySigner
from memkoshi.core.memory import Memory, MemoryCategory, MemoryConfidence


def test_memory_signer_init_generates_key():
    """MemorySigner generates a key if not provided."""
    signer = MemorySigner()
    assert signer.signing_key is not None
    assert len(signer.signing_key) == 32  # 256 bits


def test_memory_signer_init_with_key():
    """MemorySigner can be initialized with a specific key."""
    key = b"test_key_32_bytes_long_exactly!!"
    signer = MemorySigner(signing_key=key)
    assert signer.signing_key == key


def test_memory_signer_sign():
    """MemorySigner can sign a memory."""
    signer = MemorySigner()
    memory = Memory(
        id="mem_12345678",  # Correct format
        category=MemoryCategory.EVENTS,
        topic="testing",
        title="Test memory",
        abstract="This is a test memory",
        content="Full content of the test memory",
        confidence=MemoryConfidence.HIGH,
        created="2024-01-01T00:00:00"
    )
    
    signature = signer.sign(memory)
    assert signature is not None
    assert isinstance(signature, str)
    assert len(signature) == 64  # SHA256 produces 32 bytes = 64 hex chars


def test_memory_signer_verify_valid():
    """MemorySigner verifies valid signatures correctly."""
    signer = MemorySigner()
    memory = Memory(
        id="mem_12345678",
        category=MemoryCategory.EVENTS,
        topic="testing",
        title="Test memory",
        abstract="This is a test memory",
        content="Full content of the test memory",
        confidence=MemoryConfidence.HIGH,
        created="2024-01-01T00:00:00"
    )
    
    # Sign and store signature
    signature = signer.sign(memory)
    memory.signature = signature
    
    # Verify should return True
    assert signer.verify(memory) is True


def test_memory_signer_verify_tampered():
    """MemorySigner detects tampered memories."""
    signer = MemorySigner()
    memory = Memory(
        id="mem_12345678",
        category=MemoryCategory.EVENTS,
        topic="testing",
        title="Test memory",
        abstract="This is a test memory",
        content="Full content of the test memory",
        confidence=MemoryConfidence.HIGH,
        created="2024-01-01T00:00:00"
    )
    
    # Sign the memory
    signature = signer.sign(memory)
    memory.signature = signature
    
    # Tamper with the memory
    memory.content = "Tampered content"
    
    # Verify should return False
    assert signer.verify(memory) is False


def test_memory_signer_verify_no_signature():
    """MemorySigner returns False for memories without signatures."""
    signer = MemorySigner()
    memory = Memory(
        id="mem_12345678",
        category=MemoryCategory.EVENTS,
        topic="testing",
        title="Test memory",
        abstract="This is a test memory",
        content="Full content of the test memory",
        confidence=MemoryConfidence.HIGH,
        created="2024-01-01T00:00:00"
    )
    
    # No signature set
    assert signer.verify(memory) is False


def test_memory_signer_deterministic():
    """MemorySigner produces same signature for same memory with same key."""
    key = b"test_key_32_bytes_long_exactly!!"
    signer1 = MemorySigner(signing_key=key)
    signer2 = MemorySigner(signing_key=key)
    
    memory = Memory(
        id="mem_12345678",
        category=MemoryCategory.EVENTS,
        topic="testing",
        title="Test memory",
        abstract="This is a test memory",
        content="Full content of the test memory",
        confidence=MemoryConfidence.HIGH,
        created="2024-01-01T00:00:00"
    )
    
    sig1 = signer1.sign(memory)
    sig2 = signer2.sign(memory)
    
    assert sig1 == sig2


def test_memory_signer_different_keys_different_signatures():
    """Different keys produce different signatures."""
    signer1 = MemorySigner()  # Auto-generated key
    signer2 = MemorySigner()  # Different auto-generated key
    
    memory = Memory(
        id="mem_12345678",
        category=MemoryCategory.EVENTS,
        topic="testing",
        title="Test memory",
        abstract="This is a test memory",
        content="Full content of the test memory",
        confidence=MemoryConfidence.HIGH,
        created="2024-01-01T00:00:00"
    )
    
    sig1 = signer1.sign(memory)
    sig2 = signer2.sign(memory)
    
    # Should be different (extremely high probability)
    assert sig1 != sig2


def test_memory_signer_key_persistence():
    """MemorySigner persists and loads keys correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir)
        
        # Create signer with storage path
        signer1 = MemorySigner(storage_path=storage_path)
        key1 = signer1.signing_key
        
        # Create memory and sign it
        memory = Memory(
            id="mem_12345678",
            category=MemoryCategory.EVENTS,
            topic="testing",
            title="Test memory",
            abstract="This is a test memory",
            content="Full content of the test memory",
            confidence=MemoryConfidence.HIGH,
            created="2024-01-01T00:00:00"
        )
        sig1 = signer1.sign(memory)
        
        # Create new signer with same storage path
        signer2 = MemorySigner(storage_path=storage_path)
        key2 = signer2.signing_key
        
        # Should load the same key
        assert key1 == key2
        
        # Should produce same signature
        sig2 = signer2.sign(memory)
        assert sig1 == sig2
        
        # Check key file permissions (Unix only)
        if os.name == 'posix':
            key_file = storage_path / ".memkoshi_key"
            assert key_file.exists()
            stat = key_file.stat()
            assert oct(stat.st_mode)[-3:] == '600'


def test_memory_signer_canonicalize_order():
    """Canonicalization is consistent regardless of field order."""
    signer = MemorySigner()
    
    # Create two memories with same content but potentially different field order
    memory1 = Memory(
        id="mem_12345678",
        category=MemoryCategory.EVENTS,
        topic="testing",
        title="Test memory",
        abstract="This is a test memory",
        content="Full content of the test memory",
        confidence=MemoryConfidence.HIGH,
        created="2024-01-01T00:00:00"
    )
    
    memory2 = Memory(
        created="2024-01-01T00:00:00",
        confidence=MemoryConfidence.HIGH,
        content="Full content of the test memory",
        abstract="This is a test memory",
        title="Test memory",
        topic="testing",
        category=MemoryCategory.EVENTS,
        id="mem_12345678"
    )
    
    # Should produce same canonical form
    canon1 = signer._canonicalize(memory1)
    canon2 = signer._canonicalize(memory2)
    assert canon1 == canon2
