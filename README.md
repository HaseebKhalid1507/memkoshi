# Memkoshi

**The only agent memory system that doesn't suck.**

Your AI agent has the memory of a goldfish. Every conversation starts from zero. Every decision gets re-made. Every lesson gets re-learned. That ends now.

Memkoshi extracts structured memories from conversations, stages them for review (because trust is earned), and makes them searchable forever. No vendor lock-in. No API keys. No bullshit.

```bash
# 30-second demo that actually works
pip install memkoshi
memkoshi init
echo "We decided to use Rust for the backend because Python was too slow" | memkoshi commit
memkoshi review  # approve the extracted memory
memkoshi recall "backend choice"
# Returns: "We decided to use Rust for the backend..."
```

## Why This Exists

Every other "AI memory" solution is either:
- **Academic research** (unusable)
- **SaaS vendor lock-in** (expensive, dies when the startup does)  
- **Vector databases** (no extraction, just embedding storage)
- **LLM-powered extractors** (expensive, unreliable, need API keys)

We built something different. Something that works locally, extracts intelligently, and lets you stay in control.

## What Makes It Different

### 🧠 **Rule-Based Extraction** 
Finds decisions, preferences, solutions, and entities using pattern matching. No LLM calls. No API costs. No vendor dependencies.

### 🎭 **Staging Workflow**
Extracted memories must be reviewed before becoming permanent. Because AI isn't perfect and neither are conversations.

### 🔍 **Semantic Search**
VelociRAG integration for meaning-based search, with SQL fallback when needed.

### 🔌 **Universal Integration**
CLI, Python API, and MCP server. Works with Claude Code, pi, LangChain, custom agents — anything.

### 📦 **Actually Tested**
117 tests. All passing. In 0.30 seconds. Because we're not shipping broken software.

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

## Python API

```python
from memkoshi import Memkoshi

# Initialize local storage
m = Memkoshi("~/.memkoshi")
m.init()

# Process conversation
m.commit("The client wants real-time updates, so we're switching to WebSockets")

# Review staged memories
staged = m.list_staged()
for memory in staged:
    print(f"{memory['title']}: {memory['content']}")
    m.approve(memory['id'])  # or m.reject(memory['id'])

# Search memories
results = m.recall("websockets", limit=5)
for memory in results:
    print(f"[{memory['confidence']}] {memory['title']}")
```

## MCP Server Integration

Memkoshi includes an MCP server for seamless agent integration:

```bash
memkoshi serve  # Starts MCP server
# Connect any MCP-compatible agent for automatic memory integration
```

## vs. The Competition

**Memkoshi**: Local extraction → staging workflow → semantic search  
**Mem0**: Cloud LLM extraction → direct storage → vector search  
**Zep**: Session summaries → cloud storage → basic search

We're the only one with local-first architecture and human-in-the-loop memory approval.

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
memkoshi recall "query"      # Search memories
memkoshi boot               # Show system status
memkoshi stats              # Storage statistics
memkoshi reindex            # Rebuild search index
memkoshi serve              # Start MCP server
```

## What v0.1 Actually Has

We don't lie about features. Here's what actually works today:

- ✅ Rule-based memory extraction (decisions, preferences, entities, problems/solutions)
- ✅ Staging workflow with interactive review
- ✅ Local SQLite storage with HMAC signing
- ✅ VelociRAG semantic search integration
- ✅ CLI, Python API, and MCP server
- ✅ Memory deduplication and confidence scoring
- ✅ 117 tests, all passing
- ❌ Pattern learning from user feedback (v0.2)
- ❌ Memory relationship graphs (v0.2)
- ❌ Bulk document import (v0.2)

## Requirements

- Python 3.8+
- ~20MB storage per 1000 memories
- No internet required (except for optional VelociRAG features)

## Contributing

```bash
git clone https://github.com/yourusername/memkoshi
cd memkoshi
pip install -e ".[dev]"
pytest tests/  # Should pass in <1s
```

We have opinions about code quality. Tests are required. Documentation is required. Breaking changes need good reasons.

## License

MIT. Because lock-in is for losers.

---

**Built by agents, for agents. Memory is the foundation of intelligence.**