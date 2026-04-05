# Memkoshi

![Tests](https://img.shields.io/badge/tests-316_passing-green) ![Version](https://img.shields.io/badge/version-0.4.0-blue) ![Python](https://img.shields.io/badge/python-3.8+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

**Your AI agent forgets everything when the session ends. Memkoshi fixes that.**

Memory system for AI agents. Two paths: **write** (learn from conversations via [Stelline](https://github.com/HaseebKhalid1507/Stelline)) and **read** (search what you know via [VelociRAG](https://github.com/HaseebKhalid1507/VelociRAG)). Staging gates, pattern detection, evolution scoring. Local-first, no cloud required.

## Quick Start

```bash
pip install git+https://github.com/HaseebKhalid1507/memkoshi.git
```

```python
from memkoshi import Memkoshi

mk = Memkoshi("./memory")
mk.init()

# Write: commit a memory
mk.commit("We chose PostgreSQL over MySQL — faster for our auth workload")

# Review what was extracted (staging gate)
staged = mk.list_staged()
mk.approve(staged[0]['id'])  # or mk.approve_all()

# Read: search your memories
results = mk.recall("database decision", limit=5)
```

## Session Intelligence

Install with Stelline to learn from conversations automatically:

```bash
pip install memkoshi[stelline]
```

```python
mk = Memkoshi("./memory")
mk.init()

# Learn from a session transcript
mk.stelline.harvest("path/to/session.jsonl")

# Memories are staged → approve → searchable
mk.approve_all()
mk.recall("what happened yesterday")
```

Stelline reads session transcripts and crafts authentic memories — not data extraction, but memory making. Importance scoring (0.0–1.0), quality gates, context-aware dedup. [Read more →](https://github.com/HaseebKhalid1507/Stelline)

## Architecture

```
Write Path (Stelline)                          Read Path (VelociRAG)
                                              
Session transcript                            "what do I know about X?"
       ↓                                              ↓
   Stelline                                    Four-layer search
  (crafts memories)                         (vector + keyword + graph + metadata)
       ↓                                              ↓
   Staging gate                                Ranked results
  (review before permanent)                            ↓
       ↓                                        Your agent responds
   Permanent store ←─────────────────────→    with real context
       ↓
   Pattern detection
   Evolution scoring
```

## Core Features

### Staging Workflow

Other systems auto-store everything the LLM extracts — including hallucinations. Memkoshi stages first, you review, then it's permanent.

```python
mk.commit("Meeting notes: John prefers Docker, rejected Kubernetes")

staged = mk.list_staged()
for memory in staged:
    print(f"{memory['title']}: {memory['content']}")

mk.approve(memory['id'])  # or mk.reject(memory['id'], reason="...")
```

### Four-Layer Search

Powered by [VelociRAG](https://github.com/HaseebKhalid1507/VelociRAG). Not just vector similarity.

1. **Vector** — FAISS embeddings (all-MiniLM-L6-v2)
2. **Keyword** — BM25 via SQLite FTS5
3. **Graph** — entity relationships, temporal connections
4. **Metadata** — categories, confidence, dates

Results fused with reciprocal rank fusion and cross-encoder reranking.

```python
results = mk.recall("database decision", limit=5)
for r in results:
    print(f"[{r['score']:.2f}] {r['title']}")
```

### Cross-Agent Memory (MCP)

One memory store, every AI tool you use. 15 MCP tools available to any compatible agent.

```json
{
  "mcpServers": {
    "memkoshi": {
      "command": "memkoshi",
      "args": ["mcp-serve"]
    }
  }
}
```

### Context & Handoff

State transfer between sessions. Boot context with token budgets.

```python
mk.context.set_handoff(
    task="Building auth API",
    progress="endpoints done",
    next_steps=["Add tests", "Deploy staging"]
)

boot = mk.context.get_boot(token_budget=4096)
```

### Session Lifecycle

```python
with mk.session("debugging login issue") as s:
    s.add_message("user", "Login timeout reproduced")
    s.add_message("assistant", "Redis TTL was set to 0, fixed it")
    # Auto-extracts memories on exit
```

### Pattern Detection

Learns from your behavior. Zero ML dependencies.

```python
patterns = mk.patterns.detect()
insights = mk.patterns.insights()
# "You search for auth issues most on Mondays"
# "Consider adding content about Redis TTL"
```

### Evolution Scoring

Track if you're getting better.

```python
score = mk.evolve.score(session_data)
hints = mk.evolve.hints()
# "High-scoring sessions actively use the memory system"
```

## Extraction Tiers

Choose your quality/cost tradeoff:

| Tier | Method | Cost | Quality |
|------|--------|------|---------|
| **hybrid** (default) | Local regex | Free | Good |
| **pi** | OAuth LLM via pi | Free (subscription) | Better |
| **api** | Direct Anthropic/OpenAI | Pay per call | Best |
| **stelline** | Session intelligence | Pay per call | Best + context-aware |

```python
mk = Memkoshi("./memory", extractor="hybrid")  # default, free
mk = Memkoshi("./memory", extractor="api", api_key="sk-...")  # direct API
```

## Python API

```python
from memkoshi import Memkoshi

mk = Memkoshi("./memory")
mk.init()

# Core
mk.commit("text")                  # Extract & stage
mk.list_staged()                   # Review pending
mk.approve(id)                     # Approve
mk.reject(id, reason="...")        # Reject
mk.approve_all()                   # Approve all
mk.recall("query", limit=5)        # Search
mk.ingest("doc.md")                # Bulk import

# Context
mk.context.set_handoff(...)        # Set work state
mk.context.get_boot(token_budget=4096)

# Sessions
with mk.session("task") as s:
    s.add_message("user", "msg")

# Patterns & evolution
mk.patterns.detect()               # Find patterns
mk.patterns.insights()             # Recommendations
mk.evolve.score(data)              # Score session
mk.evolve.hints()                  # Improvement hints

# Stelline (pip install memkoshi[stelline])
mk.stelline.harvest("session.jsonl")
mk.stelline.scan()
mk.stelline.status()
```

## CLI

```bash
memkoshi commit "text"              # Extract memories
memkoshi review                     # Interactive review
memkoshi recall "query"             # Search
memkoshi stats                      # Storage stats
memkoshi serve                      # Start search daemon
memkoshi patterns detect            # Find patterns
memkoshi evolve status              # Performance dashboard
```

## Related Projects

- **[VelociRAG](https://github.com/HaseebKhalid1507/VelociRAG)** — 4-layer search engine. Powers the read path.
- **[Stelline](https://github.com/HaseebKhalid1507/Stelline)** — Session intelligence. Powers the write path. `pip install memkoshi[stelline]`
- **[Glyph](https://github.com/HaseebKhalid1507/Glyph)** — MCP security scanner and runtime protection.

## Development

```bash
git clone https://github.com/HaseebKhalid1507/memkoshi
cd memkoshi
pip install -e ".[dev]"
pytest tests/  # 316 passed
```

## License

MIT
