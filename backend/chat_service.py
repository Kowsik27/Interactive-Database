"""
chat_service.py — Chat Pipeline Orchestrator
=============================================
This is the brain of the application.
It wires every service together into a single async pipeline.

Full pipeline (10 steps):
  1.  Fetch conversation history (chat_memory)
  2.  Get database schema       (connection_manager)
  3.  Build the LLM prompt      (prompt_builder)
  4.  Call IBM Granite          (llm)
  5.  Extract SQL from response (utils)
  6.  Validate SQL safety       (sql_validator)
  7.  Execute the query         (query_executor)
  8.  Generate explanation      (summary)
  9.  Save the turn to history  (chat_memory)
  10. Return ChatResponse       (models)

Error handling philosophy:
  Every step can fail independently.
  We catch exceptions at each step and return a ChatResponse with
  a meaningful `error` field rather than a 500 HTTP error.
  This means the frontend always gets a structured response and
  can display a friendly message instead of a crash screen.

Async design:
  The LLM calls are HTTP-bound (I/O waiting, not CPU).
  We use asyncio.to_thread() to run synchronous httpx calls in a
  thread pool so FastAPI remains non-blocking for other requests.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from models import ChatResponse
from connection_manager import DatabaseSession
from chat_memory import chat_memory
from prompt_builder import build_prompt
from llm import granite
from sql_validator import validator
from query_executor import executor
from summary import summarizer
from config import settings

logger = logging.getLogger(__name__)


async def process_chat(
    session: DatabaseSession,
    user_message: str,
) -> ChatResponse:
    """
    Execute the full AI chat pipeline for one user message.

    All errors are caught and surfaced in the ChatResponse.error field
    so the frontend always receives a valid, structured response.
    """
    session_id = session.session_id
    timestamp = datetime.now(timezone.utc).isoformat()

    logger.info(f"[{session_id[:8]}] Processing: {user_message[:80]!r}")

    # ──────────────────────────────────────────────────────────────────────────
    # Step 1-3: Build the prompt
    # ──────────────────────────────────────────────────────────────────────────
    try:
        prompt = build_prompt(
            session_id=session_id,
            user_message=user_message,
            schema=session.schema,
            max_rows=settings.max_rows_returned,
        )
    except Exception as exc:
        logger.exception("Prompt building failed")
        return _error_response(session_id, user_message, timestamp,
                               f"Failed to build AI prompt: {exc}")

    # ──────────────────────────────────────────────────────────────────────────
    # Step 4: Call IBM Granite (async — run in thread pool)
    # ──────────────────────────────────────────────────────────────────────────
    try:
        raw_llm_output = await asyncio.to_thread(granite.generate, prompt)
        logger.debug(f"[{session_id[:8]}] LLM output: {raw_llm_output[:200]!r}")
    except Exception as exc:
        logger.error(f"IBM Granite call failed: {exc}")
        return _error_response(
            session_id, user_message, timestamp,
            f"The AI model could not be reached. Please check your API key and try again. Detail: {exc}"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Step 5-6: Extract and validate SQL
    # ──────────────────────────────────────────────────────────────────────────
    validation = validator.validate(raw_llm_output)

    if not validation.valid:
        logger.warning(f"[{session_id[:8]}] SQL validation failed: {validation.error}")
        # Still save the turn so the user sees the error in context
        explanation = (
            f"I wasn't able to generate a safe query for your question. "
            f"Reason: {validation.error}. "
            f"Please rephrase your question or ask something different."
        )
        _save_turn(session_id, user_message, explanation, sql=None)
        return ChatResponse(
            session_id=session_id,
            user_message=user_message,
            sql=None,
            columns=None,
            rows=None,
            row_count=None,
            execution_time_ms=None,
            explanation=explanation,
            error=validation.error,
            is_safe=False,
            timestamp=timestamp,
        )

    clean_sql = validation.sql
    logger.info(f"[{session_id[:8]}] Validated SQL: {clean_sql[:120]!r}")

    # ──────────────────────────────────────────────────────────────────────────
    # Step 7: Execute the validated query
    # ──────────────────────────────────────────────────────────────────────────
    try:
        query_result = await asyncio.to_thread(executor.execute, session.engine, clean_sql)
    except Exception as exc:
        logger.exception("Query execution raised an unexpected exception")
        return _error_response(session_id, user_message, timestamp,
                               f"Query execution failed unexpectedly: {exc}")

    if not query_result.success:
        explanation = (
            f"The query was generated successfully but encountered a database error: "
            f"{query_result.error}. "
            f"The SQL was: {clean_sql}"
        )
        _save_turn(session_id, user_message, explanation, sql=clean_sql)
        return ChatResponse(
            session_id=session_id,
            user_message=user_message,
            sql=clean_sql,
            columns=[],
            rows=[],
            row_count=0,
            execution_time_ms=query_result.execution_time_ms,
            explanation=explanation,
            error=query_result.error,
            is_safe=True,
            timestamp=timestamp,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Step 8: Generate natural-language explanation (async)
    # ──────────────────────────────────────────────────────────────────────────
    try:
        explanation = await asyncio.to_thread(
            summarizer.summarize,
            user_message,
            clean_sql,
            query_result.columns,
            query_result.rows,
            query_result.execution_time_ms,
        )
    except Exception as exc:
        logger.warning(f"Summary generation failed, using fallback: {exc}")
        explanation = (
            f"The query returned {query_result.row_count:,} row(s). "
            f"Results are shown in the table below."
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Step 9: Persist conversation turn
    # ──────────────────────────────────────────────────────────────────────────
    _save_turn(session_id, user_message, explanation, sql=clean_sql)

    logger.info(
        f"[{session_id[:8]}] Done — {query_result.row_count} rows, "
        f"{query_result.execution_time_ms:.1f}ms"
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Step 10: Return complete response
    # ──────────────────────────────────────────────────────────────────────────
    return ChatResponse(
        session_id=session_id,
        user_message=user_message,
        sql=clean_sql,
        columns=query_result.columns,
        rows=query_result.rows,
        row_count=query_result.row_count,
        execution_time_ms=query_result.execution_time_ms,
        explanation=explanation,
        error=None,
        is_safe=True,
        timestamp=timestamp,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _save_turn(
    session_id: str,
    user_message: str,
    assistant_message: str,
    sql: Optional[str],
) -> None:
    """Save a conversation turn, catching and logging any storage errors."""
    try:
        chat_memory.save_turn(
            session_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            sql=sql,
        )
    except Exception as exc:
        logger.error(f"Failed to save conversation turn: {exc}")


def _error_response(
    session_id: str,
    user_message: str,
    timestamp: str,
    error_message: str,
) -> ChatResponse:
    """Build a consistent error ChatResponse."""
    return ChatResponse(
        session_id=session_id,
        user_message=user_message,
        sql=None,
        columns=None,
        rows=None,
        row_count=None,
        execution_time_ms=None,
        explanation=error_message,
        error=error_message,
        is_safe=None,
        timestamp=timestamp,
    )
