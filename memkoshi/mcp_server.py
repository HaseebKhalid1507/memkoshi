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


def memory_handoff_get() -> str:
    """Get current handoff state.
    
    Returns:
        Current handoff information or message if none set.
    """
    m = get_memkoshi()
    handoff = m.context.get_handoff()
    
    if not handoff:
        return "No handoff state set."
    
    lines = [
        "=== Current Handoff ===",
        f"Task: {handoff['task']}",
        f"Priority: {handoff['priority']}",
    ]
    
    if handoff.get('progress'):
        lines.append(f"Progress: {handoff['progress']}")
    
    if handoff.get('next_steps'):
        lines.append("Next steps:")
        for step in handoff['next_steps']:
            lines.append(f"  • {step}")
    
    lines.append(f"Created: {handoff['created_at']}")
    
    return "\n".join(lines)


def memory_handoff_set(task: str, progress: str = "", details: str = "", priority: int = 3) -> str:
    """Set handoff state for next session.
    
    Args:
        task: What you're working on.
        progress: Current status/what's been done.
        details: Additional context or details.
        priority: Priority level (1=high, 5=low, default=3).
        
    Returns:
        Confirmation message.
    """
    m = get_memkoshi()
    
    # Parse next_steps from details if provided
    next_steps = []
    if details:
        # Simple parsing: split on newlines or semicolons
        if '\n' in details:
            next_steps = [step.strip() for step in details.split('\n') if step.strip()]
        elif ';' in details:
            next_steps = [step.strip() for step in details.split(';') if step.strip()]
    
    m.context.set_handoff(
        task=task,
        progress=progress,
        details={'raw_details': details} if details else None,
        next_steps=next_steps,
        priority=priority
    )
    
    return f"✓ Handoff set: {task}"


def memory_context_boot(token_budget: int = 4096) -> str:
    """Get boot context with token budget optimization.
    
    Args:
        token_budget: Maximum tokens to use (default: 4096).
        
    Returns:
        Formatted boot context optimized for the token budget.
    """
    m = get_memkoshi()
    boot_context = m.context.get_boot(token_budget=token_budget)
    
    lines = [
        f"=== Boot Context (Budget: {token_budget} tokens) ===",
        f"Token estimate: {boot_context.get('token_count_estimate', 0)}",
        ""
    ]
    
    if boot_context.get('handoff'):
        h = boot_context['handoff']
        lines.extend([
            "🔄 Handoff:",
            f"  Task: {h['task']}",
        ])
        if h.get('progress'):
            lines.append(f"  Progress: {h['progress']}")
        lines.append("")
    
    if boot_context.get('recent_sessions'):
        lines.append("📝 Recent Sessions:")
        for session in boot_context['recent_sessions']:
            lines.append(f"  • {session.get('summary', '')[:80]}...")
        lines.append("")
    
    stats = boot_context.get('memory_stats', {})
    if stats:
        lines.extend([
            "📊 Memory Stats:",
            f"  Total: {stats.get('total_memories', 0)}",
            f"  Staged: {stats.get('staged_memories', 0)}"
        ])
    
    return "\n".join(lines)


# ── v0.4 Pattern Detection & Evolution Tools ──────────────────────────────────────────────

def memory_patterns() -> str:
    """Get detected behavioral patterns.
    
    Returns:
        Formatted patterns as text.
    """
    m = get_memkoshi()
    patterns = m.patterns.detect()
    
    if not patterns:
        return "No patterns detected yet."
    
    lines = ["=== Behavioral Patterns ===", ""]
    for p in patterns:
        lines.extend([
            f"[{p.pattern_type.upper()}] {p.name}",
            f"  {p.description}",
            f"  Confidence: {p.confidence:.2f} (n={p.sample_size})",
            ""
        ])
    
    return "\n".join(lines)


def memory_insights() -> str:
    """Get pattern-based behavioral insights.
    
    Returns:
        Formatted insights as text.
    """
    m = get_memkoshi()
    insights = m.patterns.insights()
    
    if not insights:
        return "No insights available yet. Need more usage data."
    
    lines = ["=== Pattern Insights ===", ""]
    for i, insight in enumerate(insights, 1):
        lines.append(f"{i}. {insight}")
    
    return "\n".join(lines)


def memory_evolve_score(session_input: str, session_id: str = None) -> str:
    """Score a session for evolution tracking.
    
    Args:
        session_input: Session text or structured data
        session_id: Optional session ID for storage
        
    Returns:
        Formatted scoring results.
    """
    m = get_memkoshi()
    result = m.evolve.score(session_input, session_id)
    
    method = 'structured' if isinstance(session_input, dict) else 'keyword heuristics'
    
    lines = [
        "=== Session Score ===",
        f"Score: {result['score']:.1f}/10.0",
        f"Task completion: {result.get('tasks_completed', 'N/A')}",
        f"Errors: {result.get('errors', result.get('error_count', 'N/A'))}",
        f"Analysis method: {method}"
    ]
    
    return "\n".join(lines)


def memory_evolve_hints() -> str:
    """Get behavioral improvement hints.
    
    Returns:
        Formatted improvement hints.
    """
    m = get_memkoshi()
    insights = m.evolve.hints()
    
    if not insights:
        return "No insights available yet. Need more session data."
    
    lines = ["=== Evolution Insights ===", ""]
    for i, insight in enumerate(insights, 1):
        lines.append(f"{i}. {insight}")
    
    return "\n".join(lines)


def memory_evolve_status() -> str:
    """Get evolution status and performance dashboard.
    
    Returns:
        Formatted evolution status.
    """
    m = get_memkoshi()
    status = m.evolve.status()
    
    if status.get('error'):
        return f"Error: {status['error']}"
    
    lines = [
        "=== Evolution Status ===",
        f"Recent sessions (30d): {status.get('recent_sessions_30d', 0)}",
        f"Average score (30d): {status.get('average_score_30d', 0.0)}",
        f"Performance trend: {status.get('trend_7d', 'unknown')}",
        ""
    ]
    
    best = status.get('best_session', {})
    if best.get('id'):
        lines.extend([
            f"Best session: {best['id']}",
            f"Best score: {best['score']}"
        ])
    
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
    
    # New context management tools
    mcp.tool()(memory_handoff_get)
    mcp.tool()(memory_handoff_set)
    mcp.tool()(memory_context_boot)
    
    # v0.4 Pattern detection and evolution tools
    mcp.tool()(memory_patterns)
    mcp.tool()(memory_insights)
    mcp.tool()(memory_evolve_score)
    mcp.tool()(memory_evolve_hints)
    mcp.tool()(memory_evolve_status)
    
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
