"""
schema_loader.py — MySQL Schema Introspector
=============================================
Reads the complete structure of a connected database and returns a rich,
structured dictionary that is used by:
  - prompt_builder.py   (to teach the LLM what tables/columns exist)
  - routes.py           (to display the schema in the sidebar)

What we introspect per table:
  - Columns: name, data type, nullable, default value
  - Primary key columns
  - Foreign keys: local column → referenced table.column
  - Approximate row count (via information_schema — fast, non-locking)
  - Table comment (if the DBA wrote one)
  - Indexes (helps the LLM suggest queries that use indexes)

Architectural decision:
  We use raw SQL against information_schema rather than SQLAlchemy's
  reflection API because information_schema gives us richer metadata
  (comments, row counts, FK details) in a single pass, and it's
  universally supported across MySQL 5.7 and 8.x.

Performance note:
  Schema loading happens once per session at connect time, then the result
  is cached in the DatabaseSession object. Subsequent requests use the cache.
  Users can trigger a reload via the refresh endpoint.
"""

from typing import Dict, List, Any
from sqlalchemy import text
from sqlalchemy.engine import Engine

from database import get_connection


# ── Public API ──────────────────────────────────────────────────────────────

def load_schema(engine: Engine, database: str) -> Dict[str, Any]:
    """
    Introspect the entire database schema and return a structured dict.

    Return shape:
    {
        "database": "mydb",
        "tables": {
            "users": {
                "comment": "Registered application users",
                "approximate_row_count": 15000,
                "columns": [
                    {
                        "name": "id",
                        "type": "int",
                        "full_type": "int(11)",
                        "nullable": false,
                        "default": null,
                        "comment": "",
                        "primary_key": true,
                        "auto_increment": true
                    },
                    ...
                ],
                "primary_keys": ["id"],
                "foreign_keys": [
                    {
                        "column": "role_id",
                        "references_table": "roles",
                        "references_column": "id"
                    }
                ],
                "indexes": [
                    {
                        "name": "idx_email",
                        "columns": ["email"],
                        "unique": true
                    }
                ]
            }
        }
    }
    """
    with get_connection(engine) as conn:
        table_names = _get_table_names(conn, database)

        tables: Dict[str, Any] = {}
        for table_name in table_names:
            tables[table_name] = {
                "comment": "",
                "approximate_row_count": 0,
                "columns": [],
                "primary_keys": [],
                "foreign_keys": [],
                "indexes": [],
            }

        if not table_names:
            return {"database": database, "tables": {}}

        # Load all metadata in bulk (one query per metadata type, not per table)
        _load_columns(conn, database, tables)
        _load_table_meta(conn, database, tables)
        _load_foreign_keys(conn, database, tables)
        _load_indexes(conn, database, tables)

    return {"database": database, "tables": tables}


def schema_to_prompt_text(schema: Dict[str, Any]) -> str:
    """
    Convert the structured schema dict to a compact, LLM-friendly text block.

    The format mirrors how a DBA would describe a schema verbally, which
    empirically produces better SQL from language models than JSON.

    Example output:
        Table: users (≈15,000 rows)
        Columns: id INT PK, name VARCHAR(100), email VARCHAR(255) UNIQUE NOT NULL
        Foreign Keys: role_id → roles.id
    """
    lines: List[str] = [f"DATABASE: {schema['database']}\n"]

    for table_name, table in schema["tables"].items():
        row_count = table.get("approximate_row_count", 0)
        comment = f" — {table['comment']}" if table.get("comment") else ""
        lines.append(f"Table: {table_name}{comment} (≈{row_count:,} rows)")

        # Column summary
        col_parts = []
        for col in table["columns"]:
            parts = [col["name"], col["type"].upper()]
            if col.get("primary_key"):
                parts.append("PK")
            if col.get("auto_increment"):
                parts.append("AUTO_INCREMENT")
            if not col.get("nullable"):
                parts.append("NOT NULL")
            if col.get("default") is not None:
                parts.append(f"DEFAULT {col['default']}")
            if col.get("comment"):
                parts.append(f"/* {col['comment']} */")
            col_parts.append(" ".join(parts))
        lines.append("  Columns: " + ", ".join(col_parts))

        # Foreign keys
        if table["foreign_keys"]:
            fk_parts = [
                f"{fk['column']} → {fk['references_table']}.{fk['references_column']}"
                for fk in table["foreign_keys"]
            ]
            lines.append("  Foreign Keys: " + ", ".join(fk_parts))

        # Indexes
        if table["indexes"]:
            idx_parts = []
            for idx in table["indexes"]:
                uniqueness = "UNIQUE " if idx["unique"] else ""
                idx_parts.append(f"{uniqueness}INDEX({', '.join(idx['columns'])})")
            lines.append("  Indexes: " + "; ".join(idx_parts))

        lines.append("")  # blank line between tables

    return "\n".join(lines)


# ── Private helpers ─────────────────────────────────────────────────────────

def _get_table_names(conn, database: str) -> List[str]:
    """Fetch all base table names (excludes views) for the given database."""
    result = conn.execute(
        text("""
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = :db
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """),
        {"db": database},
    )
    return [row[0] for row in result.fetchall()]


def _load_columns(conn, database: str, tables: Dict) -> None:
    """
    Load all column metadata for all tables in one query.
    Populates tables[table_name]['columns'] and tables[table_name]['primary_keys'].
    """
    result = conn.execute(
        text("""
            SELECT
                TABLE_NAME,
                COLUMN_NAME,
                DATA_TYPE,
                COLUMN_TYPE,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                COLUMN_KEY,
                EXTRA,
                COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = :db
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """),
        {"db": database},
    )

    for row in result.fetchall():
        (table_name, col_name, data_type, col_type,
         is_nullable, col_default, col_key, extra, col_comment) = row

        if table_name not in tables:
            continue

        is_pk = col_key == "PRI"
        col = {
            "name": col_name,
            "type": data_type,
            "full_type": col_type,
            "nullable": is_nullable == "YES",
            "default": col_default,
            "comment": col_comment or "",
            "primary_key": is_pk,
            "auto_increment": "auto_increment" in (extra or "").lower(),
        }
        tables[table_name]["columns"].append(col)
        if is_pk:
            tables[table_name]["primary_keys"].append(col_name)


def _load_table_meta(conn, database: str, tables: Dict) -> None:
    """Load table comments and approximate row counts via information_schema.TABLES."""
    result = conn.execute(
        text("""
            SELECT
                TABLE_NAME,
                TABLE_COMMENT,
                TABLE_ROWS
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = :db
              AND TABLE_TYPE = 'BASE TABLE'
        """),
        {"db": database},
    )

    for row in result.fetchall():
        table_name, comment, row_count = row
        if table_name in tables:
            tables[table_name]["comment"] = comment or ""
            tables[table_name]["approximate_row_count"] = int(row_count or 0)


def _load_foreign_keys(conn, database: str, tables: Dict) -> None:
    """
    Load foreign key relationships from information_schema.KEY_COLUMN_USAGE.
    Populates tables[table_name]['foreign_keys'].
    """
    result = conn.execute(
        text("""
            SELECT
                TABLE_NAME,
                COLUMN_NAME,
                REFERENCED_TABLE_NAME,
                REFERENCED_COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = :db
              AND REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY TABLE_NAME, COLUMN_NAME
        """),
        {"db": database},
    )

    for row in result.fetchall():
        table_name, col_name, ref_table, ref_col = row
        if table_name in tables:
            tables[table_name]["foreign_keys"].append({
                "column": col_name,
                "references_table": ref_table,
                "references_column": ref_col,
            })


def _load_indexes(conn, database: str, tables: Dict) -> None:
    """
    Load non-primary indexes from information_schema.STATISTICS.
    Groups multi-column indexes correctly.
    Populates tables[table_name]['indexes'].
    """
    result = conn.execute(
        text("""
            SELECT
                TABLE_NAME,
                INDEX_NAME,
                NON_UNIQUE,
                COLUMN_NAME,
                SEQ_IN_INDEX
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = :db
              AND INDEX_NAME != 'PRIMARY'
            ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
        """),
        {"db": database},
    )

    # Accumulate multi-column indexes before writing to tables
    # Structure: {table_name: {index_name: {non_unique, columns[]}}}
    index_buffer: Dict[str, Dict[str, Any]] = {}

    for row in result.fetchall():
        table_name, idx_name, non_unique, col_name, _ = row
        if table_name not in tables:
            continue
        if table_name not in index_buffer:
            index_buffer[table_name] = {}
        if idx_name not in index_buffer[table_name]:
            index_buffer[table_name][idx_name] = {"unique": not bool(non_unique), "columns": []}
        index_buffer[table_name][idx_name]["columns"].append(col_name)

    # Write fully-assembled indexes into tables
    for table_name, indexes in index_buffer.items():
        for idx_name, idx_data in indexes.items():
            tables[table_name]["indexes"].append({
                "name": idx_name,
                "columns": idx_data["columns"],
                "unique": idx_data["unique"],
            })
