"""Main CLI interface."""

import click
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from ..storage.sqlite import SQLiteBackend
from ..extractors.hybrid import HybridExtractor
from ..core.pipeline import MemoryPipeline
from ..core.session import SessionSummary
from ..core.context import BootContext
from ..search.engine import MemkoshiSearch


@click.group()
@click.option("--storage", default="~/.memkoshi", help="Storage directory")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx, storage, verbose):
    """Memkoshi - The only agent memory system that learns and improves over time."""
    # Initialize components
    storage_backend = SQLiteBackend(storage)
    
    # Store in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj['storage'] = storage_backend
    ctx.obj['verbose'] = verbose
    ctx.obj['storage_path'] = Path(storage).expanduser()


@cli.command()
@click.pass_context
def init(ctx):
    """Initialize memkoshi storage."""
    storage = ctx.obj['storage']
    storage.initialize()
    click.echo(f"Initialized memkoshi storage at {storage.db_path}")


@cli.command()
@click.argument("text", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read from file")
@click.option("--json", "output_json", is_flag=True, help="Output JSON format")
@click.option("--extractor", "-e", default="hybrid", type=click.Choice(["hybrid", "pi", "api"]), help="Extractor: hybrid (local), pi (OAuth), or api (API key)")
@click.option("--provider", default="anthropic", type=click.Choice(["anthropic", "openai"]), help="API provider")
@click.option("--model", default=None, help="Model override")
@click.pass_context
def commit(ctx, text, file, output_json, extractor, provider, model):
    """Extract memories from session text and stage for review."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    # Read input: positional arg > --file > stdin
    if text:
        content = text
    elif file:
        with open(file, 'r') as f:
            content = f.read()
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        click.echo("Error: provide text as argument, --file, or pipe via stdin", err=True)
        sys.exit(1)
    
    if not content.strip():
        click.echo("Error: empty input", err=True)
        sys.exit(1)
    
    # Select extractor
    if extractor == "api":
        from ..extractors.api import APIExtractor
        ext = APIExtractor(provider=provider, model=model)
    elif extractor == "pi":
        from ..extractors.pi import PiExtractor
        ext = PiExtractor(model=model)
    else:
        ext = HybridExtractor()
    ext.initialize()
    pipeline = MemoryPipeline(storage, ext)
    result = pipeline.process(content)
    
    # Update session tracking in context if memories were extracted
    if result["staged_count"] > 0:
        context = storage.get_context()
        if not context:
            context = BootContext()
        
        # Add to recent sessions
        session_summary = f"{content[:80]}... ({result['staged_count']} memories)"
        context.recent_sessions.append(session_summary)
        context.recent_sessions = context.recent_sessions[-3:]  # Keep last 3
        
        # Update staged count
        context.staged_memories_count = result["staged_count"]
        
        # Save context
        storage.store_context(context)
    
    if output_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"extracted: {result['extracted_count']} memories")
        click.echo(f"staged: {result['staged_count']} memories")
        if result.get('validation_errors'):
            for err in result['validation_errors']:
                click.echo(f"  warning: {err}", err=True)
        if result['staged_count'] > 0:
            click.echo("\nHint: Run 'memkoshi review' to approve staged memories.")
            click.echo("      Memories are only searchable via 'memkoshi recall' after approval.")

@cli.command()
@click.option("--limit", "-n", default=10, help="Number of memories to review")
@click.pass_context
def review(ctx, limit):
    """Review staged memories."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    # Get staged memories
    staged = storage.list_staged()
    
    if not staged:
        click.echo("No staged memories to review")
        return
    
    # Review each memory
    reviewed = 0
    for memory in staged[:limit]:
        click.echo(f"\n{'='*60}")
        click.echo(f"Memory ID: {memory.id}")
        click.echo(f"Category: {memory.category.value}")
        click.echo(f"Title: {memory.title}")
        click.echo(f"Abstract: {memory.abstract}")
        click.echo(f"Tags: {', '.join(memory.tags)}")
        click.echo(f"\nContent:\n{memory.content}")
        click.echo(f"\nConfidence: {memory.confidence.value}")
        
        # Get decision
        while True:
            decision = click.prompt("\n[A]pprove / [R]eject / [S]kip / [Q]uit", type=str).lower()
            
            if decision == 'a':
                storage.approve_memory(memory.id, "user")
                # Index the approved memory
                search = MemkoshiSearch(ctx.obj['storage_path'])
                search.initialize()
                # Load the approved memory from storage to get full data
                approved_memory = storage.get_memory(memory.id)
                if approved_memory:
                    search.index_memory(approved_memory)
                click.echo("✓ Approved")
                reviewed += 1
                break
            elif decision == 'r':
                reason = click.prompt("Rejection reason")
                storage.reject_memory(memory.id, reason)
                click.echo("✗ Rejected")
                reviewed += 1
                break
            elif decision == 's':
                click.echo("→ Skipped")
                break
            elif decision == 'q':
                click.echo(f"\nReviewed {reviewed} memories")
                return
            else:
                click.echo("Invalid choice")
    
    click.echo(f"\nReviewed {reviewed} memories")


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output JSON format")
@click.pass_context
def boot(ctx, output_json):
    """Show boot context with current state."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    # Get context from storage
    context = storage.get_context()
    
    # Get stats
    stats = storage.get_stats()
    
    # Count sessions from context
    session_count = 0
    recent_sessions = []
    if context and context.recent_sessions:
        session_count = len(context.recent_sessions)
        recent_sessions = context.recent_sessions
    
    # Build output
    if output_json:
        boot_data = {
            "session_count": session_count,
            "memory_count": stats.get('memories_count', 0),
            "staged_count": stats.get('staged_count', 0),
            "recent_sessions": recent_sessions,
            "handoff": context.handoff if context else None
        }
        click.echo(json.dumps(boot_data))
        return
    
    # Check if search index exists
    search = MemkoshiSearch(str(ctx.obj['storage_path']))
    search.initialize()
    index_path = Path(ctx.obj['storage_path']).expanduser() / "search"
    has_index = any(index_path.glob("*.faiss")) if index_path.exists() else False
    
    # Display boot context
    click.echo("=== Memkoshi Boot Context ===")
    click.echo(f"Sessions: {session_count}")
    click.echo(f"Total memories: {stats.get('memories_count', 0)}")
    click.echo(f"Staged memories: {stats.get('staged_count', 0)}")
    
    if context and context.handoff:
        # For test compatibility
        click.echo(f"{context.handoff}")
    
    if recent_sessions:
        click.echo("\nRecent sessions:")
        for session in recent_sessions:
            click.echo(f"  - {session}")
    else:
        click.echo("\nFresh start")
    
    if not has_index:
        click.echo("\n⚠️  Search index not found. Run 'memkoshi reindex' after approving memories.")
    
    if stats.get('staged_count', 0) > 0:
        click.echo(f"\n💡 {stats.get('staged_count', 0)} memories pending review. Run 'memkoshi review'")

@cli.command()
@click.argument("query")
@click.option("--category", help="Filter by memory category")
@click.option("--limit", "-l", default=5, help="Maximum results")
@click.option("--json", "output_json", is_flag=True, help="Output JSON format")
@click.pass_context
def recall(ctx, query, category, limit, output_json):
    """Recall memories matching query."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    # Try semantic search first
    search_results = None
    try:
        search = MemkoshiSearch(ctx.obj['storage_path'])
        search.initialize()
        search_results = search.search(query, limit=limit, category=category)
        
        if ctx.obj['verbose']:
            click.echo("Using semantic search", err=True)
    except Exception as e:
        if ctx.obj['verbose']:
            click.echo(f"Search failed, using SQL fallback: {e}", err=True)
    
    # Prepare results — use semantic if it returned hits, otherwise fall back to SQL
    if search_results:
        # Use search results - need to load full memories
        memories = []
        for result in search_results:
            memory = storage.get_memory(result['id'])
            if memory:
                memories.append(memory)
    else:
        # Fallback to storage search
        memories = storage.search_memories(query, limit=limit)
        
        # Filter by category if specified
        if category:
            memories = [m for m in memories if m.category.value == category]
    
    if output_json:
        # JSON output
        output_data = []
        for memory in memories:
            output_data.append({
                "id": memory.id,
                "category": memory.category.value,
                "title": memory.title,
                "abstract": memory.abstract,
                "created": memory.created.isoformat()
            })
        click.echo(json.dumps(output_data))
    else:
        # Human-readable output
        if not memories:
            click.echo(f"No memories found matching '{query}'")
        else:
            for memory in memories:
                click.echo(f"\n{memory.title}")
                click.echo(f"Category: {memory.category.value}")
                click.echo(f"Abstract: {memory.abstract}")
                click.echo(f"Created: {memory.created.strftime('%Y-%m-%d')}")


@cli.command()
@click.pass_context
def stats(ctx):
    """Show storage statistics."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    stats = storage.get_stats()
    
    click.echo(f"Total memories: {stats.get('memories_count', 0)}")
    click.echo(f"Staged memories: {stats.get('staged_count', 0)}")
    click.echo(f"Total sessions: {stats.get('sessions_count', 0)}")
    
    click.echo(f"\nMemories by category:")
    for category, count in stats.get('memories_by_category', {}).items():
        click.echo(f"  {category}: {count}")


@cli.command()
@click.pass_context
def reindex(ctx):
    """Rebuild search index from all memories."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    click.echo("Rebuilding search index...")
    
    # Create search engine
    search = MemkoshiSearch(ctx.obj['storage_path'])
    search.initialize()
    
    # Reindex all memories
    count = search.reindex_all(storage)
    
    click.echo(f"✓ Indexed {count} memories")


@cli.command()
@click.option('--storage', '-s', help='Storage path (default: from env or ~/.memkoshi)')
def serve(storage):
    """Start the MCP server for external tool access."""
    if storage:
        os.environ['MEMKOSHI_STORAGE'] = storage
    
    from ..mcp_server import main as mcp_main
    exit_code = mcp_main()
    if exit_code != 0:
        raise click.ClickException("Failed to start MCP server")


@cli.command()
@click.argument("text")
@click.pass_context
def handoff(ctx, text):
    """Save handoff state for next boot."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    # Get current context or create new
    context = storage.get_context()
    if not context:
        context = BootContext()
    
    # Update handoff text
    context.handoff = text
    
    # Save context
    storage.store_context(context)
    
    click.echo(f"Handoff saved: {text}")
