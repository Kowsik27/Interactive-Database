"""
connection_manager.py — In-Memory Session Registry
====================================================
Manages the lifecycle of all active database sessions.

A "session" in this app means:
  - A live SQLAlchemy Engine (connection pool to a MySQL database)
  - The fully-loaded database schema (tables, columns, types)
  - Metadata (which database, when connected, server version)

Architectural decisions:
  1. Thread-safe:  A threading.Lock guards all mutations to the registry.
  2. Singleton:    One ConnectionManager instance exists per process
                   (created at module level, imported everywhere).
  3. Memory-only:  No persistence. Sessions exist as long as the server runs.
                   If the server restarts, the frontend simply reconnects.
  4. No ORM:       We only store engines and metadata, not mapped models.

Why not a database for session storage?
  This is a single-server, single-user tool designed for developer use.
  An in-memory registry is fast, dependency-free, and perfectly adequate.
  For multi-user scale, replace the dict with Redis.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.engine import Engine

from database import create_db_engine, test_connection


# ── Session data structure ──────────────────────────────────────────────────

@dataclass
class DatabaseSession:
    """
    Represents one active user connection to a MySQL database.
    All fields are set at connection time and are immutable after creation.
    """
    session_id: str
    host: str
    port: int
    username: str
    database: str
    engine: Engine
    schema: Dict                         # populated by schema_loader
    server_version: str
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_summary(self) -> dict:
        """Serialisable summary — safe to return in API responses (no engine, no password)."""
        return {
            "session_id": self.session_id,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "server_version": self.server_version,
            "connected_at": self.connected_at.isoformat(),
            "table_count": len(self.schema.get("tables", {})),
            "tables": list(self.schema.get("tables", {}).keys()),
        }


# ── Manager class ───────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Thread-safe registry for all active DatabaseSession instances.

    Public API:
        create_session(...)  → (session_id, DatabaseSession)
        get_session(id)      → DatabaseSession | None
        remove_session(id)   → bool
        list_sessions()      → List[dict]
        session_exists(id)   → bool
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, DatabaseSession] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Session creation
    # ------------------------------------------------------------------

    def create_session(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str,
    ) -> tuple[str, DatabaseSession]:
        """
        Build an engine, test it, and register a new session.

        Steps:
          1. Create SQLAlchemy engine (no actual connection yet — lazy)
          2. Test connectivity with a SELECT VERSION() ping
          3. Register session in the registry under a fresh UUID
          4. Return (session_id, session) — schema is populated separately
             by schema_loader after this call returns, keeping this method fast.

        Raises:
          ConnectionError   if the database refuses the connection
          ValueError        if credentials are structurally invalid
        """
        # Basic input validation
        if not all([host, username, database]):
            raise ValueError("host, username, and database are required")
        if not (1 <= port <= 65535):
            raise ValueError(f"Invalid port: {port}")

        # Create engine (lazy — no socket opened yet)
        engine = create_db_engine(host, port, username, password, database)

        # Ping the server — this is the ONLY moment we use the password
        test_result = test_connection(engine)
        if not test_result["success"]:
            engine.dispose()  # release resources immediately on failure
            raise ConnectionError(
                f"Cannot connect to {host}:{port}/{database} — {test_result['error']}"
            )

        session_id = str(uuid.uuid4())
        session = DatabaseSession(
            session_id=session_id,
            host=host,
            port=port,
            username=username,
            database=database,
            engine=engine,
            schema={},                          # filled in by schema_loader
            server_version=test_result["server_version"],
        )

        with self._lock:
            self._sessions[session_id] = session

        return session_id, session

    # ------------------------------------------------------------------
    # Session retrieval
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[DatabaseSession]:
        """Return the session or None if it does not exist."""
        with self._lock:
            return self._sessions.get(session_id)

    def require_session(self, session_id: str) -> DatabaseSession:
        """
        Return the session or raise a KeyError with a descriptive message.
        Use this in route handlers where a missing session is a client error.
        """
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session '{session_id}' not found. Please reconnect.")
        return session

    def session_exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    # ------------------------------------------------------------------
    # Session mutation
    # ------------------------------------------------------------------

    def update_schema(self, session_id: str, schema: dict) -> None:
        """Attach a loaded schema to an existing session."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].schema = schema

    def remove_session(self, session_id: str) -> bool:
        """
        Disconnect and remove a session.
        Disposes the connection pool to release all MySQL connections cleanly.
        Returns True if the session existed, False if it was already gone.
        """
        with self._lock:
            session = self._sessions.pop(session_id, None)

        if session:
            session.engine.dispose()
            return True
        return False

    # ------------------------------------------------------------------
    # Session listing
    # ------------------------------------------------------------------

    def list_sessions(self) -> list:
        """Return serialisable summaries of all active sessions."""
        with self._lock:
            return [s.to_summary() for s in self._sessions.values()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


# ── Module-level singleton ──────────────────────────────────────────────────
# Import this instance everywhere — do NOT instantiate ConnectionManager again.

connection_manager = ConnectionManager()
