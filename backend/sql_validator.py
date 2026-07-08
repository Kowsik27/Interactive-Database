"""
sql_validator.py — SQL Safety Gate
====================================
Every AI-generated SQL string must pass through this module before
it touches the database. This is the critical security layer.

Validation strategy: ALLOWLIST, not blocklist.
  We do NOT try to catch every possible dangerous keyword.
  We ONLY allow SELECT and WITH (for read-only CTEs).
  Anything that is not demonstrably a read-only SELECT is rejected.

This two-phase approach:
  Phase 1 — Structural checks  (fast, no parsing needed)
  Phase 2 — Token-level checks (keyword scanning)

Why not use an SQL parser library?
  SQL parsers (sqlglot, sqlparse) are good but:
  - They can be fooled by obfuscated input
  - Parser bugs can create false negatives
  - Adding a dependency for validation creates supply-chain risk
  A simple, auditable allowlist is harder to bypass and easier to reason
  about in a security review.

Validation result shape:
  {"valid": True,  "sql": "SELECT ...", "error": None}
  {"valid": False, "sql": None,         "error": "reason"}
"""

import re
import logging
from typing import Optional
from dataclasses import dataclass

from config import settings
from utils import normalise_sql, extract_sql_from_text

logger = logging.getLogger(__name__)


# ── Blocked keywords ─────────────────────────────────────────────────────────

# Core mutations — always blocked regardless of context
BLOCKED_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "REPLACE", "MERGE",
    "CALL", "EXEC", "EXECUTE", "LOAD", "OUTFILE", "DUMPFILE",
    "INTO OUTFILE", "INTO DUMPFILE",
}

# Suspicious patterns that suggest injection attempts
SUSPICIOUS_PATTERNS = [
    r"--",                          # SQL line comment (injection hiding)
    r"/\*.*?\*/",                   # block comment (injection hiding)
    r";\s*\w",                      # multiple statements
    r"xp_\w+",                      # SQL Server extended procs
    r"information_schema\.user",    # trying to enumerate users
    r"mysql\.user",                  # trying to read mysql credentials
    r"performance_schema",          # internal MySQL tables
    r"sys\.schema",                 # sys schema (server internals)
]

# Compile suspicious patterns for efficiency
_SUSPICIOUS_COMPILED = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in SUSPICIOUS_PATTERNS]


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid: bool
    sql: Optional[str]       # cleaned SQL if valid, None if invalid
    error: Optional[str]     # human-readable rejection reason

    def to_dict(self) -> dict:
        return {"valid": self.valid, "sql": self.sql, "error": self.error}


# ── Main validator ───────────────────────────────────────────────────────────

class SQLValidator:
    """
    Validates AI-generated SQL for safety before database execution.

    Usage:
        result = validator.validate(raw_llm_output)
        if result.valid:
            execute(result.sql)
        else:
            return error(result.error)
    """

    def __init__(self) -> None:
        # Merge core blocked keywords with any extras from config
        self._blocked = BLOCKED_KEYWORDS | {
            kw.upper() for kw in settings.get_extra_blocked_keywords()
        }

    def validate(self, raw_text: str) -> ValidationResult:
        """
        Full validation pipeline.

        Steps:
          1. Extract SQL from the LLM output (handles ```sql fences)
          2. Normalise whitespace and remove trailing semicolon
          3. Check it is not empty
          4. Check for suspicious injection patterns
          5. Check first keyword is SELECT or WITH
          6. Scan for blocked DML/DDL keywords
          7. Return a clean, validated SQL string

        The `raw_text` may be the entire LLM response (including the
        EXPLANATION section), so step 1 handles extraction gracefully.
        """
        # ── Step 1: Extract SQL ───────────────────────────────────────────
        sql = extract_sql_from_text(raw_text)

        if sql is None:
            # Maybe the whole string IS the SQL (no fences)
            sql = raw_text.strip()

        if not sql:
            return ValidationResult(
                valid=False, sql=None,
                error="No SQL query was found in the AI response."
            )

        # ── Step 2: Normalise ─────────────────────────────────────────────
        sql = normalise_sql(sql)

        # ── Step 3: Empty check ───────────────────────────────────────────
        if len(sql) < 7:   # shorter than "SELECT " is definitely wrong
            return ValidationResult(
                valid=False, sql=None,
                error="The generated SQL is too short to be valid."
            )

        # ── Step 4: Suspicious pattern check ─────────────────────────────
        for pattern in _SUSPICIOUS_COMPILED:
            if pattern.search(sql):
                logger.warning(f"SQL failed suspicious-pattern check: {pattern.pattern!r}")
                return ValidationResult(
                    valid=False, sql=None,
                    error="The SQL contains patterns that are not allowed for safety reasons."
                )

        # ── Step 5: Must start with SELECT or WITH ────────────────────────
        first_token = _get_first_token(sql)
        if first_token not in ("SELECT", "WITH"):
            return ValidationResult(
                valid=False, sql=None,
                error=(
                    f"Only SELECT queries are allowed. "
                    f"The generated query starts with '{first_token}', which is not permitted."
                )
            )

        # ── Step 6: Blocked keyword scan ─────────────────────────────────
        tokens = _tokenise(sql)
        for token in tokens:
            if token in self._blocked:
                logger.warning(f"SQL blocked — contains keyword: {token!r}")
                return ValidationResult(
                    valid=False, sql=None,
                    error=(
                        f"The generated SQL contains the blocked keyword '{token}'. "
                        f"Only read-only SELECT queries are allowed."
                    )
                )

        # ── Step 7: WITH must be a read-only CTE ─────────────────────────
        if first_token == "WITH":
            if not _with_resolves_to_select(sql):
                return ValidationResult(
                    valid=False, sql=None,
                    error="WITH (CTE) queries must resolve to a SELECT statement."
                )

        logger.debug(f"SQL passed validation: {sql[:80]}...")
        return ValidationResult(valid=True, sql=sql, error=None)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_first_token(sql: str) -> str:
    """Return the uppercase first word of the SQL string."""
    match = re.match(r"^\s*(\w+)", sql)
    return match.group(1).upper() if match else ""


def _tokenise(sql: str) -> set:
    """
    Split SQL into a set of uppercase word tokens.
    This is intentionally simple — we are scanning for keyword presence,
    not parsing structure.
    """
    return {word.upper() for word in re.findall(r"\b[a-zA-Z_]+\b", sql)}


def _with_resolves_to_select(sql: str) -> bool:
    """
    A WITH query is safe only if the final statement is a SELECT.
    We check by finding the last meaningful keyword before the closing
    parenthesis of the CTE block.

    Simple heuristic: after the last ')' that closes a CTE, the next
    non-whitespace word must be SELECT.
    """
    # Remove string literals to avoid false matches inside them
    cleaned = re.sub(r"'[^']*'", "''", sql)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)

    # Find text after the CTE definitions — should be "SELECT ..."
    # Pattern: WITH ... ) SELECT ...
    match = re.search(r"\)\s*(SELECT)\b", cleaned, re.IGNORECASE | re.DOTALL)
    return bool(match)


# ── Module-level singleton ───────────────────────────────────────────────────
validator = SQLValidator()
