"""
summary.py — Natural Language Result Summarizer
================================================
After a SQL query executes successfully, this module calls IBM Granite
a second time to produce a plain-English explanation of the results.

Why a second LLM call instead of having one call do everything?
  Split-responsibility approach:
    Call 1 (prompt_builder + llm): Generate SQL from the question + schema
    Call 2 (summary + llm):        Explain the ACTUAL results after execution

  This produces better explanations because:
    - The model sees the real row data, not a hypothetical result set
    - The explanation is grounded in fact, not speculation
    - We can detect "0 rows" and give a meaningful "nothing found" message
    - Errors from execution are handled cleanly before explanation

  The tradeoff is latency (two API calls). This is acceptable because:
    - We run both sequentially; first call validates intent, second explains
    - Granite is fast enough that total roundtrip is ~2–4s
    - The UX shows a typing animation, so the wait feels natural

For very simple queries (single-column aggregate like COUNT), we skip
the second call and generate the explanation locally to save latency.
"""

import logging
import re
from typing import List, Any, Optional

from llm import granite
from prompt_builder import build_summary_prompt
from utils import format_row_count

logger = logging.getLogger(__name__)


class ResultSummarizer:
    """
    Generates natural-language summaries of SQL query results.

    Public API:
        summarize(user_message, sql, columns, rows, execution_time_ms)
            → str  (plain English explanation)
    """

    # Threshold: if the result is this simple, summarize locally
    # (avoids a second API call for trivial responses)
    SIMPLE_RESULT_THRESHOLD = 1  # single row, single column

    def summarize(
        self,
        user_message: str,
        sql: str,
        columns: List[str],
        rows: List[List[Any]],
        execution_time_ms: float,
    ) -> str:
        """
        Generate a natural-language explanation of query results.

        Falls back to a local template if the result is trivially simple
        or if the LLM call fails (ensures the user always gets an answer).
        """
        row_count = len(rows)

        # ── Case 1: No results ───────────────────────────────────────────────
        if row_count == 0:
            return self._explain_empty_result(user_message, sql)

        # ── Case 2: Single scalar result (e.g. COUNT(*), SUM, MAX) ──────────
        if row_count == 1 and len(columns) == 1:
            return self._explain_scalar(user_message, columns[0], rows[0][0])

        # ── Case 3: Full LLM explanation ─────────────────────────────────────
        try:
            prompt = build_summary_prompt(
                user_message=user_message,
                sql=sql,
                columns=columns,
                rows=rows,
                row_count=row_count,
                execution_time_ms=execution_time_ms,
            )
            explanation = granite.generate(prompt, max_new_tokens=300, temperature=0.2)
            # Clean up any accidental fences or prefixes the model adds
            explanation = self._clean_explanation(explanation)
            return explanation

        except Exception as exc:
            logger.warning(f"Summary LLM call failed, using fallback: {exc}")
            return self._fallback_summary(user_message, columns, rows, row_count)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _explain_empty_result(self, user_message: str, sql: str) -> str:
        """Generate a clear 'no results' explanation."""
        return (
            "The query ran successfully but returned no results. "
            "This means no records matched the conditions in your question. "
            "You might want to try broader search criteria or check that the data exists."
        )

    def _explain_scalar(self, user_message: str, column: str, value: Any) -> str:
        """Generate a direct explanation for a single-value result."""
        formatted_value = _format_scalar(value)
        col_display = column.replace("_", " ").title()

        # Detect common aggregate patterns
        col_lower = column.lower()
        if any(kw in col_lower for kw in ("count", "total", "num", "cnt")):
            return f"The result is {formatted_value} — this is the total count matching your question."
        if any(kw in col_lower for kw in ("sum", "total_amount", "revenue")):
            return f"The total is {formatted_value}."
        if any(kw in col_lower for kw in ("avg", "average", "mean")):
            return f"The average is {formatted_value}."
        if any(kw in col_lower for kw in ("max", "maximum", "highest", "latest")):
            return f"The maximum value is {formatted_value}."
        if any(kw in col_lower for kw in ("min", "minimum", "lowest", "earliest")):
            return f"The minimum value is {formatted_value}."

        return f"The result for {col_display} is {formatted_value}."

    def _fallback_summary(
        self,
        user_message: str,
        columns: List[str],
        rows: List[List[Any]],
        row_count: int,
    ) -> str:
        """
        Local template-based fallback when the LLM is unavailable.
        Always produces a grammatically correct, useful response.
        """
        col_list = ", ".join(columns[:5])
        more_cols = f" (and {len(columns) - 5} more columns)" if len(columns) > 5 else ""
        rows_str = format_row_count(row_count)

        return (
            f"The query returned {rows_str} "
            f"with columns: {col_list}{more_cols}. "
            f"The data is displayed in the table below."
        )

    def _clean_explanation(self, text: str) -> str:
        """
        Remove artefacts that the model sometimes prepends or appends.
        Examples:
          - "EXPLANATION: Here are the results..."  → strip prefix
          - "```\nHere are the results\n```"        → strip fences
        """
        text = text.strip()
        # Remove EXPLANATION: prefix
        text = re.sub(r"^EXPLANATION:\s*", "", text, flags=re.IGNORECASE)
        # Remove markdown fences
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        return text.strip()


# ── Module-level helpers ─────────────────────────────────────────────────────

def _format_scalar(value: Any) -> str:
    """Format a scalar DB value for display in a sentence."""
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


# ── Module-level singleton ───────────────────────────────────────────────────
summarizer = ResultSummarizer()
