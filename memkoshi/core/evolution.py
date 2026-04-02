"""Evolution engine for session scoring and behavioral insights."""

import re
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EvolutionScore(BaseModel):
    """Session evolution score data structure."""
    score: float = Field(..., ge=1.0, le=10.0)
    task_completion_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    error_count: int = Field(default=0, ge=0)
    satisfaction_keywords: Dict[str, Any] = Field(default_factory=dict)
    duration_minutes: int = Field(default=60, ge=0)
    memories_committed: int = Field(default=0, ge=0)
    memories_recalled: int = Field(default=0, ge=0)
    insights: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EvolutionEngine:
    """Session scoring and behavioral improvement system."""
    
    def __init__(self, storage):
        """Initialize evolution engine.
        
        Args:
            storage: Storage backend instance
        """
        self.storage = storage
    
    def score(self, session_input: Union[Dict[str, Any], str], 
              session_id: Optional[str] = None) -> Dict[str, Any]:
        """Score a session. Accepts structured dict or text fallback.
        
        Args:
            session_input: Structured session data dict or text string
            session_id: Optional session ID for storage
            
        Returns:
            Dictionary with score and analysis data
        """
        try:
            if isinstance(session_input, dict):
                # Structured input (preferred)
                score = self.score_structured(session_input)
                result = session_input.copy()
                result['score'] = score
                # Compute and store task_completion_rate
                tasks_completed = session_input.get('tasks_completed', 0)
                tasks_attempted = max(1, session_input.get('tasks_attempted', 1))
                result['task_completion_rate'] = tasks_completed / tasks_attempted
            else:
                # Text fallback with heuristics
                result = self.score_text_fallback(str(session_input))
            
            # Store in database if session_id provided
            if session_id:
                self._store_evolution_session(session_id, result)
            
            return result
            
        except Exception as e:
            # Return safe fallback if scoring fails
            logger.warning(f"Session scoring failed: {e}")
            return {
                'score': 5.0,
                'error': 'Scoring temporarily unavailable',
                'session_data': session_input if isinstance(session_input, dict) else {}
            }
    
    def score_structured(self, session_data: Dict[str, Any]) -> float:
        """Score session using STRUCTURED input (not magic text parsing).
        
        Args:
            session_data: Structured session metrics dict
            
        Returns:
            Score from 1.0 to 10.0
        """
        # Extract metrics from structured data
        tasks_completed = session_data.get('tasks_completed', 0)
        tasks_attempted = max(1, session_data.get('tasks_attempted', 1))
        errors = session_data.get('errors', 0)
        duration_minutes = session_data.get('duration_minutes', 60)
        memories_committed = session_data.get('memories_committed', 0)
        memories_recalled = session_data.get('memories_recalled', 0)
        
        # Concrete scoring formula (no magic)
        task_completion_rate = tasks_completed / tasks_attempted
        error_penalty = max(0.0, 1.0 - (errors * 0.1))  # -0.1 per error
        memory_usage_boost = min(0.2, (memories_committed + memories_recalled) * 0.02)  # +0.02 per memory
        
        # Weighted combination
        base_score = (
            0.5 * task_completion_rate +  # Primary metric
            0.3 * error_penalty +         # Quality penalty
            0.2 * memory_usage_boost      # Memory system usage
        )
        
        # Scale to 1-10 and apply duration bonus/penalty
        duration_factor = 1.0
        if duration_minutes < 30:
            duration_factor = 1.1  # Bonus for efficiency
        elif duration_minutes > 120:
            duration_factor = 0.9  # Penalty for long sessions
        
        final_score = base_score * duration_factor * 10
        return min(10.0, max(1.0, final_score))
    
    def score_text_fallback(self, session_text: str) -> Dict[str, Any]:
        """Fallback scoring using keyword heuristics (not magic).
        
        Args:
            session_text: Session text to analyze
            
        Returns:
            Dictionary with score and extracted metrics
        """
        if not session_text:
            return {'score': 5.0, 'tasks_completed': 0, 'errors': 0, 'satisfaction_keywords': []}
        
        text_lower = session_text.lower()
        
        # Task completion keywords (concrete regex)
        completed_patterns = [
            r'\b(completed?|finished|done|shipped|fixed|resolved|implemented)\b',
            r'\b(success|successful|working|works)\b',
            r'\b(commit|merge|deploy|release)\b'
        ]
        
        error_patterns = [
            r'\b(error|failed?|broken|crash|exception|bug)\b',
            r'\b(issue|problem|trouble|stuck)\b'
        ]
        
        satisfaction_positive = [
            r'\b(great|excellent|perfect|smooth|easy|good)\b',
            r'\b(good job|well done|nice)\b'
        ]
        
        satisfaction_negative = [
            r'\b(frustrated|frustrating|annoying|difficult|hard|confusing)\b',
            r'\b(waste|slow|tedious)\b'
        ]
        
        # Count matches
        completed_count = sum(len(re.findall(pattern, text_lower)) for pattern in completed_patterns)
        error_count = sum(len(re.findall(pattern, text_lower)) for pattern in error_patterns)
        pos_sentiment = sum(len(re.findall(pattern, text_lower)) for pattern in satisfaction_positive)
        neg_sentiment = sum(len(re.findall(pattern, text_lower)) for pattern in satisfaction_negative)
        
        # Structured data for scoring
        session_data = {
            'tasks_completed': completed_count,
            'tasks_attempted': max(1, completed_count + error_count),
            'errors': error_count,
            'duration_minutes': 60,  # Default assumption
            'memories_committed': 0,
            'memories_recalled': 0
        }
        
        score = self.score_structured(session_data)
        
        return {
            'score': score,
            'tasks_completed': completed_count,
            'errors': error_count,
            'satisfaction_keywords': {
                'positive': pos_sentiment,
                'negative': neg_sentiment
            },
            'session_data': session_data
        }
    
    def hints(self) -> List[str]:
        """Get behavioral improvement hints.
        
        Returns:
            List of actionable hint strings
        """
        try:
            insights = self.generate_insights()
            return insights
        except Exception as e:
            logger.warning(f"Hints generation failed: {e}")
            return ["Hints temporarily unavailable"]
    
    def status(self) -> Dict[str, Any]:
        """Get performance dashboard dict.
        
        Returns:
            Dictionary with performance metrics
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()
            
            # Recent session count
            cursor.execute("""
                SELECT COUNT(*) 
                FROM evolution_sessions 
                WHERE created_at >= datetime('now', '-30 days')
            """)
            recent_sessions = cursor.fetchone()[0] or 0
            
            # Average score
            cursor.execute("""
                SELECT AVG(score) 
                FROM evolution_sessions 
                WHERE created_at >= datetime('now', '-30 days')
            """)
            avg_score = cursor.fetchone()[0] or 0.0
            
            # Best session
            cursor.execute("""
                SELECT session_id, score 
                FROM evolution_sessions 
                ORDER BY score DESC 
                LIMIT 1
            """)
            best_session = cursor.fetchone()
            
            # Trend analysis (last 7 days vs previous 7 days)
            cursor.execute("""
                SELECT AVG(score) 
                FROM evolution_sessions 
                WHERE created_at >= datetime('now', '-7 days')
            """)
            recent_avg = cursor.fetchone()[0] or 0.0
            
            cursor.execute("""
                SELECT AVG(score) 
                FROM evolution_sessions 
                WHERE created_at BETWEEN datetime('now', '-14 days') AND datetime('now', '-7 days')
            """)
            previous_avg = cursor.fetchone()[0] or 0.0
            
            trend = "stable"
            if recent_avg > previous_avg + 0.5:
                trend = "improving"
            elif recent_avg < previous_avg - 0.5:
                trend = "declining"
            
            return {
                "recent_sessions_30d": recent_sessions,
                "average_score_30d": round(avg_score, 1),
                "best_session": {
                    "id": best_session[0] if best_session else None,
                    "score": round(best_session[1], 1) if best_session else 0.0
                },
                "trend_7d": trend,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
        except (sqlite3.Error, Exception) as e:
            logger.warning(f"Status retrieval failed: {e}")
            return {"error": "Status temporarily unavailable"}
    
    def generate_insights(self, lookback_days: int = 30) -> List[str]:
        """Generate hints from recent sessions using SQL analysis.
        
        Args:
            lookback_days: Number of days to look back for analysis
            
        Returns:
            List of insight strings
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()
            
            # Get recent high-scoring sessions
            cursor.execute("""
                SELECT score, task_completion_rate, error_count, memories_committed, memories_recalled
                FROM evolution_sessions 
                WHERE created_at >= datetime('now', ? || ' days')
                AND score >= 7.0
                ORDER BY score DESC
                LIMIT 10
            """, (f'-{lookback_days}',))
            
            high_performers = cursor.fetchall()
            
            # Get all recent sessions for comparison
            cursor.execute("""
                SELECT AVG(score), AVG(task_completion_rate), AVG(error_count)
                FROM evolution_sessions 
                WHERE created_at >= datetime('now', ? || ' days')
            """, (f'-{lookback_days}',))
            
            averages = cursor.fetchone()
            
            if not averages or not high_performers:
                return ["Need more session data to generate insights."]
            
            avg_score, avg_completion, avg_errors = averages
            if avg_score is None:
                return ["Insufficient data for analysis."]
            
            insights = []
            
            # Concrete pattern analysis
            if len(high_performers) >= 3:
                high_avg_completion = sum(row[1] or 0 for row in high_performers) / len(high_performers)
                high_avg_errors = sum(row[2] or 0 for row in high_performers) / len(high_performers)
                
                if avg_completion and high_avg_completion > (avg_completion + 0.2):
                    insights.append(f"High-scoring sessions have {high_avg_completion:.1%} task completion vs {avg_completion:.1%} average")
                
                if avg_errors and high_avg_errors < (avg_errors - 1):
                    insights.append(f"Best sessions average {high_avg_errors:.1f} errors vs {avg_errors:.1f} overall")
            
            # Memory usage patterns
            memory_users = [row for row in high_performers if (row[3] or 0) + (row[4] or 0) > 0]
            if len(memory_users) > len(high_performers) * 0.6:  # 60%+ use memory
                insights.append("High-scoring sessions actively use the memory system")
            
            if not insights:
                insights.append("Performance patterns still emerging - continue using the system")
            
            return insights[:3]  # Max 3 insights
            
        except (sqlite3.Error, Exception) as e:
            logger.warning(f"Pattern analysis failed: {e}")
            return ["Pattern analysis temporarily unavailable"]
    
    def _store_evolution_session(self, session_id: str, session_data: Dict[str, Any]) -> None:
        """Store evolution session data in database.
        
        Args:
            session_id: Session identifier
            session_data: Session metrics and analysis
        """
        try:
            self.storage._check_conn()
            cursor = self.storage.conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO evolution_sessions (
                    session_id, score, task_completion_rate, error_count,
                    satisfaction_keywords, duration_minutes, memories_committed,
                    memories_recalled, insights, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                session_data.get('score', 5.0),
                session_data.get('task_completion_rate', 0.0),
                session_data.get('errors', session_data.get('error_count', 0)),
                json.dumps(session_data.get('satisfaction_keywords', {})),
                session_data.get('duration_minutes', 60),
                session_data.get('memories_committed', 0),
                session_data.get('memories_recalled', 0),
                json.dumps(session_data.get('insights', [])),
                datetime.now(timezone.utc).isoformat()
            ))
            
            self.storage.conn.commit()
            
        except (sqlite3.Error, json.JSONEncodeError, Exception) as e:
            # Store failure should not crash evolution system
            logger.warning(f"Evolution session storage failed: {e}")