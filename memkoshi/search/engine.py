"""Search engine for memkoshi — full 4-layer VelociRAG integration."""

import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any

from ..core.memory import Memory, MemoryCategory
from ..storage.sqlite import SQLiteBackend

# Try to import VelociRAG components
try:
    from velocirag.store import VectorStore
    from velocirag.searcher import Searcher
    from velocirag.embedder import Embedder
    from velocirag.graph import GraphStore, Node, Edge, NodeType, RelationType
    from velocirag.metadata import MetadataStore
    from velocirag.unified import UnifiedSearch
    HAS_VELOCIRAG = True
except ImportError:
    HAS_VELOCIRAG = False


logger = logging.getLogger(__name__)


class SimpleSearch:
    """Simple SQL LIKE search fallback when VelociRAG is not available."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._storage = None

    def initialize(self):
        self._storage = SQLiteBackend(self.db_path)
        self._storage.initialize()

    def index_memory(self, memory: Memory):
        pass  # Memories already in SQLite

    def remove_memory(self, memory_id: str):
        pass

    def search(self, query: str, limit: int = 5, category: str = None,
               recency_bias: bool = True) -> List[Dict[str, Any]]:
        if not self._storage:
            raise RuntimeError("SimpleSearch not initialized")
        memories = self._storage.search_memories(query, limit=limit * 2)
        if category:
            memories = [m for m in memories if m.category.value.lower() == category.lower()]
        results = []
        for memory in memories[:limit]:
            results.append({
                "id": memory.id,
                "score": 1.0,
                "title": memory.title,
                "category": memory.category,
                "abstract": memory.abstract,
            })
        return results

    def reindex_all(self, storage: SQLiteBackend) -> int:
        return len(storage.list_memories(limit=10000))


class MemkoshiSearch:
    """Full 4-layer search: vector + keyword + graph + metadata via VelociRAG."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._index_path = os.path.join(db_path, "search")
        self._store = None
        self._embedder = None
        self._searcher = None
        self._graph = None
        self._metadata = None
        self._unified = None
        self._fallback = None
        self._use_fallback = not HAS_VELOCIRAG

    def initialize(self):
        if self._use_fallback:
            logger.info("VelociRAG not available. Using SimpleSearch fallback.")
            self._fallback = SimpleSearch(self.db_path)
            self._fallback.initialize()
            return

        os.makedirs(self._index_path, exist_ok=True)

        # Layer 1: Vector store (FAISS + SQLite)
        self._store = VectorStore(self._index_path)
        self._embedder = Embedder()

        # Layer 2: Keyword search (BM25 via SQLite FTS5) — built into VectorStore
        # Layer 3: Knowledge graph
        graph_path = os.path.join(self._index_path, "graph.db")
        self._graph = GraphStore(graph_path)

        # Layer 4: Metadata store
        metadata_path = os.path.join(self._index_path, "metadata.db")
        self._metadata = MetadataStore(metadata_path)
        self._metadata.initialize()

        # Searcher (vector + keyword fusion)
        self._searcher = Searcher(self._store, self._embedder)

        # Unified search (all 4 layers + RRF fusion)
        self._unified = UnifiedSearch(
            self._searcher,
            graph_store=self._graph,
            metadata_store=self._metadata,
        )

    def index_memory(self, memory: Memory):
        """Index a memory across all 4 layers."""
        if self._use_fallback:
            return

        text = f"{memory.title}\n\n{memory.content}"
        embedding = self._embedder.embed(text)

        metadata = {
            "title": memory.title,
            "category": memory.category.value,
            "topic": memory.topic,
            "abstract": memory.abstract,
            "tags": memory.tags,
            "created": memory.created.isoformat() if memory.created else None,
            "confidence": memory.confidence.value,
        }

        # Layer 1+2: Vector + keyword (VectorStore handles both)
        self._store.add(memory.id, text, metadata, embedding)

        # Layer 3: Graph — add memory as node + edges for topic/category/tags
        import hashlib
        mem_node = Node(
            id=memory.id,
            title=memory.title,
            type=NodeType.NOTE,
            metadata={"category": memory.category.value, "topic": memory.topic}
        )
        self._graph.add_node(mem_node)

        # Add topic node + edge
        topic_node = Node(id=f"topic:{memory.topic}", title=memory.topic, type=NodeType.TOPIC)
        self._graph.add_node(topic_node)
        edge_id = hashlib.md5(f"{memory.id}:topic:{memory.topic}".encode()).hexdigest()[:12]
        self._graph.add_edge(Edge(
            id=edge_id, source_id=memory.id, target_id=f"topic:{memory.topic}",
            type=RelationType.DISCUSSES, weight=1.0, confidence=1.0
        ))

        # Add category node + edge
        cat_node = Node(id=f"cat:{memory.category.value}", title=memory.category.value, type=NodeType.TAG)
        self._graph.add_node(cat_node)
        edge_id = hashlib.md5(f"{memory.id}:cat:{memory.category.value}".encode()).hexdigest()[:12]
        self._graph.add_edge(Edge(
            id=edge_id, source_id=memory.id, target_id=f"cat:{memory.category.value}",
            type=RelationType.TAGGED_AS, weight=1.0, confidence=1.0
        ))

        # Add tag nodes + edges
        for tag in memory.tags:
            tag_node = Node(id=f"tag:{tag}", title=tag, type=NodeType.TAG)
            self._graph.add_node(tag_node)
            edge_id = hashlib.md5(f"{memory.id}:tag:{tag}".encode()).hexdigest()[:12]
            self._graph.add_edge(Edge(
                id=edge_id, source_id=memory.id, target_id=f"tag:{tag}",
                type=RelationType.TAGGED_AS, weight=0.8, confidence=1.0
            ))

        # Layer 4: Metadata
        doc_id = self._metadata.upsert_document(
            filename=memory.id,
            title=memory.title,
            metadata={
                "category": memory.category.value,
                "topic": memory.topic,
                "confidence": memory.confidence.value,
                "created": memory.created.isoformat() if memory.created else None,
                "source": "memkoshi",
            }
        )
        if memory.tags:
            self._metadata.add_tags(doc_id, memory.tags)

    def remove_memory(self, memory_id: str):
        """Remove memory from all layers."""
        if self._use_fallback:
            return
        try:
            self._store.remove(memory_id)
        except Exception:
            pass
        try:
            self._metadata.remove_document(memory_id)
        except Exception:
            pass

    def search(self, query: str, limit: int = 5, category: str = None,
               recency_bias: bool = True) -> List[Dict[str, Any]]:
        """4-layer fusion search: vector + keyword + graph + metadata → RRF → results."""
        if self._use_fallback:
            return self._fallback.search(query, limit, category, recency_bias)

        # Build metadata filters
        filters = {}
        if category:
            filters["category"] = category

        # Run unified 4-layer search
        response = self._unified.search(
            query=query,
            limit=limit * 2,  # Get extra for post-filtering
            threshold=0.15,
            enrich_graph=True,
            filters=filters,
        )

        results = response.get("results", [])
        now = datetime.now(timezone.utc)
        final_results = []

        for result in results:
            doc_id = result.get("doc_id", result.get("filename", ""))
            base_score = result.get("similarity", result.get("score", 0.0))
            meta = result.get("metadata", {})

            # Apply recency bias
            score = base_score
            if recency_bias and meta.get("created"):
                try:
                    created = datetime.fromisoformat(meta["created"])
                    days_old = (now - created).days
                    score = base_score * (1.0 + 1.0 / (1.0 + days_old * 0.1))
                except Exception:
                    pass

            final_results.append({
                "id": doc_id,
                "score": score,
                "title": meta.get("title", ""),
                "category": meta.get("category", ""),
                "abstract": meta.get("abstract", ""),
                "source_layers": meta.get("source_layers", ""),
                "rrf_score": meta.get("rrf_score", 0),
                "graph_connections": meta.get("graph_connections", []),
            })

            if len(final_results) >= limit:
                break

        return final_results

    def reindex_all(self, storage: SQLiteBackend) -> int:
        """Rebuild all 4 layers from permanent memories."""
        if self._use_fallback:
            return self._fallback.reindex_all(storage)

        # Clear vector store
        if hasattr(self._store, 'clear'):
            self._store.clear()

        memories = storage.list_memories(limit=10000)
        count = 0
        for memory in memories:
            try:
                self.index_memory(memory)
                count += 1
            except Exception as e:
                logger.error(f"Failed to index memory {memory.id}: {e}")

        logger.info(f"Reindexed {count} memories across 4 layers")
        return count
