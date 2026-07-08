"""
database.py — Database Engine Factory & Connection Utilities
=============================================================
Responsible for:
  1. Creating SQLAlchemy engines from user-supplied credentials
  2. Testing connectivity before committing to a session
  3. Providing raw connection objects for query execution

Architectural decision: This module knows NOTHING about sessions or chat.
It is pure infrastructure — a factory that creates database handles.
The connection_manager.py layer sits above it and manages session lifecycle.

Why SQLAlchemy Core (not ORM)?
  We are introspecting arbitrary user databases, not mapping our own models.
  SQLAlchemy Core gives us full control over raw SQL execution with the
  safety of parameterised queries and connection pooling.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.pool import QueuePool

from config import settings


# ── Connection URL builder ──────────────────────────────────────────────────

def build_connection_url(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
) -> str:
    """
    Construct a SQLAlchemy-compatible MySQL connection URL.

    Uses PyMySQL as the driver (pure Python, no C extensions needed).
    Password is URL-encoded to handle special characters safely.
    """
    from urllib.parse import quote_plus
    encoded_password = quote_plus(password)
    return (
        f"mysql+pymysql://{username}:{encoded_password}"
        f"@{host}:{port}/{database}"
        f"?charset=utf8mb4"
    )


# ── Engine factory ──────────────────────────────────────────────────────────

def create_db_engine(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
) -> Engine:
    """
    Create and configure a SQLAlchemy Engine with a connection pool.

    Pool settings:
      - pool_size=5:        Keep 5 connections open (adequate for single-user app)
      - max_overflow=10:    Allow burst to 15 total connections
      - pool_timeout=30:    Wait up to 30s before raising PoolTimeout
      - pool_recycle=1800:  Recycle connections every 30 min (avoids MySQL 8hr timeout)
      - pool_pre_ping=True: Validate connection health before use (handles dropped connections)

    The connect_args set a per-connection read timeout matching our configured
    execution timeout, so runaway queries are killed at the driver level.
    """
    url = build_connection_url(host, port, username, password, database)

    engine = create_engine(
        url,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "read_timeout": settings.max_execution_time_seconds,
            "write_timeout": settings.max_execution_time_seconds,
        },
        echo=settings.debug,   # logs all SQL to stdout in debug mode
    )

    # Register a connect event to enforce a session-level query timeout.
    # This is a second layer of protection on top of the driver-level timeout.
    @event.listens_for(engine, "connect")
    def set_session_timeout(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        timeout_ms = settings.max_execution_time_seconds * 1_000
        cursor.execute(f"SET SESSION MAX_EXECUTION_TIME={timeout_ms}")
        cursor.close()

    return engine


# ── Connectivity test ───────────────────────────────────────────────────────

def test_connection(engine: Engine) -> dict:
    """
    Attempt a trivial query to verify the engine can actually reach the server.

    Returns a dict with:
      - success (bool)
      - server_version (str) — MySQL version string on success
      - error (str | None)   — human-readable error message on failure
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT VERSION() AS version"))
            row = result.fetchone()
            version = row[0] if row else "unknown"
            return {"success": True, "server_version": version, "error": None}
    except OperationalError as exc:
        # Extract the most useful part of the MySQL error message
        msg = str(exc.orig) if exc.orig else str(exc)
        return {"success": False, "server_version": None, "error": msg}
    except SQLAlchemyError as exc:
        return {"success": False, "server_version": None, "error": str(exc)}


# ── Context manager for short-lived connections ──────────────────────────────

@contextmanager
def get_connection(engine: Engine) -> Generator:
    """
    Context manager that yields a single database connection.
    The connection is checked back into the pool on exit, whether or
    not an exception occurred.

    Usage:
        with get_connection(engine) as conn:
            result = conn.execute(text("SELECT ..."))
    """
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()
