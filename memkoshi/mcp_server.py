"""MCP server for Memkoshi memory system."""

import os
from pathlib import Path
from typing import Optional

# Try to import fastmcp
try:
    from fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    FastMCP = None

from .api import Memkoshi

# Global instance
_memkoshi_instance = None


def get_memkoshi() -> Memkoshi:
    """Get or create the global Memkoshi instance."""
    global _memkoshi_instance
    
    if _memkoshi_instance is None:
        # Use environment variable or default path
        storage_path = os.environ.get('MEMKOSHI_STORAGE', str(Path.home() / '.memkoshi'))
        _memkoshi_instance = Memkoshi(storage_path)
        _memkoshi_instance.init()
    
    return _memkoshi_instance


def memory_boot() -> str:
    """Get boot context with current memory state.
    
    Returns:
        Formatted boot context as text.
    """
    m = get_memkoshi()
    ctx = m.boot()
    
    lines = [
        "=== Memkoshi Boot Context ===",
        f"Session count: {ctx['session_count']}",
        f"Total memories: {ctx['memory_count']}",
        f"Staged memories: {ctx['staged_count']}",
        ""
    ]
    
    if ctx['handoff_text']:
        lines.extend([
            "Handoff:",
            f"  {ctx['handoff_text']}",
            ""
        ])
    
    if ctx['recent_sessions']:
        lines.append("Recent sessions:")
        for session in ctx['recent_sessions']:
            lines.append(f"  - {session}")
    
    return "\n".join(lines)


def memory_recall(query: str, limit: int = 5) -> str:
    """Search for memories matching the query.
    
    Args:
        query: Search query text.
        limit: Maximum number of results (default: 5).
        
    Returns:
        Formatted search results as text.
    """
    m = get_memkoshi()
    results = m.recall(query, limit=limit)
    
    if not results:
        return f"No memories found matching: {query}"
    
    lines = [f"Found {len(results)} memories matching '{query}':", ""]
    
    for i, memory in enumerate(results, 1):
        lines.extend([
            f"{i}. [{memory['id']}] {memory['title']}",
            f"   Category: {memory['category']} | Confidence: {memory['confidence']} | Score: {memory['score']:.2f}",
            f"   Content: {memory['content']}",
            ""
        ])
    
    return "\n".join(lines)


def memory_commit(text: str) -> str:
    """Process text and commit extracted memories to staging.
    
    Args:
        text: Text to process for memory extraction.
        
    Returns:
        Processing results as text.
    """
    m = get_memkoshi()
    result = m.commit(text)
    
    lines = [
        "=== Memory Extraction Results ===",
        f"Extracted: {result['extracted_count']} memories",
        f"Staged: {result['staged_count']} memories",
        f"Time: {result['pipeline_time']:.3f}s",
    ]
    
    if result['validation_errors']:
        lines.extend([
            "",
            "Validation errors:",
        ])
        for error in result['validation_errors']:
            lines.append(f"  - {error}")
    else:
        lines.append("\nExtraction successful!")
    
    return "\n".join(lines)


def memory_staged() -> str:
    """List all staged memories pending review.
    
    Returns:
        Formatted list of staged memories as text.
    """
    m = get_memkoshi()
    staged = m.list_staged()
    
    if not staged:
        return "No staged memories pending review."
    
    lines = [f"{len(staged)} staged memories pending review:", ""]
    
    for memory in staged:
        lines.extend([
            f"ID: {memory['id']}",
            f"  Title: {memory['title']}",
            f"  Category: {memory['category']}",
            f"  Content: {memory['content'][:100]}...",
            f"  Staged at: {memory['staged_at']}",
            ""
        ])
    
    return "\n".join(lines)


def memory_approve(memory_id: str) -> str:
    """Approve a staged memory.
    
    Args:
        memory_id: ID of the memory to approve.
        
    Returns:
        Confirmation message.
    """
    m = get_memkoshi()
    
    try:
        m.approve(memory_id)
        return f"Memory {memory_id} approved and indexed."
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Failed to approve memory: {str(e)}"


def memory_reject(memory_id: str, reason: str = "") -> str:
    """Reject a staged memory.
    
    Args:
        memory_id: ID of the memory to reject.
        reason: Reason for rejection (optional).
        
    Returns:
        Confirmation message.
    """
    m = get_memkoshi()
    
    try:
        m.reject(memory_id, reason)
        return f"Memory {memory_id} rejected. Reason: {reason or 'None provided'}"
    except Exception as e:
        return f"Failed to reject memory: {str(e)}"


def memory_stats() -> str:
    """Get storage statistics.
    
    Returns:
        Formatted statistics as text.
    """
    m = get_memkoshi()
    stats = m.stats()
    
    lines = [
        "=== Memkoshi Storage Statistics ===",
        f"Total memories: {stats['total_memories']}",
        f"Staged memories: {stats['staged_memories']}",
        f"Sessions: {stats['session_count']}",
        f"Database size: {stats['database_size']} KB",
        ""
    ]
    
    if stats['memory_categories']:
        lines.append("Memory categories:")
        for category, count in stats['memory_categories'].items():
            lines.append(f"  {category}: {count}")
    
    return "\n".join(lines)


# MCP server setup (only if fastmcp is available)
if HAS_FASTMCP:
    # Create the MCP server
    mcp = FastMCP("memkoshi")
    
    # Register all tools
    mcp.tool()(memory_boot)
    mcp.tool()(memory_recall)
    mcp.tool()(memory_commit)
    mcp.tool()(memory_staged)
    mcp.tool()(memory_approve)
    mcp.tool()(memory_reject)
    mcp.tool()(memory_stats)
    
    # Export the server
    server = mcp
else:
    server = None


def main():
    """Run the MCP server."""
    if not HAS_FASTMCP:
        print("Error: fastmcp not installed. Install with: pip install fastmcp")
        return 1
    
    if server:
        # Run the server
        import asyncio
        asyncio.run(server.run())
    else:
        print("Error: MCP server not initialized")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
