"""Memory extraction and staging pipeline."""

import time
import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from ..storage.base import StorageBackend
from ..extractors.base import MemoryExtractor
from ..core.memory import Memory
from ..core.security import MemorySigner


class MemoryPipeline:
    """Memory extraction and staging pipeline."""
    
    def __init__(self, storage: StorageBackend, extractor: MemoryExtractor):
        self.storage = storage
        self.extractor = extractor
        # Initialize signer with storage path if available
        storage_path = None
        if hasattr(storage, 'path') and storage.path and isinstance(storage.path, (str, Path)):
            try:
                storage_path = Path(storage.path).parent
            except (TypeError, ValueError):
                storage_path = None
        self.signer = MemorySigner(storage_path=storage_path)
    
    def process(self, text: str) -> Dict[str, Any]:
        """
        Process text through the full memory pipeline.
        
        Flow:
        1. Extract memories using extractor
        2. Validate each memory
        3. Deduplicate against each other and existing memories
        4. Sign each memory for integrity
        5. Stage all survivors
        6. Return statistics
        """
        start_time = time.time()
        
        result = {
            "extracted_count": 0,
            "staged_count": 0,
            "validation_errors": [],
            "pipeline_time": 0.0
        }
        
        # Step 1: Extract memories
        memories = self.extractor.extract_memories(text)
        result["extracted_count"] = len(memories)
        
        if not memories:
            result["pipeline_time"] = time.time() - start_time
            return result
        
        # Step 2: Validate memories
        validated_memories = []
        for memory in memories:
            errors = self._validate_memory(memory)
            if errors:
                result["validation_errors"].extend(errors)
            else:
                validated_memories.append(memory)
        
        # Step 3: Deduplicate
        unique_memories = self._deduplicate_memories(validated_memories)
        
        # Step 4: Sign memories for integrity
        for memory in unique_memories:
            memory.signature = self.signer.sign(memory)
        
        # Step 5: Stage survivors
        for memory in unique_memories:
            self.storage.stage_memory(memory)
        
        result["staged_count"] = len(unique_memories)
        result["pipeline_time"] = time.time() - start_time
        
        return result
    
    def _validate_memory(self, memory: Memory) -> List[str]:
        """
        Validate a memory for:
        - Minimum content length (20 chars)
        - Injection patterns
        """
        errors = []
        
        # Check minimum content length
        if len(memory.content.strip()) < 20:
            errors.append(f"Memory {memory.id}: content length ({len(memory.content.strip())}) below minimum (20)")
        
        # Check for injection patterns
        injection_patterns = [
            "remember that you must always",
            "for all future queries",
            "system instruction:",
            "override settings"
        ]
        
        content_lower = memory.content.lower()
        for pattern in injection_patterns:
            if pattern in content_lower:
                errors.append(f"Memory {memory.id}: injection pattern detected: '{pattern}'")
        
        return errors
    
    def _deduplicate_memories(self, memories: List[Memory]) -> List[Memory]:
        """
        Deduplicate memories using Jaccard similarity.
        Check against:
        1. Each other in the current batch
        2. Existing memories in storage
        """
        if not memories:
            return []
        
        # Get existing memories for deduplication
        existing_memories = self.storage.list_memories(limit=1000)
        
        unique_memories = []
        
        for memory in memories:
            is_duplicate = False
            
            # Check against existing memories
            for existing in existing_memories:
                similarity = self._jaccard_similarity(memory.content, existing.content)
                if similarity > 0.8:  # Threshold
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                # Check against already processed unique memories
                for unique in unique_memories:
                    similarity = self._jaccard_similarity(memory.content, unique.content)
                    if similarity > 0.8:
                        is_duplicate = True
                        break
            
            if not is_duplicate:
                unique_memories.append(memory)
        
        return unique_memories
    
    def _jaccard_similarity(self, text1: str, text2: str) -> float:
        """Calculate Jaccard similarity between two texts."""
        # Convert to lowercase and split into words
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        # Handle empty sets
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0
        
        # Calculate Jaccard similarity
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union)
