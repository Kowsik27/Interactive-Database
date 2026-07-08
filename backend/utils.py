"""
utils.py — Shared Utility Functions
=====================================
Small, pure helper functions used across multiple modules.

Rules for this file:
  - No imports from other project modules (avoids circular imports)
  - All functions are stateless (no side effects, no global state)
  - Each function does exactly one thing
"""

import csv
import io
import re
import time
from typing import Any, Dict, List, Optional


# ── Timing ───────────────────────────────────────────────────────────────────

class Timer:
    """
    Context manager for measuring elapsed time.

    Usage:
        with Timer() as t:
            do_something()
        print(f"{t.elapsed_ms:.1f}ms")
    """

    def __init__(self) -> None:
        self._start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000


# ── Result formatting ────────────────────────────────────────────────────────

def rows_to_dicts(columns: List[str], rows: List[tuple]) -> List[Dict[str, Any]]:
    """
    Convert raw SQLAlchemy rows (list of tuples) to a list of dicts.

    Useful for JSON serialisation.  Values that can't be serialised by
    default (datetime, Decimal) are coerced to strings.
    """
    result = []
    for row in rows:
        row_dict = {}
        for col, val in zip(columns, row):
            row_dict[col] = _coerce_value(val)
        result.append(row_dict)
    return result


def rows_to_lists(rows: List[tuple]) -> List[List[Any]]:
    """
    Convert rows (list of tuples) to list of lists.
    JSON-safe — all non-serialisable types are stringified.
    """
    return [[_coerce_value(v) for v in row] for row in rows]


def _coerce_value(val: Any) -> Any:
    """Coerce a DB value to a JSON-serialisable Python type."""
    if val is None:
        return None
    # datetime, date, time
    if hasattr(val, "isoformat"):
        return val.isoformat()
    # Decimal (MySQL DECIMAL/NUMERIC columns)
    try:
        from decimal import Decimal
        if isinstance(val, Decimal):
            return float(val)
    except ImportError:
        pass
    # bytes / bytearray → hex string
    if isinstance(val, (bytes, bytearray)):
        return val.hex()
    # Everything else: let it pass (int, float, str, bool are already safe)
    return val


# ── CSV export ───────────────────────────────────────────────────────────────

def results_to_csv(columns: List[str], rows: List[List[Any]]) -> str:
    """
    Serialise query results to a CSV string ready for download.
    Handles all types via _coerce_value.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_coerce_value(v) for v in row])
    return output.getvalue()


# ── Text helpers ─────────────────────────────────────────────────────────────

def truncate(text: str, max_chars: int = 200, suffix: str = "...") -> str:
    """Truncate a string to max_chars, appending suffix if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - len(suffix)] + suffix


def extract_sql_from_text(text: str) -> Optional[str]:
    """
    Extract a SQL statement from a larger text block.

    The LLM may return SQL wrapped in a markdown code block:
        ```sql
        SELECT * FROM users
        ```
    or plain text. This function handles both.

    Returns the extracted SQL string, or None if no SQL is found.
    """
    # Pattern 1: fenced code block with optional language tag
    match = re.search(
        r"```(?:sql)?\s*\n?(.*?)```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    # Pattern 2: SQL starts with SELECT keyword (common in non-fenced responses)
    match = re.search(
        r"(SELECT\s+.+?)(?:;|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    return None


def normalise_sql(sql: str) -> str:
    """
    Normalise a SQL string for consistent processing.
      - Strip leading/trailing whitespace
      - Collapse internal whitespace runs to single spaces
      - Remove trailing semicolons (we add one only at execution time)
      - Uppercase the statement for keyword detection
    """
    sql = sql.strip()
    sql = re.sub(r"\s+", " ", sql)
    sql = sql.rstrip(";").strip()
    return sql


def count_sql_statements(sql: str) -> int:
    """
    Count the number of SQL statements in a string.
    A naive but effective check: count semicolons not inside string literals.
    Returns ≥1 for any non-empty input.
    """
    # Remove string literals to avoid counting semicolons inside them
    cleaned = re.sub(r"'[^']*'", "''", sql)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)
    return cleaned.count(";") + (1 if cleaned.strip() else 0)


# ── Formatting helpers ───────────────────────────────────────────────────────

def format_row_count(n: int) -> str:
    """Format a row count for display: 0 → 'no rows', 1 → '1 row', etc."""
    if n == 0:
        return "no rows"
    if n == 1:
        return "1 row"
    return f"{n:,} rows"


def format_execution_time(ms: float) -> str:
    """Format execution time for display."""
    if ms < 1:
        return "<1ms"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"
