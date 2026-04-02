"""Main CLI interface."""

import click
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from ..storage.sqlite import SQLiteBackend
from ..extractors.hybrid import HybridExtractor
from ..core.pipeline import MemoryPipeline
from ..core.session import SessionSummary
from ..core.context import BootContext
from ..core.context_manager import ContextManager
from ..search.engine import MemkoshiSearch
from ..core.patterns import PatternDetector
from ..core.evolution import EvolutionEngine


@click.group()
@click.option("--storage", default=None, help="Storage directory")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx, storage, verbose):
    """Memkoshi - The only agent memory system that learns and improves over time."""
    # Priority: --storage flag > MEMKOSHI_STORAGE env > default ~/.memkoshi
    if storage is None:
        storage = os.environ.get('MEMKOSHI_STORAGE', '~/.memkoshi')
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
@click.option('--storage-path', default=None, help='Storage directory')
@click.option('--socket-path', help='Unix socket path (auto-generated if not specified)')
@click.option('--max-memory', default=1024, help='Maximum memory usage in MB')
@click.option('--daemon', is_flag=True, help='Run as background daemon')
@click.option('--log-level', default='INFO', help='Logging level')
def serve(storage_path, socket_path, max_memory, daemon, log_level):
    """Start search daemon to keep VelociRAG warm in memory."""
    import logging
    import os
    
    if storage_path is None:
        storage_path = os.environ.get('MEMKOSHI_STORAGE', '~/.memkoshi')
    storage_path = Path(storage_path).expanduser()
    if not storage_path.exists():
        click.echo(f"Error: Storage path does not exist: {storage_path}")
        sys.exit(1)
    
    if not socket_path:
        socket_path = f"/tmp/memkoshi-search-{os.getuid()}.sock"
    
    # Configure logging
    logging.basicConfig(level=getattr(logging, log_level.upper()))
    
    from ..daemon.server import MemkoshiDaemon
    
    # Start daemon
    daemon_instance = MemkoshiDaemon(
        storage_path=str(storage_path),
        socket_path=socket_path,
        max_memory_mb=max_memory
    )
    
    if daemon:
        # Fork into background
        pid = os.fork()
        if pid > 0:
            # Parent — print PID and exit
            click.echo(f"✓ Daemon started (PID {pid})")
            return
        # Child — detach
        os.setsid()
        # Redirect stdin to /dev/null, stdout/stderr to log file
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.close(devnull)
        log_path = os.path.join(str(storage_path), 'daemon.log')
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        os.close(log_fd)
        # Write PID file
        pid_path = f"/tmp/memkoshi-daemon-{os.getuid()}.pid"
        with open(pid_path, 'w') as f:
            f.write(str(os.getpid()))
    
    try:
        daemon_instance.start()
    except KeyboardInterrupt:
        if not daemon:
            click.echo("\nShutting down daemon...")


@cli.command("serve-stop")
def serve_stop():
    """Stop running search daemon."""
    import os
    import socket
    from ..daemon.protocol import send_message, recv_message
    
    socket_path = f"/tmp/memkoshi-search-{os.getuid()}.sock"
    
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        
        send_message(sock, {"cmd": "shutdown"})
        response = recv_message(sock)
        sock.close()
        
        if response["status"] == "success":
            click.echo("✓ Daemon stopped")
        else:
            click.echo(f"Error: {response['error']}")
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error: Could not connect to daemon: {e}")
        sys.exit(1)


@cli.command("serve-status")
def serve_status():
    """Show search daemon status."""
    import os
    import socket
    from ..daemon.protocol import send_message, recv_message
    
    socket_path = f"/tmp/memkoshi-search-{os.getuid()}.sock"
    
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        
        send_message(sock, {"cmd": "health"})
        response = recv_message(sock)
        sock.close()
        
        if response["status"] == "success":
            health = response["data"]
            click.echo("=== Search Daemon Status ===")
            click.echo(f"Status: ✓ Running")
            click.echo(f"Version: {health['daemon_version']}")
            click.echo(f"Uptime: {health['uptime_seconds']}s")
            click.echo(f"Memory: {health['memory_usage_mb']}MB")
            click.echo(f"Requests: {health['request_stats']['total_requests']}")
            click.echo(f"Avg response: {health['request_stats']['avg_response_ms']}ms")
        else:
            click.echo(f"Error: {response['error']}")
            sys.exit(1)
    except Exception:
        click.echo("=== Search Daemon Status ===")
        click.echo("Status: ❌ Not running")


@cli.command()
@click.option('--storage', '-s', help='Storage path (default: from env or ~/.memkoshi)')
def mcp_serve(storage):
    """Start the MCP server for external tool access."""
    if storage:
        os.environ['MEMKOSHI_STORAGE'] = storage
    
    from ..mcp_server import main as mcp_main
    exit_code = mcp_main()
    if exit_code != 0:
        raise click.ClickException("Failed to start MCP server")


@cli.group()
def handoff():
    """Manage handoff state between sessions."""
    pass


@handoff.command("set")
@click.argument("task")
@click.option("--progress", "-p", default="", help="Current progress")
@click.option("--next", "-n", multiple=True, help="Next steps (can be repeated)")
@click.option("--priority", "-P", default=3, type=int, help="Priority level (1=high, 5=low)")
@click.pass_context
def handoff_set(ctx, task, progress, next, priority):
    """Set handoff state for next session."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    context_manager = ContextManager(storage)
    context_manager.set_handoff(
        task=task,
        progress=progress,
        next_steps=list(next),
        priority=priority
    )
    
    click.echo(f"✓ Handoff set: {task}")
    if progress:
        click.echo(f"  Progress: {progress}")
    if next:
        click.echo(f"  Next steps: {', '.join(next)}")


@handoff.command("show")
@click.pass_context
def handoff_show(ctx):
    """Show current handoff state."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    context_manager = ContextManager(storage)
    handoff = context_manager.get_handoff()
    
    if handoff:
        click.echo(f"Task: {handoff['task']}")
        click.echo(f"Priority: {handoff['priority']}")
        if handoff['progress']:
            click.echo(f"Progress: {handoff['progress']}")
        if handoff['next_steps']:
            click.echo(f"Next steps:")
            for step in handoff['next_steps']:
                click.echo(f"  • {step}")
        click.echo(f"Created: {handoff['created_at']}")
    else:
        click.echo("No handoff state set.")


@handoff.command("clear")
@click.pass_context
def handoff_clear(ctx):
    """Clear current handoff state."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    context_manager = ContextManager(storage)
    cleared = context_manager.clear_handoff()
    
    if cleared:
        click.echo("✓ Handoff cleared.")
    else:
        click.echo("No handoff to clear.")


@cli.group()
def context():
    """Manage context data and sessions."""
    pass


@context.command("boot")
@click.option("--budget", "-b", default=4096, type=int, help="Token budget")
@click.option("--json", "output_json", is_flag=True, help="Output JSON format")
@click.pass_context
def context_boot(ctx, budget, output_json):
    """Show boot context with token budget."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    context_manager = ContextManager(storage)
    boot_context = context_manager.get_boot(token_budget=budget)
    
    if output_json:
        click.echo(json.dumps(boot_context, indent=2))
    else:
        click.echo(f"=== Boot Context (Budget: {budget} tokens) ===")
        click.echo(f"Token estimate: {boot_context.get('token_count_estimate', 0)}")
        
        if boot_context.get('handoff'):
            h = boot_context['handoff']
            click.echo(f"\n🔄 Handoff: {h['task']}")
            if h.get('progress'):
                click.echo(f"   Progress: {h['progress']}")
        
        if boot_context.get('recent_sessions'):
            click.echo(f"\n📝 Recent Sessions:")
            for session in boot_context['recent_sessions']:
                click.echo(f"  • {session.get('summary', '')[:80]}...")
        
        stats = boot_context.get('memory_stats', {})
        if stats:
            click.echo(f"\n📊 Memory Stats:")
            click.echo(f"  Total: {stats.get('total_memories', 0)}")
            click.echo(f"  Staged: {stats.get('staged_memories', 0)}")


# ── v0.4 Pattern Detection Commands ──────────────────────────────────────────

@cli.group()
@click.pass_context
def patterns(ctx):
    """Pattern detection and analysis."""
    pass

@patterns.command()
@click.pass_context
def detect(ctx):
    """Run pattern detection."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    detector = PatternDetector(storage)
    patterns = detector.detect()
    
    if not patterns:
        click.echo("No patterns detected.")
        return
    
    click.echo(f"Found {len(patterns)} patterns:")
    for p in patterns:
        click.echo(f"  [{p.pattern_type.upper()}] {p.name} (confidence: {p.confidence:.2f})")
        click.echo(f"    {p.description}")
        click.echo()

@patterns.command()
@click.pass_context
def insights(ctx):
    """Get pattern-based insights."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    detector = PatternDetector(storage)
    insights = detector.insights()
    
    if not insights:
        click.echo("No insights available yet.")
        return
    
    click.echo("Pattern Insights:")
    for i, insight in enumerate(insights, 1):
        click.echo(f"  {i}. {insight}")

@patterns.command()
@click.pass_context
def stats(ctx):
    """Get usage statistics."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    detector = PatternDetector(storage)
    stats = detector.stats()
    
    if stats.get('error'):
        click.echo(f"Error: {stats['error']}")
        return
    
    click.echo(f"Total events: {stats.get('total_events', 0)}")
    click.echo(f"Recent activity (7d): {stats.get('recent_activity_7d', 0)}")
    
    events_by_type = stats.get('events_by_type', {})
    if events_by_type:
        click.echo("\nEvents by type:")
        for event_type, count in events_by_type.items():
            click.echo(f"  {event_type}: {count}")


# ── v0.4 Evolution Commands ──────────────────────────────────────────────────

@cli.group()
@click.pass_context
def evolve(ctx):
    """Evolution and session scoring."""
    pass

@evolve.command()
@click.argument("session_text")
@click.option("--session-id", help="Session ID for storage")
@click.pass_context
def score(ctx, session_text, session_id):
    """Score a session."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    engine = EvolutionEngine(storage)
    result = engine.score(session_text, session_id)
    
    click.echo(f"Score: {result['score']:.1f}/10.0")
    click.echo(f"Tasks completed: {result.get('tasks_completed', 'N/A')}")
    click.echo(f"Errors: {result.get('errors', result.get('error_count', 'N/A'))}")
    
    sat_keywords = result.get('satisfaction_keywords', {})
    if isinstance(sat_keywords, dict):
        if sat_keywords.get('positive', 0) > 0:
            click.echo(f"Positive sentiment: {sat_keywords['positive']}")
        if sat_keywords.get('negative', 0) > 0:
            click.echo(f"Negative sentiment: {sat_keywords['negative']}")

@evolve.command()
@click.pass_context
def hints(ctx):
    """Get behavioral improvement hints."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    engine = EvolutionEngine(storage)
    insights = engine.hints()
    
    if not insights:
        click.echo("No hints available yet.")
        return
    
    click.echo("Evolution Insights:")
    for i, insight in enumerate(insights, 1):
        click.echo(f"  {i}. {insight}")

@evolve.command()
@click.pass_context
def status(ctx):
    """Get evolution status dashboard."""
    storage = ctx.obj['storage']
    storage.initialize()
    
    engine = EvolutionEngine(storage)
    status = engine.status()
    
    if status.get('error'):
        click.echo(f"Error: {status['error']}")
        return
    
    click.echo(f"Recent sessions (30d): {status.get('recent_sessions_30d', 0)}")
    click.echo(f"Average score (30d): {status.get('average_score_30d', 0.0)}")
    click.echo(f"Trend (7d): {status.get('trend_7d', 'unknown')}")
    
    best = status.get('best_session', {})
    if best.get('id'):
        click.echo(f"Best session: {best['id']} (score: {best['score']})")


if __name__ == '__main__':
    cli()
