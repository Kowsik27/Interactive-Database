"""
models.py — Pydantic Request & Response Schemas
================================================
Defines the complete data contract for all API endpoints.

Why Pydantic?
  - Automatic input validation with clear error messages
  - Self-documenting OpenAPI/Swagger spec generated automatically
  - Type safety bridging the JSON wire format and Python objects
  - Field-level descriptions appear in the Swagger UI

Naming convention:
  - *Request  → incoming payload from frontend
  - *Response → outgoing payload to frontend
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ── Connection ──────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    """Credentials supplied by the user on the connection screen."""

    host: str = Field(..., min_length=1, max_length=255, examples=["localhost"])
    port: int = Field(default=3306, ge=1, le=65535, examples=[3306])
    username: str = Field(..., min_length=1, max_length=64, examples=["root"])
    password: str = Field(..., examples=["secret"])          # empty string is valid
    database: str = Field(..., min_length=1, max_length=64, examples=["mydb"])

    @field_validator("host")
    @classmethod
    def strip_host_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("database")
    @classmethod
    def strip_database_whitespace(cls, v: str) -> str:
        return v.strip()


class ConnectResponse(BaseModel):
    """Returned after a successful database connection."""

    session_id: str = Field(..., description="UUID that identifies this session")
    status: str = Field(default="connected")
    database: str
    host: str
    port: int
    server_version: str
    tables: List[str] = Field(description="All table names in the database")
    table_count: int
    connected_at: str
    message: str = Field(default="Connected successfully")


class DisconnectResponse(BaseModel):
    status: str
    message: str


# ── Schema ──────────────────────────────────────────────────────────────────

class ColumnInfo(BaseModel):
    name: str
    type: str
    full_type: str
    nullable: bool
    default: Optional[Any] = None
    comment: str = ""
    primary_key: bool = False
    auto_increment: bool = False


class ForeignKeyInfo(BaseModel):
    column: str
    references_table: str
    references_column: str


class IndexInfo(BaseModel):
    name: str
    columns: List[str]
    unique: bool


class TableInfo(BaseModel):
    comment: str = ""
    approximate_row_count: int = 0
    columns: List[ColumnInfo]
    primary_keys: List[str]
    foreign_keys: List[ForeignKeyInfo]
    indexes: List[IndexInfo]


class SchemaResponse(BaseModel):
    session_id: str
    database: str
    tables: Dict[str, TableInfo]


# ── Chat ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """A single user message turn in the conversation."""

    session_id: str = Field(..., description="Session UUID from /api/connect")
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language question about the database",
        examples=["Show all customers who placed orders last month"],
    )

    @field_validator("message")
    @classmethod
    def strip_message(cls, v: str) -> str:
        return v.strip()


class ChatResponse(BaseModel):
    """
    Full response from one chat turn.
    All fields are always present; use null to indicate absence of data.
    """

    session_id: str
    user_message: str
    sql: Optional[str] = Field(None, description="The generated SELECT statement")
    columns: Optional[List[str]] = Field(None, description="Result column names")
    rows: Optional[List[List[Any]]] = Field(None, description="Result rows")
    row_count: Optional[int] = None
    execution_time_ms: Optional[float] = None
    explanation: str = Field(..., description="Plain-English answer from the AI")
    error: Optional[str] = Field(None, description="Error message if something went wrong")
    is_safe: Optional[bool] = Field(None, description="Whether the SQL passed safety validation")
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO-8601 UTC timestamp of this response",
    )


# ── Chat History ────────────────────────────────────────────────────────────

class MessagePair(BaseModel):
    """A single user/assistant exchange stored in conversation memory."""

    user: str
    assistant: str
    sql: Optional[str] = None
    timestamp: str


class HistoryResponse(BaseModel):
    session_id: str
    database: str
    messages: List[MessagePair]
    total_turns: int


# ── Sessions ────────────────────────────────────────────────────────────────

class SessionSummary(BaseModel):
    session_id: str
    host: str
    port: int
    database: str
    server_version: str
    connected_at: str
    table_count: int
    tables: List[str]


class SessionsResponse(BaseModel):
    sessions: List[SessionSummary]
    total: int


# ── Health ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    active_sessions: int
    message: str


# ── Error ───────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error envelope for all 4xx/5xx responses."""

    error: str
    detail: Optional[str] = None
    status_code: int
