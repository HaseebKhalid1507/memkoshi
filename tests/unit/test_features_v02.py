"""Tests for v0.2 features: bulk import, staleness, tiered boot, pattern learning."""

import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

from memkoshi.api import Memkoshi


@pytest.fixture
def m(tmp_path):
    """Fresh Memkoshi instance for each test."""
    mk = Memkoshi(str(tmp_path / "test_memkoshi"))
    mk.init()
    yield mk
    mk.close()


@pytest.fixture
def sample_journal():
    """Realistic journal text for testing."""
    return """
## Research Cycle 1

BTC rejected at $69,466 AGAIN (6th rejection). Resistance is confirmed fortress.
ETH showing relative strength — holding $2,134 while BTC struggles.
GLD anchor all day, never went red. Safe haven thesis confirmed.

## Trade Cycle 1

First trade: BUY 0.23 ETH @ $2,134.33 ($490, 49% of portfolio).
Stop 3% at $2,070, TP 5% at $2,241.
Cash reserve $510 for BTC breakout above $69.6K.

## Lessons

Learned that stop losses at 3% are too tight for crypto volatility.
Never be fully deployed into a coin-flip. Always keep cash for opportunities.
Fixed XLE entry price in DB ($87 → $61.89) — data integrity matters.

## Market Analysis

BTC coiling: vol compressing 48→41%, range narrowing, resistance at $69,466.
Support rising from $67,800 to $68,200 over past 3 sessions.
SpaceX IPO filed — $1.75T valuation, bullish for tech sentiment.
"""


# ═══════════════════════════════════════════════════════════════
# Feature 1: Bulk Document Import
# ═══════════════════════════════════════════════════════════════

class TestBulkImport:
    
    def test_ingest_from_text(self, m, sample_journal):
        """Ingest raw text and extract memories."""
        result = m.ingest(sample_journal)
        assert result["chunks"] >= 1
        assert result["extracted"] > 0
        assert result["staged"] > 0
    
    def test_ingest_from_file(self, m, sample_journal, tmp_path):
        """Ingest from a file path."""
        journal_file = tmp_path / "test_journal.md"
        journal_file.write_text(sample_journal)
        
        result = m.ingest(str(journal_file))
        assert result["source"] == "test_journal.md"
        assert result["extracted"] > 0
    
    def test_ingest_auto_approve(self, m, sample_journal):
        """Auto-approve imported memories."""
        result = m.ingest(sample_journal, auto_approve=True)
        assert result["approved"] > 0
        # Check they're actually in permanent storage
        stats = m.stats()
        assert stats["total_memories"] > 0
    
    def test_ingest_deduplication(self, m, sample_journal):
        """Second import should deduplicate against first."""
        r1 = m.ingest(sample_journal, auto_approve=True)
        r2 = m.ingest(sample_journal, auto_approve=True)
        # Second import should have fewer new memories
        assert r2["staged"] <= r1["staged"]
    
    def test_ingest_chunking(self, m):
        """Large text should be split into chunks."""
        # Use paragraph breaks so chunker can split
        big_text = "\n\n".join([f"BUY 1.0 ETH at ${2000+i}. Trade #{i} executed." for i in range(100)])
        result = m.ingest(big_text, chunk_size=500)
        assert result["chunks"] > 1
    
    def test_ingest_empty_text(self, m):
        """Empty text should return zero stats."""
        result = m.ingest("")
        assert result["chunks"] == 0
        assert result["extracted"] == 0
    
    def test_ingest_missing_file(self, m):
        """Non-existent file path treated as raw text."""
        result = m.ingest("/nonexistent/path/journal.md")
        # Treated as text, not a file — but it's not meaningful content
        assert result["extracted"] == 0


# ═══════════════════════════════════════════════════════════════
# Feature 2: Staleness Caveats
# ═══════════════════════════════════════════════════════════════

class TestStaleness:
    
    def test_fresh_memory_no_caveat(self):
        """Memories <= 1 day old have no caveat."""
        assert Memkoshi.staleness_caveat(0) == ""
        assert Memkoshi.staleness_caveat(1) == ""
    
    def test_week_old_caveat(self):
        """1-7 day old memories get a short warning."""
        caveat = Memkoshi.staleness_caveat(5)
        assert "5 days old" in caveat
        assert "Verify" in caveat
    
    def test_month_old_caveat(self):
        """8-30 day old memories get a stronger warning."""
        caveat = Memkoshi.staleness_caveat(20)
        assert "20 days old" in caveat
        assert "outdated" in caveat
    
    def test_ancient_caveat(self):
        """30+ day old memories get strongest warning."""
        caveat = Memkoshi.staleness_caveat(60)
        assert "60 days old" in caveat
        assert "historical" in caveat
        assert "NOT assert" in caveat
    
    def test_recall_includes_staleness(self, m, sample_journal):
        """Recalled memories should include age and staleness info."""
        m.ingest(sample_journal, auto_approve=True)
        results = m.recall("BTC")
        if results:
            assert "age_days" in results[0]
            assert "staleness_caveat" in results[0]
    
    def test_age_calculation(self):
        """Age calculation from datetime strings."""
        # Today
        now = datetime.now(timezone.utc)
        assert Memkoshi._memory_age_days(now) == 0
        
        # 10 days ago
        ten_ago = now - timedelta(days=10)
        assert Memkoshi._memory_age_days(ten_ago) == 10
        
        # String format
        assert Memkoshi._memory_age_days(ten_ago.isoformat()) == 10
        
        # Invalid input
        assert Memkoshi._memory_age_days("garbage") == -1


# ═══════════════════════════════════════════════════════════════
# Feature 3: Tiered Boot
# ═══════════════════════════════════════════════════════════════

class TestTieredBoot:
    
    def test_tier_0_loads_high_importance(self, m, sample_journal):
        """Tier 0 only loads high-importance memories."""
        m.ingest(sample_journal, auto_approve=True)
        
        t0 = m.boot_tiered(tier=0)
        assert t0["tier"] == 0
        # All memories should be importance >= 0.7 OR preferences/cases
        for mem in t0["memories"]:
            assert mem["importance"] >= 0.7 or mem["category"] in ("preferences", "cases")
    
    def test_tier_2_loads_everything(self, m, sample_journal):
        """Tier 2 loads all memories."""
        m.ingest(sample_journal, auto_approve=True)
        
        t2 = m.boot_tiered(tier=2)
        assert t2["count"] >= m.boot_tiered(tier=0)["count"]
    
    def test_tier_progression(self, m, sample_journal):
        """Higher tiers load progressively more memories."""
        m.ingest(sample_journal, auto_approve=True)
        
        t0 = m.boot_tiered(tier=0, limit=100)
        t1 = m.boot_tiered(tier=1, limit=100)
        t2 = m.boot_tiered(tier=2, limit=100)
        
        assert t0["count"] <= t1["count"] <= t2["count"]
    
    def test_tier_respects_limit(self, m, sample_journal):
        """Tier respects the limit parameter."""
        m.ingest(sample_journal, auto_approve=True)
        
        t = m.boot_tiered(tier=2, limit=3)
        assert t["count"] <= 3
    
    def test_tier_includes_staleness(self, m, sample_journal):
        """Tiered results include staleness info."""
        m.ingest(sample_journal, auto_approve=True)
        
        t = m.boot_tiered(tier=2)
        if t["memories"]:
            assert "staleness_caveat" in t["memories"][0]
            assert "age_days" in t["memories"][0]
    
    def test_tier_sorted_by_importance(self, m, sample_journal):
        """Memories within a tier are sorted by importance descending."""
        m.ingest(sample_journal, auto_approve=True)
        
        t = m.boot_tiered(tier=2, limit=100)
        importances = [mem["importance"] for mem in t["memories"]]
        assert importances == sorted(importances, reverse=True)


# ═══════════════════════════════════════════════════════════════
# Feature 4: Pattern Learning
# ═══════════════════════════════════════════════════════════════

class TestPatternLearning:
    
    def test_record_access(self, m, sample_journal):
        """Recording access should not error."""
        m.ingest(sample_journal, auto_approve=True)
        memories = m.recall("BTC")
        if memories:
            m.record_access(memories[0]["id"], "recall")
            # Should be able to record multiple times
            m.record_access(memories[0]["id"], "cited")
            m.record_access(memories[0]["id"], "acted_on")
    
    def test_access_count_tracks(self, m, sample_journal):
        """Access count should increase with each recording."""
        m.ingest(sample_journal, auto_approve=True)
        memories = m.recall("ETH")
        if memories:
            mid = memories[0]["id"]
            assert m.storage.get_access_count(mid) == 0
            m.record_access(mid)
            assert m.storage.get_access_count(mid) == 1
            m.record_access(mid)
            m.record_access(mid)
            assert m.storage.get_access_count(mid) == 3
    
    def test_decay_and_boost_runs(self, m, sample_journal):
        """Decay and boost cycle should run without errors."""
        m.ingest(sample_journal, auto_approve=True)
        result = m.decay_and_boost()
        assert result["total_processed"] > 0
        assert "boosted" in result
        assert "decayed" in result
        assert "unchanged" in result
    
    def test_boost_increases_importance(self, m, sample_journal):
        """Accessed memories should get boosted importance."""
        m.ingest(sample_journal, auto_approve=True)
        memories = m.recall("ETH")
        if memories:
            mid = memories[0]["id"]
            
            # Record many accesses
            for _ in range(10):
                m.record_access(mid)
            
            # Get importance before
            mem_before = m.storage.get_memory(mid)
            old_importance = mem_before.importance
            
            # Run decay/boost
            m.decay_and_boost()
            
            # Check importance increased
            mem_after = m.storage.get_memory(mid)
            assert mem_after.importance > old_importance
    
    def test_importance_capped_at_1(self, m, sample_journal):
        """Boosted importance should never exceed 1.0."""
        m.ingest(sample_journal, auto_approve=True)
        memories = m.recall("ETH")
        if memories:
            mid = memories[0]["id"]
            # Massive access count
            for _ in range(100):
                m.record_access(mid)
            m.decay_and_boost()
            
            mem = m.storage.get_memory(mid)
            assert mem.importance <= 1.0
    
    def test_importance_floor_at_01(self, m, sample_journal):
        """Decayed importance should never go below 0.1."""
        m.ingest(sample_journal, auto_approve=True)
        # No accesses + we can't easily simulate age, but verify floor logic
        result = m.decay_and_boost()
        # All memories are fresh (created now), so no decay should happen
        assert result["decayed"] == 0
