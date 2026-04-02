# Memkoshi

![Tests](https://img.shields.io/badge/tests-316_passing-green) ![Version](https://img.shields.io/badge/version-0.4.0-blue) ![Python](https://img.shields.io/badge/python-3.8+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

**AI agents have the memory of a goldfish. Every session starts from zero. Every decision gets re-made. Every lesson gets re-learned. Memkoshi fixes that.**

Production-grade memory library with staging gates, four-layer search, pattern detection, and evolution scoring. No vendor lock-in. No API requirements. Local-first with intelligent features that actually work.

## The Problem

Your AI assistant forgets everything the moment the conversation ends. Yesterday's debugging session, last week's architecture decisions, that API key you mentioned three times — gone. You're stuck in Groundhog Day with artificial intelligence.

## The Solution

Memkoshi is a memory system that thinks like you do. It extracts important information, stages it for review (the key differentiator), stores it with cryptographic integrity, and finds it instantly when you need it. Four-layer VelociRAG search combines vector similarity, keyword matching, knowledge graphs, and metadata filtering. Pattern detection learns from your behavior. Evolution scoring tracks if you're getting better.

Local SQLite storage. No cloud dependencies. Memories survive forever.

## 30-Second Demo

```bash
pip install git+https://github.com/HaseebKhalid1507/memkoshi.git
memkoshi init
echo "We chose PostgreSQL over MySQL for the new auth service" | memkoshi commit
memkoshi review  # approve the extracted memory
memkoshi recall "database decision"
# Returns: "We chose PostgreSQL over MySQL for the new auth service"
```

## Cross-Agent Memory

Connect any MCP-compatible agent to the same memory store. Claude Code learns something in the morning, Gemini CLI remembers it by afternoon.

```json
// ~/.claude/settings.json or ~/.gemini/settings.json
{
  "mcpServers": {
    "memkoshi": {
      "command": "memkoshi",
      "args": ["mcp-serve"]
    }
  }
}
```

Result: One memory system, every AI tool you use.

## Architecture 

```
Text → Extractor (hybrid/pi/api) → Staging → Review → Permanent → Four-Layer Search
                                                         ↓
                                              Event Buffer → Patterns → Evolution
```

The staging gate is what makes Memkoshi different. Other systems auto-store everything the AI extracts, including hallucinations and noise. Memkoshi gives you a review step. Approve the good stuff, reject the garbage.

## Core Features

### Three-Tier Extraction

Choose your quality vs. cost tradeoff:

- **Hybrid** (default): Local regex patterns, zero API costs, 70% quality
- **Pi**: OAuth-based LLM extraction, no API keys needed  
- **Api**: Direct OpenAI/Anthropic API keys for maximum quality

```python
from memkoshi import Memkoshi

# Start free, scale up when needed
mk = Memkoshi("~/.memkoshi", extractor="hybrid")
mk.init()
mk.commit("Switched to PostgreSQL because MySQL was too slow")
```

### Staging Workflow

The killer feature that nobody else has. Extracted memories go to staging first, not straight to permanent storage.

```python
# Extract memories
result = mk.commit("Meeting notes: John prefers Docker, rejected Kubernetes")

# Review what was extracted
staged = mk.list_staged()
for memory in staged:
    print(f"Title: {memory['title']}")
    print(f"Content: {memory['content']}")

# Approve or reject
mk.approve(memory['id'])  # or mk.reject(memory['id'])
```

### Four-Layer VelociRAG Search

Not just semantic similarity. Real search that understands context.

1. **Vector search**: FAISS embeddings (all-MiniLM-L6-v2)
2. **Keyword search**: BM25 with SQLite FTS5
3. **Knowledge graph**: Entity relationships and temporal connections  
4. **Metadata filtering**: Categories, confidence, dates

Results fused with reciprocal rank fusion and cross-encoder reranking.

```python
results = mk.recall("database decision", limit=5)
for memory in results:
    print(f"[{memory['confidence']}] {memory['title']}")
    print(f"Score: {memory['score']:.2f} | Layers: {memory['source_layers']}")
```

### Context & Handoff

Seamless state transfer between sessions. Boot context with token budgets, handoff for multi-session work.

```python
# Set handoff for next session
mk.context.set_handoff(
    task="Building auth API", 
    progress="endpoints done", 
    next_steps=["Add tests", "Deploy staging"]
)

# Get token-budgeted boot context
boot = mk.context.get_boot(token_budget=4096)
```

### Session Lifecycle

Automatic memory extraction with context managers. Perfect for agent loops.

```python
with mk.session("debugging login issue") as s:
    s.add_message("user", "Login timeout reproduced")
    s.add_message("assistant", "Redis TTL was set to 0, fixed it")
    # Auto-extracts memories on exit
```

### Pattern Detection (NEW v0.4)

The only memory system that learns from your behavior. SQL-based pattern recognition with zero ML dependencies.

- **Frequency patterns**: Memories accessed 3+ times
- **Knowledge gaps**: Failed searches that repeat
- **Temporal patterns**: Day-of-week usage habits

```python
patterns = mk.patterns.detect()
insights = mk.patterns.insights()
# "You search for authentication issues most on Mondays"
# "Consider adding content about Redis TTL configuration"
```

### Evolution Scoring (NEW v0.4)

Track if you're actually getting better. Session scoring based on task completion, error rates, and memory system usage.

```python
score = mk.evolve.score({
    "tasks_completed": 7,
    "tasks_attempted": 8, 
    "errors": 1,
    "duration_minutes": 45
})
# Returns: {"score": 7.1, "task_completion_rate": 0.875, "errors": 1, ...}

hints = mk.evolve.hints()
# "High-scoring sessions actively use the memory system"
```

### Search Daemon

Optional daemon mode keeps VelociRAG warm in memory for sub-second search responses.

```bash
memkoshi serve              # Start daemon
memkoshi serve-status       # Check health  
memkoshi serve-stop         # Stop daemon
```

### HMAC Signing

Every memory cryptographically signed with HMAC-SHA256. Tamper detection and integrity verification built-in.

## Python API

```python
from memkoshi import Memkoshi

# Initialize 
mk = Memkoshi("~/.memkoshi", extractor="hybrid")
mk.init()

# Core operations
mk.commit("Important decision text")        # Extract & stage
mk.list_staged()                           # Review pending
mk.approve(memory_id)                      # Move to permanent
mk.reject(memory_id, reason="...")         # Reject staged memory
mk.approve_all()                           # Approve all pending
mk.recall("search query", limit=5)        # Four-layer search
mk.ingest("/path/to/doc.md")              # Bulk import a document
mk.boot_tiered(tier=0)                     # Tiered boot context
mk.decay_and_boost()                       # Refresh memory importance

# Context management  
mk.context.set_handoff(task="...", progress="...")
mk.context.get_boot(token_budget=4096)

# Session lifecycle
with mk.session("task description") as s:
    s.add_message("user", "message")
    # Auto-extract on exit

# v0.4: Pattern detection & evolution
mk.patterns.detect()                       # Find behavioral patterns
mk.patterns.insights()                     # Human recommendations
mk.evolve.score(session_data)              # Score session performance
mk.evolve.hints()                          # Improvement suggestions
mk.evolve.status()                         # Performance dashboard
```

## MCP Tools

15 tools available to any MCP-compatible agent:

| Tool | Description |
|------|-------------|
| `memory_commit` | Extract and stage memories from text |
| `memory_recall` | Four-layer search across all memories |
| `memory_staged` | List memories pending review |
| `memory_approve` | Approve staged memory |
| `memory_reject` | Reject staged memory |
| `memory_boot` | System status and statistics |
| `memory_stats` | Storage statistics |
| `memory_handoff_get` | Current handoff state |
| `memory_handoff_set` | Set handoff for next session |
| `memory_context_boot` | Token-budgeted boot context |
| **NEW:** `memory_patterns` | Detected behavioral patterns |
| **NEW:** `memory_insights` | Pattern-based recommendations |
| **NEW:** `memory_evolve_score` | Score a session |
| **NEW:** `memory_evolve_hints` | Improvement suggestions |
| **NEW:** `memory_evolve_status` | Performance dashboard |

## CLI Commands

```bash
memkoshi commit "text"           # Extract memories
memkoshi review                  # Interactive review
memkoshi recall "query"          # Search memories
memkoshi boot                    # System status
memkoshi stats                   # Storage statistics

# Context management
memkoshi handoff set "task"      # Set handoff state
memkoshi handoff show            # Show current handoff
memkoshi context boot            # Boot context

# Search daemon
memkoshi serve                   # Start daemon
memkoshi serve-status            # Check health
memkoshi serve-stop              # Stop daemon

# v0.4: Pattern detection & evolution
memkoshi patterns detect         # Find patterns
memkoshi patterns insights       # Get recommendations
memkoshi evolve score "session"  # Score session
memkoshi evolve hints            # Get improvement hints
memkoshi evolve status           # Performance dashboard
```

## vs. The Competition

| Feature | Memkoshi | Mem0 | Zep | Letta |
|---------|----------|------|-----|-------|
| **Staging workflow** | ✅ | ❌ | ❌ | ❌ |
| **Local-first** | ✅ | ❌ | ❌ | ✅ |
| **Multi-tier extraction** | ✅ | ❌ | ❌ | ❌ |
| **No API keys required** | ✅ | ❌ | ❌ | ✅ |
| **Four-layer search** | ✅ | ❌ | ❌ | ❌ |
| **Pattern detection** | ✅ | ❌ | ❌ | ❌ |
| **Evolution scoring** | ✅ | ❌ | ❌ | ❌ |
| **Session lifecycle** | ✅ | ❌ | ❌ | ❌ |
| **MCP integration** | ✅ | ❌ | ❌ | ❌ |
| **Cryptographic signing** | ✅ | ❌ | ❌ | ❌ |

**Memkoshi**: Staging gates + Local-first + Pattern intelligence  
**Mem0**: Cloud LLM extraction → direct storage  
**Zep**: Enterprise cloud only, $80-150/month (open-source version discontinued)  
**Letta**: Full agent framework (not modular)

We're the only one with human-in-the-loop approval, local intelligence, and cross-session learning.

## Installation

```bash
# Install from GitHub (PyPI coming soon)
pip install git+https://github.com/HaseebKhalid1507/memkoshi.git

# Quick start
memkoshi init
echo "Important information here" | memkoshi commit
memkoshi review
memkoshi recall "information"

# With pattern detection & evolution
memkoshi patterns detect
memkoshi evolve status
```

## Configuration

```python
# Storage location
mk = Memkoshi("~/my-memories")

# Extraction quality
mk = Memkoshi("~/.memkoshi", extractor="pi")        # OAuth LLM
mk = Memkoshi("~/.memkoshi", extractor="api")       # API keys

# With auto-extraction
mk = Memkoshi("~/.memkoshi", enable_auto_extract=True)

# Environment variables
export MEMKOSHI_STORAGE=~/my-memories
export ANTHROPIC_API_KEY=sk-...  # for api extractor
export OPENAI_API_KEY=sk-...     # for api extractor
```

## Development

316 tests. All must pass before submitting PRs.

```bash
git clone https://github.com/HaseebKhalid1507/memkoshi
cd memkoshi
pip install -e ".[dev]"
pytest tests/  # 316 passed, 2 skipped
```

## License

MIT. Because vendor lock-in is for losers.

---

**Built by agents, for agents.** Memory is the foundation of intelligence. Evolution is the foundation of improvement. 

Memkoshi gives your AI the one thing it's missing: the ability to remember, learn, and get better over time.