# Memkoshi

![Tests](https://img.shields.io/badge/tests-239_passing-green) ![PyPI](https://img.shields.io/badge/PyPI-v0.3.0-blue) ![Python](https://img.shields.io/badge/python-3.8+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

**The only agent memory system that doesn't treat you like an idiot.**

Your AI agent has the memory of a goldfish. Every conversation starts from zero. Every decision gets re-made. Every lesson gets re-learned. That ends now.

Memkoshi is a production-grade memory library with **three-tier extraction architecture**, **four-layer search engine**, **context management**, **session lifecycle**, **search daemon**, and **cryptographic integrity**. Born from a real agent system that ran 100+ sessions. 53 production memories imported with 100% recall on test queries.

No vendor lock-in. No API requirements. No bullshit.

### 🔗 One Memory, Every Agent

Using Claude Code *and* Gemini CLI? Memkoshi is the shared memory layer between them. Both agents connect to the same `~/.memkoshi` store via MCP — Claude learns something in the morning, Gemini remembers it by afternoon. **Agent-agnostic memory that works across your entire toolkit.**

```
Claude Code ──→ memkoshi ──→ ┌──────────────┐
                              │  ~/.memkoshi  │  shared memory store
Gemini CLI  ──→ memkoshi ──→ └──────────────┘
```

```bash
# 30-second demo that actually works
pip install memkoshi
memkoshi init
echo "We decided to use Rust for the backend because Python was too slow" | memkoshi commit
memkoshi review  # approve the extracted memory
memkoshi recall "backend choice"
# Returns: "We decided to use Rust for the backend..."
```

## Architecture: Why This Doesn't Suck

```
Text → Extractor (hybrid/pi/api) → Staged Memories → Review → Permanent Storage → Search (VelociRAG 4-layer)
```

### 🎛️ **Three-Tier Extraction Architecture**

You choose your extraction quality vs. cost tradeoff:

- **`HybridExtractor`** (default): Rule-based regex patterns. **Zero API costs.** Finds decisions, preferences, problems/solutions, and entities using pattern matching.
- **`PiExtractor`**: OAuth-based LLM extraction via pi. No API keys needed, better extraction quality.
- **`ApiExtractor`**: OpenAI/Anthropic API keys for maximum extraction sophistication.

No other memory library gives you this flexibility. Start free, scale up when you need it.

### 🔍 **Four-Layer VelociRAG Search**

Not just "semantic search." The search engine combines:

1. **Vector search** (FAISS, all-MiniLM-L6-v2 embeddings)
2. **BM25 keyword search** (SQLite FTS5) 
3. **Knowledge graph traversal** (entity extraction, relationship mapping)
4. **Metadata filtering** (tags, categories, dates)

Results fused with RRF + cross-encoder reranking. Falls back to pure SQL when VelociRAG isn't installed.

### 🔒 **HMAC Cryptographic Signing**

Every memory is signed with HMAC-SHA256. Tamper detection. Integrity verification. Because if you can't trust your memory system, you can't trust anything.

### 🏗️ **Born From Production**

This isn't a weekend project. Extracted from **Jawz**, a real AI agent system that processed 100+ actual conversation sessions. We know this works because it already worked.

## Why This Exists

Every other "AI memory" solution is either:
- **Academic research** (unusable)
- **SaaS vendor lock-in** (expensive, dies when the startup does)  
- **Vector databases** (no extraction, just embedding storage)
- **LLM-only extractors** (expensive, unreliable, need API keys)

We built something different. Something that works locally, extracts intelligently at any budget, and lets you stay in control.

## The Staging Workflow (The Killer Feature)

```
Conversation → Extract → Stage → Review → Memory → Search
```

Nobody else has the staging step. Everyone else trusts the AI extractor completely. We don't, because we're not idiots.

```bash
# Extract memories (creates staged entries)
memkoshi commit "Meeting notes: decided on PostgreSQL, John prefers Docker"

# Review what was extracted  
memkoshi review
# Memory 1: "Decision about PostgreSQL database choice" [A]pprove / [R]eject / [S]kip?

# Search approved memories
memkoshi recall "database decision"
```

## Context & Handoff

Seamless state transfer between sessions. Set handoff for the next developer, get boot context within token budgets, checkpoint mid-session progress.

```python
# Set handoff for next session
mk.context.set_handoff(task="Building auth API", progress="endpoints done", priority=4)

# Get boot context (token-budgeted)
boot = mk.context.get_boot(token_budget=4096)

# Checkpoint mid-session
mk.context.checkpoint(notes="Auth endpoints working, starting tests")
```

## Session Lifecycle

Managed session contexts with automatic memory extraction. Perfect for agent loops and conversation boundaries.

```python
mk = Memkoshi("~/.memkoshi", enable_auto_extract=True)
mk.init()

with mk.session("debugging login issue") as s:
    s.add_message("user", "Login timeout reproduced")
    s.add_message("assistant", "Redis TTL was set to 0")
    # Auto-extracts memories on exit
```

## Search Daemon

Keeps VelociRAG warm in memory for instant search responses. Production-ready daemon with health monitoring.

```bash
memkoshi serve              # Start daemon (keeps search warm)
memkoshi serve-status       # Check health
```

## Python API

```python
from memkoshi import Memkoshi

# Initialize with your preferred extractor
m = Memkoshi("~/.memkoshi", extractor="hybrid")  # or "pi" or "api"
m.init()

# Process conversation
m.commit("The client wants real-time updates, so we're switching to WebSockets")

# Review staged memories
staged = m.list_staged()
for memory in staged:
    print(f"{memory['title']}: {memory['content']}")
    m.approve(memory['id'])  # or m.reject(memory['id'])

# Search memories (four-layer VelociRAG)
results = m.recall("websockets", limit=5)
for memory in results:
    print(f"[{memory['confidence']}] {memory['title']}")
```

## MCP Server Integration

Memkoshi ships a full MCP server with 10 tools. Any MCP-compatible agent gets persistent memory out of the box.

### Claude Code / pi

Add to your `~/.claude/settings.json` or `.pi/settings.json`:

```json
{
  "mcpServers": {
    "memkoshi": {
      "command": "memkoshi",
      "args": ["serve"]
    }
  }
}
```

That's it. Your agent now has access to:

| Tool | What It Does |
|------|-------------|
| `memory_commit` | Extract memories from conversation text |
| `memory_recall` | Search memories by meaning (4-layer VelociRAG) |
| `memory_staged` | List memories pending review |
| `memory_approve` | Approve a staged memory |
| `memory_reject` | Reject a staged memory |
| `memory_boot` | Get boot context (session count, handoff, recent sessions) |
| `memory_stats` | Storage statistics |
| `memory_handoff_get` | Get current handoff state |
| `memory_handoff_set` | Set handoff for next session |
| `memory_context_boot` | Get token-budgeted boot context |

### Custom Storage Path

```bash
MEMKOSHI_STORAGE=~/my-agent/.memkoshi memkoshi serve
```

### LangChain / Custom Agents

```python
from memkoshi import Memkoshi

# Drop this into any agent loop
m = Memkoshi("~/.memkoshi")
m.init()

# After each conversation turn
m.commit(conversation_text)

# Before each response
context = m.recall(user_query, limit=5)
```

No daemon. No background process. No config files beyond the MCP JSON. It just works.

### Multi-Agent, One Memory

The real power: point multiple agents at the same storage. Claude Code and Gemini CLI both get MCP config → both read and write the same memories → knowledge transfers automatically between tools.

```bash
# Same store, both agents
# Claude Code:  ~/.claude/settings.json → memkoshi serve
# Gemini CLI:   ~/.gemini/settings.json → memkoshi serve
# Result: shared persistent memory across all your AI tools
```

## vs. The Competition

| Feature | Memkoshi | Mem0 | Zep | Letta/MemGPT | LangChain Memory |
|---------|----------|------|-----|-------------|------------------|
| **Local-first** | ✅ | ❌ | ❌ | ✅ | ✅ |
| **Staging workflow** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Multi-tier extraction** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **No API keys required** | ✅ | ❌ | ❌ | ✅ | ✅ |
| **Structured extraction** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Knowledge graph** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Cryptographic signing** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Cross-session persistence** | ✅ | ✅ | ✅ | ✅ | ❌ |

**Memkoshi**: Local extraction → staging workflow → cryptographically signed → four-layer search  
**Mem0**: Cloud LLM extraction → direct storage → vector search  
**Zep**: Session summaries → cloud storage → basic search  
**Letta**: Full agent framework (not modular memory), heavy dependencies  
**LangChain**: Conversation buffer only, no extraction, no persistence

We're the only one with local-first architecture, human-in-the-loop approval, and multi-tier extraction.

## Install & Quick Start

```bash
# Install
pip install memkoshi

# Initialize storage
memkoshi init

# Process a conversation
echo "Important decision: switching to TypeScript for better type safety" | memkoshi commit

# Review extracted memories
memkoshi review

# Search your memories  
memkoshi recall "typescript decision"

# Check system status
memkoshi boot
```

## CLI Commands

```bash
memkoshi commit "text"        # Extract memories from text
memkoshi review              # Interactive memory review
memkoshi recall "query"      # Search memories (4-layer VelociRAG)
memkoshi boot               # Show system status
memkoshi stats              # Storage statistics
memkoshi reindex            # Rebuild search index
memkoshi serve              # Start search daemon
memkoshi serve-status       # Check daemon health
memkoshi serve-stop         # Stop daemon
memkoshi mcp-serve          # Start MCP server
memkoshi handoff set        # Set handoff state
memkoshi handoff show       # Show current handoff
memkoshi handoff clear      # Clear handoff
memkoshi context boot       # Get boot context
```

## What v0.3 Actually Has

We don't lie about features. Here's what actually works today:

- ✅ Three-tier extraction architecture (hybrid/pi/api)
- ✅ Four-layer VelociRAG search engine with knowledge graph
- ✅ Staging workflow with interactive review
- ✅ Local SQLite storage with HMAC-SHA256 signing
- ✅ CLI, Python API, and MCP server
- ✅ Memory deduplication and confidence scoring
- ✅ **239 tests**, all passing in 0.30 seconds
- ✅ Cross-encoder reranking and RRF fusion
- ❌ Pattern learning from user feedback (v0.2)
- ❌ Memory relationship graphs visualization (v0.2)
- ❌ Bulk document import (v0.2)

## Requirements

- Python 3.8+
- ~20MB storage per 1000 memories
- No internet required (except for optional pi/api extractors and VelociRAG features)
- Optional: VelociRAG for enhanced search capabilities

## Contributing

```bash
git clone https://github.com/HaseebKhalid1507/memkoshi
cd memkoshi
pip install -e ".[dev]"
pytest tests/  # Should pass 142 tests in <1s
```

We have opinions about code quality. Tests are required. Documentation is required. Breaking changes need good reasons.

## License

MIT. Because lock-in is for losers.

---

**Built by agents, for agents. Memory is the foundation of intelligence.**