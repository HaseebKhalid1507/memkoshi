"""Security module for memory signing and verification."""

import hmac
import hashlib
import os
from pathlib import Path
from typing import Optional
from .memory import Memory


class MemorySigner:
    """HMAC-based memory signer for integrity verification."""
    
    def __init__(self, signing_key: Optional[bytes] = None, storage_path: Optional[Path] = None):
        """Initialize the signer with a key.
        
        Args:
            signing_key: 32-byte signing key. If None, generates or loads one.
            storage_path: Path to storage directory for key persistence.
        """
        self.storage_path = storage_path
        
        if signing_key:
            self.signing_key = signing_key
        else:
            # Try to load existing key or generate new one
            self.signing_key = self._load_or_generate_key()
    
    def _load_or_generate_key(self) -> bytes:
        """Load existing key from storage or generate a new one."""
        if self.storage_path:
            key_file = self.storage_path / ".memkoshi_key"
            
            if key_file.exists():
                # Load existing key
                with open(key_file, 'rb') as f:
                    return f.read()
            else:
                # Generate new key and save it
                key = os.urandom(32)  # 256 bits
                
                # Create directory if needed
                key_file.parent.mkdir(parents=True, exist_ok=True)
                
                # Write key with restricted permissions
                with open(key_file, 'wb') as f:
                    f.write(key)
                
                # Set permissions to 600 (owner read/write only)
                if os.name == 'posix':
                    os.chmod(key_file, 0o600)
                
                return key
        else:
            # No storage path, just generate a key
            return os.urandom(32)
    
    def sign(self, memory: Memory) -> str:
        """Sign a memory and return the signature.
        
        Args:
            memory: The memory to sign.
            
        Returns:
            Hex-encoded HMAC-SHA256 signature.
        """
        canonical = self._canonicalize(memory)
        signature = hmac.new(self.signing_key, canonical.encode('utf-8'), hashlib.sha256)
        return signature.hexdigest()
    
    def verify(self, memory: Memory) -> bool:
        """Verify a memory's signature.
        
        Args:
            memory: The memory to verify. Must have a 'signature' attribute.
            
        Returns:
            True if signature is valid, False otherwise.
        """
        if not hasattr(memory, 'signature') or not memory.signature:
            return False
        
        expected_signature = self.sign(memory)
        return hmac.compare_digest(memory.signature, expected_signature)
    
    def _canonicalize(self, memory: Memory) -> str:
        """Create a canonical string representation of a memory for signing.
        
        Args:
            memory: The memory to canonicalize.
            
        Returns:
            Deterministic string representation.
        """
        # Use specific fields in a fixed order
        fields = [
            memory.id,
            memory.category.value,  # Use the enum value
            memory.topic,
            memory.title,
            memory.content,
            memory.created if isinstance(memory.created, str) else memory.created.isoformat()
        ]
        
        # Join with a delimiter that won't appear in the content
        return '\x00'.join(fields)
