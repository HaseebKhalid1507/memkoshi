"""Unified context and handoff management for Memkoshi."""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone


class ContextManager:
    """Unified context and handoff management for Memkoshi."""
    
    def __init__(self, storage: 'StorageBackend'):
        """Initialize context manager with storage backend.
        
        Args:
            storage: Storage backend instance
        """
        self._storage = storage
        self._boot_cache: Optional[Dict[str, Any]] = None
        self._session_data: Dict[str, Any] = {}
    
    # ── Core Operations ─────────────────────────────────
    
    def set(self, key: str, value: Any, layer: str = "session") -> None:
        """Set a context value in the specified layer.
        
        Args:
            key: Context key (e.g., 'current_task', 'debug_flags')
            value: Any JSON-serializable value
            layer: 'boot', 'session', or 'archive' (default: 'session')
            
        Examples:
            context.set('current_task', 'Fix login timeout bug')
            context.set('team_preferences', {'editor': 'vim'}, layer='boot')
            context.set('completed_sprint', sprint_data, layer='archive')
        """
        # Input validation
        if not key or not isinstance(key, str) or not key.strip():
            raise ValueError("Key must be a non-empty string")
        
        if layer not in ['boot', 'session', 'archive']:
            raise ValueError(f"Invalid layer '{layer}'. Must be 'boot', 'session', or 'archive'")
        
        # For session layer, store in memory
        if layer == 'session':
            self._session_data[key] = value
        
        # All layers are persisted to storage
        try:
            serialized_value = json.dumps(value) if not isinstance(value, str) else value
        except (TypeError, ValueError) as e:
            # Fall back to string representation for non-serializable objects
            serialized_value = str(value)
        
        value_type = type(value).__name__
        
        self._storage.set_context_data(layer, key, serialized_value, value_type)
        
        # Clear boot cache if we modified boot layer
        if layer == 'boot':
            self._boot_cache = None
    
    def get(self, key: str, layer: str = "session", default: Any = None) -> Any:
        """Get a context value from the specified layer.
        
        Args:
            key: Context key to retrieve
            layer: Layer to search ('boot', 'session', 'archive', or 'all')
            default: Default value if key not found
            
        Returns:
            The stored value or default
            
        Note:
            layer='all' searches session → boot → archive in order
        """
        if layer == 'all':
            # Search in priority order: session → boot → archive
            for search_layer in ['session', 'boot', 'archive']:
                result = self.get(key, search_layer)
                if result is not None:
                    return result
            return default
        
        if layer not in ['boot', 'session', 'archive']:
            raise ValueError(f"Invalid layer '{layer}'. Must be 'boot', 'session', 'archive', or 'all'")
        
        # Check session memory first for session layer
        if layer == 'session' and key in self._session_data:
            return self._session_data[key]
        
        # Get from storage
        result = self._storage.get_context_data(layer, key)
        if result is None:
            return default
        
        # Deserialize if needed
        value, value_type = result
        if value_type in ['dict', 'list', 'int', 'float', 'bool']:
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError, ValueError):
                # Return raw value if deserialization fails
                return value
        return value
    
    def checkpoint(self, notes: str = "") -> Dict[str, Any]:
        """Save current session state as a checkpoint.
        
        Creates a snapshot of current session context and optionally
        moves it to archive with timestamp and notes.
        
        Args:
            notes: Optional description of the checkpoint
            
        Returns:
            Checkpoint metadata (id, timestamp, item_count)
        """
        # Serialize current session state
        try:
            session_state = json.dumps(self._session_data)
        except (TypeError, ValueError) as e:
            # Fall back to string representation if serialization fails
            session_state = str(self._session_data)
        
        # Save checkpoint to storage
        checkpoint_id = self._storage.save_checkpoint(notes, session_state)
        
        # Count items in session
        item_count = len(self._session_data)
        
        return {
            "id": checkpoint_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "item_count": item_count,
            "notes": notes
        }
    
    def get_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Get the latest checkpoint.
        
        Returns:
            Latest checkpoint dict or None
        """
        return self._storage.get_latest_checkpoint()
    
    def get_boot(self, token_budget: int = 4096) -> Dict[str, Any]:
        """Get boot context optimized for token budget.
        
        Returns lean, essential context for agent startup.
        Automatically truncates/prioritizes to fit within budget.
        
        Args:
            token_budget: Max tokens to use (rough estimate)
            
        Returns:
            Boot context dict with keys: handoff, recent_sessions, 
            preferences, memory_stats, token_count_estimate
        """
        if self._boot_cache:
            return self._boot_cache
        
        # Get handoff
        handoff = self.get_handoff()
        
        # Get recent sessions
        recent_sessions = self.get_recent_sessions(n=3)
        
        # Get boot layer preferences
        preferences = self._storage.get_layer_data('boot')
        
        # Get memory stats from storage
        memory_stats = self._storage.get_stats()
        
        # Build initial context
        boot_context = {
            "handoff": handoff,
            "recent_sessions": recent_sessions,
            "preferences": preferences or {},
            "memory_stats": memory_stats or {}
        }
        
        # Estimate tokens and fit to budget
        boot_context = self._fit_to_budget(boot_context, token_budget)
        
        # Cache the result
        self._boot_cache = boot_context
        
        return boot_context
    
    # ── Handoff Operations ──────────────────────────────
    
    def set_handoff(self, task: str, progress: str = "", 
                   details: Any = None, next_steps: List[str] = None, 
                   priority: int = 3) -> None:
        """Set handoff state for next session.
        
        Args:
            task: What you're working on
            progress: Current status/what's been done
            details: Any additional context (dict, list, etc.)
            next_steps: List of next actions to take
            priority: Priority level (1=high, 5=low, default=3)
        """
        # Input validation
        if not task or not isinstance(task, str) or not task.strip():
            raise ValueError("Task must be a non-empty string")
        
        if not isinstance(priority, int) or priority < 1 or priority > 5:
            raise ValueError("Priority must be an integer between 1 and 5")
        
        handoff_data = {
            "task": task,
            "progress": progress,
            "details": details or {},
            "next_steps": next_steps or [],
            "priority": priority,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        self.set('_handoff', handoff_data, layer='session')
        
        # Clear boot cache since handoff changed
        self._boot_cache = None
    
    def get_handoff(self) -> Optional[Dict[str, Any]]:
        """Get current handoff state.
        
        Returns:
            Handoff dict with keys: task, progress, details, next_steps, 
            priority, created_at, or None if no handoff exists
        """
        return self.get('_handoff', layer='session')
    
    def clear_handoff(self) -> bool:
        """Clear current handoff state.
        
        Returns:
            True if handoff was cleared, False if none existed
        """
        handoff = self.get_handoff()
        if handoff is None:
            return False
        
        # Remove from session memory
        if '_handoff' in self._session_data:
            del self._session_data['_handoff']
        
        # Remove from storage
        self._storage.delete_context_data('session', '_handoff')
        
        # Clear boot cache
        self._boot_cache = None
        
        return True
    
    # ── Session Management ──────────────────────────────
    
    def add_session(self, summary: str, extracted_count: int = 0) -> None:
        """Add a session summary to recent sessions.
        
        Args:
            summary: Brief description of what happened
            extracted_count: Number of memories extracted (for stats)
        """
        self._storage.add_session_log(summary, extracted_count)
        
        # Clear boot cache since sessions changed
        self._boot_cache = None
    
    def get_recent_sessions(self, n: int = 3) -> List[Dict[str, Any]]:
        """Get recent session summaries.
        
        Args:
            n: Number of recent sessions to return
            
        Returns:
            List of session dicts with keys: summary, timestamp, 
            extracted_count, session_id
        """
        return self._storage.get_recent_sessions(n)
    
    # ── Private Methods ──────────────────────────────
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: ~4 chars per token for English."""
        if isinstance(text, dict) or isinstance(text, list):
            text = json.dumps(text)
        elif not isinstance(text, str):
            text = str(text)
        
        return len(text) // 4
    
    def _fit_to_budget(self, context: Dict[str, Any], budget: int) -> Dict[str, Any]:
        """Prioritize and truncate context to fit token budget."""
        # Priority order: handoff > preferences > recent_sessions > memory_stats
        
        # Start with essentials that always fit - initialize all required keys
        result = {
            "handoff": None,
            "recent_sessions": [],
            "preferences": {},
            "memory_stats": context.get("memory_stats", {}),
            "token_count_estimate": 0
        }
        
        current_tokens = self._estimate_tokens(json.dumps(result))
        remaining_budget = budget - current_tokens
        
        # Add handoff if it exists (highest priority)
        handoff = context.get("handoff")
        if handoff and remaining_budget > 0:
            handoff_tokens = self._estimate_tokens(json.dumps(handoff))
            if handoff_tokens <= remaining_budget:
                result["handoff"] = handoff
                remaining_budget -= handoff_tokens
                current_tokens += handoff_tokens
        
        # Add preferences (high priority)
        preferences = context.get("preferences", {})
        if preferences and remaining_budget > 0:
            pref_tokens = self._estimate_tokens(json.dumps(preferences))
            if pref_tokens <= remaining_budget:
                result["preferences"] = preferences
                remaining_budget -= pref_tokens
                current_tokens += pref_tokens
            else:
                # Truncate preferences to fit
                result["preferences"] = self._truncate_dict(preferences, remaining_budget)
                remaining_budget = 0
        
        # Add recent sessions (medium priority)
        sessions = context.get("recent_sessions", [])
        if sessions and remaining_budget > 0:
            sessions_tokens = self._estimate_tokens(json.dumps(sessions))
            if sessions_tokens <= remaining_budget:
                result["recent_sessions"] = sessions
                current_tokens += sessions_tokens
            else:
                # Take as many sessions as fit
                fitted_sessions = []
                for session in sessions:
                    session_tokens = self._estimate_tokens(json.dumps(session))
                    if session_tokens <= remaining_budget:
                        fitted_sessions.append(session)
                        remaining_budget -= session_tokens
                        current_tokens += session_tokens
                    else:
                        break
                result["recent_sessions"] = fitted_sessions
        
        result["token_count_estimate"] = current_tokens
        return result
    
    def _truncate_dict(self, data: Dict[str, Any], token_budget: int) -> Dict[str, Any]:
        """Truncate dictionary to fit within token budget."""
        result = {}
        remaining = token_budget
        
        # Sort by key length (shorter keys first, likely more important)
        sorted_items = sorted(data.items(), key=lambda x: len(str(x[0])))
        
        for key, value in sorted_items:
            item_tokens = self._estimate_tokens(json.dumps({key: value}))
            if item_tokens <= remaining:
                result[key] = value
                remaining -= item_tokens
            else:
                break
        
        return result