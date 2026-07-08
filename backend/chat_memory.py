"""
chat_memory.py — Conversation History Manager
==============================================
Maintains per-session conversation history so the AI can understand
follow-up questions without the user repeating context.

Design decisions:
  1. Sliding window:  Only the last N turns are injected into prompts.
     This keeps prompt size bounded regardless of conversation length.
     Older turns are archived (stored but not sent to LLM).
  2. Full archive:   All turns are preserved in the session store so the
     user can scroll back through the entire conversation in the sidebar.
  3. Thread-safe:    A lock guards all mutations per-session.
  4. Memory-only:    No database persistence for this implementation.
     For production multi-user scale, replace the in-memory dict with Redis
     and add user ID partitioning.

Conversation format (each turn):
  {
      "user":      "Show all employees",
      "assistant": "Here are all 42 employees in the database.",
      "sql":       "SELECT * FROM employees",
      "timestamp": "2024-01-15T10:30:00.123456"
  }
"""

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import settings


# ── ChatMemory ───────────────────────────────────────────────────────────────

class ChatMemory:
    """
    Manages conversation history across all active sessions.

    Public API:
        save_turn(session_id, user, assistant, sql)  — store one Q&A pair
        get_history(session_id)                       — retrieve all turns
        get_window(session_id)                        — retrieve last N turns for LLM
        clear_history(session_id)                     — wipe a session's history
        get_turn_count(session_id)                    — how many turns so far
    """

    def __init__(self, window_size: Optional[int] = None) -> None:
        # Each session gets its own list of turn dicts
        self._histories: Dict[str, List[dict]] = defaultdict(list)
        self._locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._global_lock = threading.Lock()
        # Use settings value unless overridden (useful for testing)
        self._window_size = window_size or settings.chat_history_window

    def _get_lock(self, session_id: str) -> threading.Lock:
        """Get or create a per-session lock (thread-safe)."""
        with self._global_lock:
            return self._locks[session_id]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        sql: Optional[str] = None,
    ) -> None:
        """
        Append one conversation turn to the session history.
        Timestamps are UTC ISO-8601 for unambiguous cross-timezone serialisation.
        """
        turn = {
            "user": user_message,
            "assistant": assistant_message,
            "sql": sql,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        lock = self._get_lock(session_id)
        with lock:
            self._histories[session_id].append(turn)

    def clear_history(self, session_id: str) -> None:
        """Wipe all conversation history for a session."""
        lock = self._get_lock(session_id)
        with lock:
            self._histories[session_id] = []

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(self, session_id: str) -> List[dict]:
        """Return a copy of the full conversation history (oldest first)."""
        lock = self._get_lock(session_id)
        with lock:
            return list(self._histories.get(session_id, []))

    def get_window(self, session_id: str) -> List[dict]:
        """
        Return only the last N turns for LLM injection.

        This is the sliding context window.  Keeping it bounded ensures:
          - Prompt tokens stay within model limits
          - Older context that's no longer relevant is excluded
          - API costs remain predictable
        """
        lock = self._get_lock(session_id)
        with lock:
            history = self._histories.get(session_id, [])
            return list(history[-self._window_size:])

    def get_turn_count(self, session_id: str) -> int:
        lock = self._get_lock(session_id)
        with lock:
            return len(self._histories.get(session_id, []))

    def history_to_prompt_text(self, session_id: str) -> str:
        """
        Format the conversation window as a plain-text block for the LLM prompt.

        Example output:
            User: Show all employees
            Assistant: SELECT * FROM employees — Found 42 employees.

            User: Only those in engineering
            Assistant: SELECT * FROM employees WHERE department = 'Engineering' — Found 8 employees.
        """
        window = self.get_window(session_id)
        if not window:
            return ""

        lines = []
        for turn in window:
            lines.append(f"User: {turn['user']}")
            assistant_line = turn["assistant"]
            if turn.get("sql"):
                assistant_line = f"[SQL: {turn['sql']}] {assistant_line}"
            lines.append(f"Assistant: {assistant_line}")
            lines.append("")  # blank line between turns

        return "\n".join(lines).strip()


# ── Module-level singleton ───────────────────────────────────────────────────
# Import this everywhere. Do NOT create a second ChatMemory instance.

chat_memory = ChatMemory()
