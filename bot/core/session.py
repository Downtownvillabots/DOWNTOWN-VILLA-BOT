"""
Session management.

Stores per‑user data in memory for the current run.
Future features can extend this to use persistent storage.
"""

from typing import Any, Dict


class SessionManager:
    """Simple in‑memory session store."""

    def __init__(self) -> None:
        self._sessions: Dict[int, Dict[str, Any]] = {}

    def get(self, user_id: int) -> Dict[str, Any]:
        """Return the session dict for a user, creating it if needed."""
        if user_id not in self._sessions:
            self._sessions[user_id] = {}
        return self._sessions[user_id]

    def set(self, user_id: int, key: str, value: Any) -> None:
        """Store a value in the user's session."""
        session = self.get(user_id)
        session[key] = value

    def clear(self, user_id: int) -> None:
        """Remove all data for a user."""
        self._sessions.pop(user_id, None)
