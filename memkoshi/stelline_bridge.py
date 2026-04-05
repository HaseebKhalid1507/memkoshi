"""Stelline integration bridge — session intelligence write path.

Provides mk.stelline.harvest(), mk.stelline.scan(), mk.stelline.status()
when the stelline package is installed (pip install memkoshi[stelline]).
"""

from pathlib import Path
from typing import Dict, Any, Optional


class StellineBridge:
    """Lazy bridge to Stelline session intelligence.
    
    Wraps Stelline's pipeline to work directly with a Memkoshi instance,
    using its storage and search as the memory backend.
    """
    
    def __init__(self, memkoshi_instance):
        self._mk = memkoshi_instance
        self._pipeline = None
        self._tracker = None
        self._config = None
    
    def _ensure_stelline(self):
        """Lazy import + initialize Stelline components."""
        if self._pipeline is not None:
            return
        
        try:
            from stelline.config import StellineConfig
            from stelline.context import ContextLoader
            from stelline.pipeline import StellinePipeline
            from stelline.tracker import SessionTracker
        except ImportError:
            raise ImportError(
                "Stelline is not installed. Install it with: pip install memkoshi[stelline]"
            )
        
        self._config = StellineConfig()
        self._config.memkoshi_storage = str(self._mk.storage_path)
        
        db_path = str(self._mk.storage_path / "stelline_tracker.db")
        self._config.db_path = db_path
        
        self._tracker = SessionTracker(db_path)
        context_loader = ContextLoader(self._config)
        self._pipeline = StellinePipeline(self._config, self._tracker, context_loader)
    
    def harvest(self, session_path: str, dry_run: bool = False) -> Dict[str, Any]:
        """Process a single session file and stage memories.
        
        Args:
            session_path: Path to a .jsonl session file.
            dry_run: If True, parse and analyze but don't call LLM.
            
        Returns:
            Dict with status, memories_extracted, duration, etc.
        """
        self._ensure_stelline()
        from stelline.discovery import SessionFile
        
        path = Path(session_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Session file not found: {path}")
        
        session = SessionFile.from_path(path, "memkoshi")
        return self._pipeline.process_session(session, dry_run=dry_run)
    
    def scan(self, source: Optional[str] = None) -> Dict[str, Dict[str, int]]:
        """Scan for unprocessed sessions.
        
        Returns:
            Dict of source -> {total, processed, unprocessed} counts.
        """
        self._ensure_stelline()
        from stelline.discovery import SessionDiscovery
        
        discovery = SessionDiscovery(self._config, self._tracker)
        return discovery.get_source_stats()
    
    def status(self) -> Dict[str, Any]:
        """Get Stelline harvest status and recent activity.
        
        Returns:
            Dict with overall stats and per-source breakdown.
        """
        self._ensure_stelline()
        return self._tracker.get_stats()
    
    def history(self, limit: int = 10):
        """Get recent harvest runs.
        
        Args:
            limit: Number of recent runs to return.
            
        Returns:
            List of harvest run records.
        """
        self._ensure_stelline()
        return self._tracker.get_recent_runs(limit)

    def add_context(self, name: str, path: str, instruction: str) -> None:
        """Register a context file for Stelline to maintain during harvest.
        
        After extracting memories (Pass 1), Stelline will update registered
        context files based on what it learned (Pass 2, same conversation).
        
        Args:
            name: Short identifier (e.g., "projects", "people").
            path: File path to maintain.
            instruction: How to update this file (e.g., "Track project statuses").
        """
        import sqlite3
        db_path = str(self._mk.storage_path / 'memkoshi.db')
        db = sqlite3.connect(db_path)
        db.execute('''CREATE TABLE IF NOT EXISTS stelline_contexts (
            name TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            instruction TEXT NOT NULL,
            enabled INTEGER DEFAULT 1
        )''')
        db.execute(
            'INSERT OR REPLACE INTO stelline_contexts (name, path, instruction) VALUES (?, ?, ?)',
            (name, path, instruction)
        )
        db.commit()
        db.close()

    def remove_context(self, name: str) -> None:
        """Remove a registered context file."""
        import sqlite3
        db_path = str(self._mk.storage_path / 'memkoshi.db')
        db = sqlite3.connect(db_path)
        db.execute('DELETE FROM stelline_contexts WHERE name = ?', (name,))
        db.commit()
        db.close()

    def list_contexts(self) -> list:
        """List all registered context files."""
        import sqlite3
        db_path = str(self._mk.storage_path / 'memkoshi.db')
        try:
            db = sqlite3.connect(db_path)
            db.execute('''CREATE TABLE IF NOT EXISTS stelline_contexts (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                instruction TEXT NOT NULL,
                enabled INTEGER DEFAULT 1
            )''')
            cursor = db.execute('SELECT name, path, instruction, enabled FROM stelline_contexts')
            result = [{'name': r[0], 'path': r[1], 'instruction': r[2], 'enabled': bool(r[3])} for r in cursor.fetchall()]
            db.close()
            return result
        except Exception:
            return []
