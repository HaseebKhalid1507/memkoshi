"""Comparison utility for memory extractors."""

from typing import List, Dict, Any, Union
from .base import MemoryExtractor
from .hybrid import HybridExtractor
from .api import APIExtractor
from ..core.memory import Memory


def compare_extractors(text: str, extractors: List[MemoryExtractor]) -> Dict[str, Any]:
    """
    Run multiple extractors on the same text and compare results.
    
    Args:
        text: Text to extract memories from
        extractors: List of initialized extractor instances
        
    Returns:
        Dictionary with comparison results for each extractor
    """
    results = {}
    
    for extractor in extractors:
        try:
            # Extract memories
            memories = extractor.extract_memories(text)
            
            # Collect statistics
            categories = {}
            for mem in memories:
                cat = mem.category.value
                categories[cat] = categories.get(cat, 0) + 1
            
            # Store results
            extractor_name = extractor.__class__.__name__
            results[extractor_name] = {
                "count": len(memories),
                "categories": [m.category.value for m in memories],
                "category_counts": categories,
                "memories": memories,
                "topics": [m.topic for m in memories],
                "titles": [m.title for m in memories],
                "confidence_levels": {
                    "high": sum(1 for m in memories if m.confidence.value == "high"),
                    "medium": sum(1 for m in memories if m.confidence.value == "medium"),
                    "low": sum(1 for m in memories if m.confidence.value == "low")
                }
            }
        except Exception as e:
            extractor_name = extractor.__class__.__name__
            results[extractor_name] = {
                "error": str(e),
                "count": 0,
                "categories": [],
                "memories": []
            }
    
    return results


def format_comparison(comparison_results: Dict[str, Any], verbose: bool = False) -> str:
    """
    Format comparison results for display.
    
    Args:
        comparison_results: Results from compare_extractors
        verbose: Whether to show detailed memory content
        
    Returns:
        Formatted string for display
    """
    lines = []
    lines.append("Memory Extraction Comparison")
    lines.append("=" * 60)
    lines.append("")
    
    # Summary table
    extractors = list(comparison_results.keys())
    if extractors:
        # Header
        lines.append(f"{'Extractor':<20} {'Total':<10} {'Categories':<30}")
        lines.append("-" * 60)
        
        # Data rows
        for extractor, data in comparison_results.items():
            if "error" in data:
                lines.append(f"{extractor:<20} {'ERROR':<10} {data['error'][:28]}")
            else:
                categories = ', '.join(f"{cat}:{count}" 
                                     for cat, count in data['category_counts'].items())
                lines.append(f"{extractor:<20} {data['count']:<10} {categories:<30}")
        
        lines.append("")
        
        # Confidence distribution
        lines.append("Confidence Levels:")
        lines.append(f"{'Extractor':<20} {'High':<10} {'Medium':<10} {'Low':<10}")
        lines.append("-" * 50)
        
        for extractor, data in comparison_results.items():
            if "error" not in data:
                conf = data['confidence_levels']
                lines.append(f"{extractor:<20} {conf['high']:<10} {conf['medium']:<10} {conf['low']:<10}")
        
        lines.append("")
        
        if verbose:
            # Detailed memory comparison
            lines.append("Detailed Memories:")
            lines.append("-" * 60)
            
            for extractor, data in comparison_results.items():
                if "error" not in data and data['memories']:
                    lines.append(f"\n{extractor}:")
                    for i, memory in enumerate(data['memories'], 1):
                        lines.append(f"  {i}. [{memory.category.value}] {memory.title}")
                        lines.append(f"     Topic: {memory.topic} | Confidence: {memory.confidence.value}")
                        if hasattr(memory, 'abstract'):
                            lines.append(f"     {memory.abstract}")
                        lines.append("")
    
    return "\n".join(lines)


def compare_default_extractors(text: str, api_key: str = None) -> Dict[str, Any]:
    """
    Convenience function to compare hybrid vs API extractors.
    
    Args:
        text: Text to extract from
        api_key: Optional API key for API extractor
        
    Returns:
        Comparison results
    """
    extractors = []
    
    # Always include hybrid
    hybrid = HybridExtractor()
    hybrid.initialize()
    extractors.append(hybrid)
    
    # Include API if key is available
    if api_key:
        api = APIExtractor(api_key=api_key)
        try:
            api.initialize()
            extractors.append(api)
        except ValueError:
            # No API key available
            pass
    
    return compare_extractors(text, extractors)
