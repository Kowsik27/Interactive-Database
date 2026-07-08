"""
routes.py — FastAPI Route Handlers
====================================
All HTTP endpoints live here.  Each handler is intentionally thin:
  1. Parse + validate the request  (Pydantic does this automatically)
  2. Delegate to the service layer
  3. Return a typed response model

No business logic lives in route handlers.  No SQL.  No LLM calls.
This keeps routes easy to read, easy to test, and easy to swap.

Endpoint map:
  POST   /api/connect              — Connect to a MySQL database
  DELETE /api/disconnect/{id}      — Disconnect and clean up
  GET    /api/schema/{id}          — Get loaded schema
  POST   /api/schema/{id}/refresh  — Reload schema from DB
  POST   /api/chat                 — Send a message, get AI response
  GET    /api/history/{id}         — Get conversation history
  DELETE /api/history/{id}         — Clear conversation history
  GET    /api/sessions             — List all active sessions
  GET    /api/health               — Health check
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

import io
import csv
import json

from models import (
    ConnectRequest, ConnectResponse,
    DisconnectResponse,
    SchemaResponse, TableInfo, ColumnInfo, ForeignKeyInfo, IndexInfo,
    ChatRequest, ChatResponse,
    HistoryResponse, MessagePair,
    SessionsResponse, SessionSummary,
    HealthResponse,
    ErrorResponse,
)
from connection_manager import connection_manager
from schema_loader import load_schema
from chat_memory import chat_memory
from chat_service import process_chat

router = APIRouter(prefix="/api", tags=["db-chat"])


# ── Helper ───────────────────────────────────────────────────────────────────

def _get_session_or_404(session_id: str):
    """Return session or raise a clean 404."""
    try:
        return connection_manager.require_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Connection Endpoints ─────────────────────────────────────────────────────

@router.post(
    "/connect",
    response_model=ConnectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect to a MySQL database",
    description=(
        "Tests the connection, creates a session, loads the full schema, "
        "and returns a session_id for all subsequent requests."
    ),
)
async def connect(request: ConnectRequest):
    """
    Connection lifecycle:
      1. Create engine + verify connectivity  (connection_manager)
      2. Load full schema                     (schema_loader)
      3. Attach schema to session             (connection_manager)
      4. Return session summary
    """
    try:
        session_id, session = connection_manager.create_session(
            host=request.host,
            port=request.port,
            username=request.username,
            password=request.password,
            database=request.database,
        )
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Load the schema (can be slow on large databases — runs once per session)
    try:
        schema = load_schema(session.engine, request.database)
        connection_manager.update_schema(session_id, schema)
    except Exception as exc:
        # Schema loading failed — still connected, but schema will be empty
        schema = {"database": request.database, "tables": {}}
        connection_manager.update_schema(session_id, schema)

    # Re-fetch to get the updated session with schema
    session = connection_manager.require_session(session_id)

    return ConnectResponse(
        session_id=session_id,
        database=session.database,
        host=session.host,
        port=session.port,
        server_version=session.server_version,
        tables=list(session.schema.get("tables", {}).keys()),
        table_count=len(session.schema.get("tables", {})),
        connected_at=session.connected_at.isoformat(),
    )


@router.delete(
    "/disconnect/{session_id}",
    response_model=DisconnectResponse,
    summary="Disconnect a session",
)
async def disconnect(session_id: str):
    removed = connection_manager.remove_session(session_id)
    chat_memory.clear_history(session_id)
    if removed:
        return DisconnectResponse(status="disconnected", message="Session closed successfully")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Session '{session_id}' not found",
    )


# ── Schema Endpoints ─────────────────────────────────────────────────────────

@router.get(
    "/schema/{session_id}",
    response_model=SchemaResponse,
    summary="Get the database schema for a session",
)
async def get_schema(session_id: str):
    session = _get_session_or_404(session_id)

    # Convert raw schema dicts to typed Pydantic models
    tables = {}
    for table_name, table_data in session.schema.get("tables", {}).items():
        tables[table_name] = TableInfo(
            comment=table_data.get("comment", ""),
            approximate_row_count=table_data.get("approximate_row_count", 0),
            columns=[ColumnInfo(**c) for c in table_data.get("columns", [])],
            primary_keys=table_data.get("primary_keys", []),
            foreign_keys=[ForeignKeyInfo(**fk) for fk in table_data.get("foreign_keys", [])],
            indexes=[IndexInfo(**idx) for idx in table_data.get("indexes", [])],
        )

    return SchemaResponse(
        session_id=session_id,
        database=session.database,
        tables=tables,
    )


@router.post(
    "/schema/{session_id}/refresh",
    response_model=SchemaResponse,
    summary="Reload the schema from the database",
    description="Forces a fresh introspection. Use after running migrations.",
)
async def refresh_schema(session_id: str):
    session = _get_session_or_404(session_id)

    try:
        schema = load_schema(session.engine, session.database)
        connection_manager.update_schema(session_id, schema)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Schema reload failed: {exc}",
        )

    # Return refreshed schema (reuse the GET handler logic)
    return await get_schema(session_id)


# ── Chat Endpoints ────────────────────────────────────────────────────────────

@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a natural language message",
    description=(
        "The full AI pipeline: prompt → LLM → SQL → validate → execute → summarise. "
        "Conversation history is maintained automatically."
    ),
)
async def chat(request: ChatRequest):
    session = _get_session_or_404(request.session_id)

    try:
        response = await process_chat(
            session=session,
            user_message=request.message,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat processing failed: {exc}",
        )

    return response


@router.get(
    "/history/{session_id}",
    response_model=HistoryResponse,
    summary="Get conversation history for a session",
)
async def get_history(session_id: str):
    session = _get_session_or_404(session_id)
    messages = chat_memory.get_history(session_id)

    return HistoryResponse(
        session_id=session_id,
        database=session.database,
        messages=[MessagePair(**m) for m in messages],
        total_turns=len(messages),
    )


@router.delete(
    "/history/{session_id}",
    summary="Clear conversation history for a session",
)
async def clear_history(session_id: str):
    _get_session_or_404(session_id)
    chat_memory.clear_history(session_id)
    return {"status": "cleared", "message": "Conversation history cleared"}


# ── Export Endpoint ────────────────────────────────────────────────────────────

@router.post(
    "/export/csv",
    summary="Export query results as a CSV file",
)
async def export_csv(payload: dict):
    """
    Accepts {columns: [...], rows: [[...], ...], filename: "..."} and returns
    a downloadable CSV file.  Called by the frontend Export button.
    """
    columns = payload.get("columns", [])
    rows = payload.get("rows", [])
    filename = payload.get("filename", "query_results") + ".csv"

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Sessions Endpoints ─────────────────────────────────────────────────────────

@router.get(
    "/sessions",
    response_model=SessionsResponse,
    summary="List all active database sessions",
)
async def list_sessions():
    sessions_raw = connection_manager.list_sessions()
    sessions = [SessionSummary(**s) for s in sessions_raw]
    return SessionsResponse(sessions=sessions, total=len(sessions))


# ── Health Endpoint ────────────────────────────────────────────────────────────

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application health check",
)
async def health():
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        active_sessions=len(connection_manager),
        message="DB Chat Assistant is running",
    )
