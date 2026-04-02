"""Pattern detection system using concrete SQL queries."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class Pattern(BaseModel):
    """Behavioral pattern data structure."""
    pattern_type: str = Field(..., min_length=1)  # frequency, temporal, gap, success
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    trigger_condition: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(..., ge=0.0, le=1.0)
    sample_size: int = Field(default=1, ge=1)
    last_triggered: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PatternDetector:
    """Concrete pattern detection using SQL analysis."""

    def __init__(self, storage):
        """Initialize pattern detector.

        Args:
            storage: Storage backend instance
        """
        self.storage = storage

    def detect(self) -> List[Pattern]:
        """Main pattern detection pipeline.

        Returns:
            List of detected patterns
        """
        patterns = []

        try:
            # Run all detection algorithms (safe - never crash)
            patterns.extend(self.detect_frequency_patterns())
            patterns.extend(self.detect_knowledge_gaps())
            patterns.extend(self.detect_temporal_patterns())

            # Store new patterns
            for pattern in patterns:
                self._store_pattern(pattern)

            # Cleanup old events to prevent unbounded growth
            self.cleanup_old_events()

        except Exception:
            # Pattern detection failure should never crash the system
            pass

        return patterns

    def detect_frequency_patterns(self) -> List[Pattern]:
        """Find memories accessed 3+ times. Pure SQL.

        Returns:
            List of frequency patterns
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()

            cursor.execute("""
                SELECT target_id, COUNT(*) as access_count
                FROM events
                WHERE event_type = 'search' AND target_id IS NOT NULL
                GROUP BY target_id
                HAVING COUNT(*) >= 3
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)

            patterns = []
            for row in cursor.fetchall():
                target_id, count = row
                patterns.append(Pattern(
                    pattern_type='frequency',
                    name=f'Frequent Access: {target_id}',
                    description=f'Memory accessed {count} times',
                    trigger_condition={'target_id': target_id, 'min_count': 3},
                    confidence=min(1.0, count / 10.0),
                    sample_size=count
                ))
            return patterns

        except (sqlite3.Error, Exception):
            return []  # Never crash on pattern detection failure

    def detect_knowledge_gaps(self) -> List[Pattern]:
        """Find search queries that return 0 results 3+ times.

        Returns:
            List of knowledge gap patterns
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()

            cursor.execute("""
                SELECT json_extract(metadata, '$.query') as query, COUNT(*) as search_count
                FROM events
                WHERE event_type = 'search_complete'
                AND json_extract(metadata, '$.results_count') = 0
                AND json_extract(metadata, '$.query') IS NOT NULL
                GROUP BY json_extract(metadata, '$.query')
                HAVING COUNT(*) >= 3
                ORDER BY COUNT(*) DESC
                LIMIT 5
            """)

            patterns = []
            for row in cursor.fetchall():
                query, count = row
                if query and query.strip():  # Skip null/empty queries
                    patterns.append(Pattern(
                        pattern_type='gap',
                        name=f'Knowledge Gap: {query}',
                        description=f'Query "{query}" failed {count} times',
                        trigger_condition={'query': query, 'zero_results': True},
                        confidence=min(1.0, count / 5.0),
                        sample_size=count
                    ))    
            return patterns
            
        except (sqlite3.Error, json.JSONDecodeError, Exception) as e:
            logger.warning(f"Knowledge gap detection failed: {e}")
            return []
    
    def detect_temporal_patterns(self) -> List[Pattern]:
        """Find day-of-week access patterns.

        Returns:
            List of temporal patterns
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()

            cursor.execute("""
                SELECT strftime('%w', timestamp) as day_of_week,
                       json_extract(metadata, '$.query') as query,
                       COUNT(*) as count
                FROM events
                WHERE event_type = 'search'
                AND json_extract(metadata, '$.query') IS NOT NULL
                GROUP BY strftime('%w', timestamp), json_extract(metadata, '$.query')
                HAVING COUNT(*) >= 2
                ORDER BY COUNT(*) DESC
                LIMIT 5
            """)

            day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            patterns = []

            for row in cursor.fetchall():
                day, query, count = row
                if day is not None and query and query.strip():
                    day_name = day_names[int(day)]
                    patterns.append(Pattern(
                        pattern_type='temporal',
                        name=f'{day_name} Pattern: {query}',
                        description=f'Query "{query}" searched on {day_name}s ({count} times)',
                        trigger_condition={'day_of_week': int(day), 'query': query},
                        confidence=min(1.0, count / 4.0),
                        sample_size=count
                    ))
            return patterns
            
        except (sqlite3.Error, json.JSONDecodeError, Exception) as e:
            logger.warning(f"Temporal pattern detection failed: {e}")
            return []
    
    def insights(self) -> List[str]:
        """Generate human-readable recommendations from patterns.

        Returns:
            List of insight strings
        """
        try:
            patterns = self.detect()
            insights = []

            # Analyze frequency patterns
            freq_patterns = [p for p in patterns if p.pattern_type == 'frequency']
            if freq_patterns:
                most_accessed = max(freq_patterns, key=lambda p: p.sample_size)
                insights.append(f"Most frequently accessed: {most_accessed.name} ({most_accessed.sample_size} times)")

            # Analyze knowledge gaps
            gap_patterns = [p for p in patterns if p.pattern_type == 'gap']
            if gap_patterns:
                insights.append(f"Found {len(gap_patterns)} recurring knowledge gaps - consider adding content for these topics")

            # Analyze temporal patterns
            temporal_patterns = [p for p in patterns if p.pattern_type == 'temporal']
            if temporal_patterns:
                insights.append(f"Detected {len(temporal_patterns)} time-based usage patterns")

            return insights[:5]  # Limit to top 5 insights

        except Exception as e:
            logger.warning(f"Pattern insights generation failed: {e}")
            return ["Pattern analysis temporarily unavailable"]

    def stats(self) -> Dict[str, Any]:
        """Get usage statistics.

        Returns:
            Dictionary with usage statistics
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()

            # Total events
            cursor.execute("SELECT COUNT(*) FROM events")
            total_events = cursor.fetchone()[0] or 0

            # Events by type
            cursor.execute("""
                SELECT event_type, COUNT(*)
                FROM events
                GROUP BY event_type
                ORDER BY COUNT(*) DESC
            """)
            events_by_type = dict(cursor.fetchall())

            # Recent activity (last 7 days)
            cursor.execute("""
                SELECT COUNT(*)
                FROM events
                WHERE timestamp >= datetime('now', '-7 days')
            """)
            recent_activity = cursor.fetchone()[0] or 0

            return {
                "total_events": total_events,
                "events_by_type": events_by_type,
                "recent_activity_7d": recent_activity,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

        except (sqlite3.Error, Exception) as e:
            logger.warning(f"Pattern statistics retrieval failed: {e}")
            return {"error": "Statistics temporarily unavailable"}

    def cleanup_old_events(self, max_events: int = 10000) -> int:
        """Remove old events to prevent unbounded growth.

        Args:
            max_events: Maximum number of events to keep

        Returns:
            Number of events deleted
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()

            # Count total events
            cursor.execute("SELECT COUNT(*) FROM events")
            total = cursor.fetchone()[0] or 0

            if total > max_events:
                # Delete oldest events beyond limit
                delete_count = total - max_events
                cursor.execute("""
                    DELETE FROM events
                    WHERE id IN (
                        SELECT id FROM events
                        ORDER BY timestamp ASC
                        LIMIT ?
                    )
                """, (delete_count,))

                self.storage.conn.commit()
                return delete_count

            return 0

        except (sqlite3.Error, Exception) as e:
            logger.warning(f"Event cleanup failed: {e}")
            return 0  # Never crash on cleanup

    def _store_pattern(self, pattern: Pattern) -> None:
        """Store a pattern in the database.

        Args:
            pattern: Pattern to store
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO patterns (
                    pattern_type, name, description, trigger_condition,
                    confidence, sample_size, last_triggered, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pattern.pattern_type,
                pattern.name,
                pattern.description,
                json.dumps(pattern.trigger_condition),
                pattern.confidence,
                pattern.sample_size,
                pattern.last_triggered,
                pattern.created_at
            ))

            self.storage.conn.commit()

        except (sqlite3.Error, json.JSONEncodeError, Exception) as e:
            # Store failure should not crash pattern detection
            logger.warning(f"Pattern storage failed: {e}")