"""
query_executor.py — Safe SQL Query Executor
=============================================
Executes pre-validated SELECT queries against a live MySQL session
and returns structured results with timing metadata.

This module sits AFTER sql_validator.py in the pipeline — it trusts
that the incoming SQL has already been validated as safe. Its job
is purely execution, result marshalling, and error handling.

Key responsibilities:
  1. Execute the validated SQL using the session's engine
  2. Apply the MAX_ROWS_RETURNED cap via LIMIT injection
  3. Marshal raw SQLAlchemy rows to JSON-serialisable Python types
  4. Record precise execution time
  5. Translate database errors into user-friendly messages

Why inject LIMIT rather than relying on the LLM to include it?
  The LLM may forget LIMIT, especially for follow-up questions.
  We ALWAYS add 'LIMIT n' if it is absent, as a guaranteed safeguard
  against accidentally returning millions of rows.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from config import settings
from database import get_connection
from utils import Timer, rows_to_lists

logger = logging.getLogger(__name__)


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class QueryResult:
    """Structured result of a single query execution."""
    success: bool
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    execution_time_ms: float
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "error": self.error,
        }


# ── Executor ─────────────────────────────────────────────────────────────────

class QueryExecutor:
    """
    Executes validated SQL queries and returns structured QueryResult objects.

    Usage:
        result = executor.execute(engine, sql)
        if result.success:
            display(result.columns, result.rows)
    """

    def __init__(self, max_rows: Optional[int] = None) -> None:
        self._max_rows = max_rows or settings.max_rows_returned

    def execute(self, engine: Engine, sql: str) -> QueryResult:
        """
        Execute a validated SELECT query.

        Args:
            engine: The SQLAlchemy engine for the active session.
            sql:    A pre-validated, normalised SQL string (no semicolons).

        Returns:
            QueryResult with columns, rows, timing, and error info.
        """
        # Ensure we never accidentally run a query without a row cap
        safe_sql = self._enforce_limit(sql)

        with Timer() as timer:
            try:
                result = self._run(engine, safe_sql)
                result.execution_time_ms = timer.elapsed_ms
                return result
            except Exception:
                # Timer still captured time up to the exception
                pass

        # If we reach here, _run raised — timer.elapsed_ms is set
        result = self._run_with_error_handling(engine, safe_sql)
        result.execution_time_ms = timer.elapsed_ms
        return result

    def _run(self, engine: Engine, sql: str) -> QueryResult:
        """Core execution path — no exception handling (caller handles it)."""
        with get_connection(engine) as conn:
            with Timer() as t:
                result_proxy = conn.execute(text(sql))
                rows_raw = result_proxy.fetchall()
                columns = list(result_proxy.keys())
            rows = rows_to_lists(rows_raw)

        return QueryResult(
            success=True,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            execution_time_ms=t.elapsed_ms,
        )

    def _run_with_error_handling(self, engine: Engine, sql: str) -> QueryResult:
        """Execution path with full exception handling."""
        try:
            with get_connection(engine) as conn:
                with Timer() as t:
                    result_proxy = conn.execute(text(sql))
                    rows_raw = result_proxy.fetchall()
                    columns = list(result_proxy.keys())
                rows = rows_to_lists(rows_raw)
            return QueryResult(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=t.elapsed_ms,
            )
        except OperationalError as exc:
            error_msg = self._format_operational_error(exc)
            logger.error(f"Query execution OperationalError: {exc}")
            return QueryResult(
                success=False, columns=[], rows=[], row_count=0,
                execution_time_ms=0, error=error_msg,
            )
        except ProgrammingError as exc:
            error_msg = f"SQL syntax error: {self._extract_mysql_message(str(exc))}"
            logger.error(f"Query execution ProgrammingError: {exc}")
            return QueryResult(
                success=False, columns=[], rows=[], row_count=0,
                execution_time_ms=0, error=error_msg,
            )
        except SQLAlchemyError as exc:
            logger.error(f"Query execution SQLAlchemyError: {exc}")
            return QueryResult(
                success=False, columns=[], rows=[], row_count=0,
                execution_time_ms=0, error=f"Database error: {str(exc)[:200]}",
            )
        except Exception as exc:
            logger.exception("Unexpected query execution error")
            return QueryResult(
                success=False, columns=[], rows=[], row_count=0,
                execution_time_ms=0, error=f"Unexpected error: {str(exc)[:200]}",
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _enforce_limit(self, sql: str) -> str:
        """
        Inject a LIMIT clause if the SQL does not already have one.

        We check for the LIMIT keyword at the outermost query level
        (ignoring subqueries) to avoid double-limiting.
        """
        # Quick check: does the SQL already contain a top-level LIMIT?
        if self._has_top_level_limit(sql):
            return sql

        limited_sql = f"{sql} LIMIT {self._max_rows}"
        logger.debug(f"Injected LIMIT {self._max_rows} into query")
        return limited_sql

    def _has_top_level_limit(self, sql: str) -> bool:
        """
        Detect if LIMIT appears at the top level (not inside a subquery).
        Strategy: strip all parenthesised blocks, then search for LIMIT.
        """
        depth = 0
        chars = []
        for ch in sql:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0:
                chars.append(ch)
        top_level = "".join(chars)
        return bool(re.search(r"\bLIMIT\b", top_level, re.IGNORECASE))

    def _extract_mysql_message(self, error_str: str) -> str:
        """Pull the human-readable part out of a SQLAlchemy error string."""
        match = re.search(r"\(.*?\)\s*(.+)", error_str)
        return match.group(1).strip() if match else error_str[:200]

    def _format_operational_error(self, exc: OperationalError) -> str:
        """Format an OperationalError into a user-friendly message."""
        orig = str(exc.orig) if exc.orig else str(exc)
        if "max_execution_time" in orig.lower() or "query was interrupted" in orig.lower():
            return (
                f"Query exceeded the maximum execution time "
                f"({settings.max_execution_time_seconds}s). "
                "Try a more specific query or add a WHERE clause."
            )
        if "doesn't exist" in orig.lower():
            return f"Table or column not found: {orig[:200]}"
        return f"Database operational error: {orig[:200]}"


# ── Module-level singleton ───────────────────────────────────────────────────
executor = QueryExecutor()
