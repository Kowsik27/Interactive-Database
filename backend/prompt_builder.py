"""
prompt_builder.py — LLM Prompt Engineering
============================================
Constructs the complete prompt sent to IBM Granite for every chat turn.

This is one of the most important files in the project.
A poorly engineered prompt produces bad SQL. A well-engineered prompt
produces accurate, safe, context-aware SQL reliably.

Prompt structure (system + user turns):
────────────────────────────────────────
[SYSTEM]
  Role definition
  Rules (SELECT only, no mutations)
  Response format instructions

[DATABASE CONTEXT]
  Full schema (tables, columns, types, PKs, FKs)

[CONVERSATION HISTORY]
  Last N user/assistant turns (sliding window)

[CURRENT QUESTION]
  User's latest message

[RESPONSE INSTRUCTION]
  Exact output format the model must follow
────────────────────────────────────────

Design decisions:
1. Schema first:   The model sees the full schema before the question,
                   so it can plan joins and understand relationships.
2. Few-shot style: The conversation history acts as implicit few-shot
                   examples, improving SQL quality for follow-ups.
3. Hard rules:     Explicit "NEVER generate INSERT/UPDATE/DELETE" in the
                   system prompt adds a first line of defence before
                   our sql_validator.py safety gate.
4. Format anchors: We instruct the model to use ```sql fences and a
                   specific EXPLANATION: tag so we can parse the output
                   reliably without brittle regex.
"""

from typing import Optional
from schema_loader import schema_to_prompt_text
from chat_memory import chat_memory


# ── Prompt constants ─────────────────────────────────────────────────────────

# Granite 3 uses the <|system|> / <|user|> / <|assistant|> chat template.
# This produces significantly better SQL than raw-text prompts.
SYSTEM_PROMPT = """\
<|system|>
You are DBChat AI, an expert database assistant. Your only job is to translate natural language questions into safe MySQL SELECT queries and explain the results clearly.

STRICT RULES:
1. ONLY write SELECT statements. NEVER write INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE, or any statement that modifies data.
2. Always write syntactically correct MySQL 8.x SQL.
3. Use table aliases when joining multiple tables.
4. Always qualify column names with their table alias in JOINs.
5. Add LIMIT {max_rows} when the result could be large and the user did not specify a limit.
6. If the question cannot be answered from the schema provided, say so — never guess table or column names.
7. Use MySQL date functions: NOW(), CURDATE(), DATE_SUB(), YEAR(), MONTH().

OUTPUT FORMAT — you must follow this exactly, no exceptions:
```sql
SELECT ...
```
EXPLANATION: One concise paragraph in plain English explaining what the query does and what the results mean. Address the user's question directly. No bullet points.
<|assistant|>"""

NO_HISTORY_NOTE = "This is the first message in the conversation."


# ── Builder ──────────────────────────────────────────────────────────────────

def build_prompt(
    session_id: str,
    user_message: str,
    schema: dict,
    max_rows: int = 500,
) -> str:
    """
    Assemble the complete prompt string to send to Granite.

    Args:
        session_id:   Used to fetch conversation history from chat_memory.
        user_message: The user's current natural language question.
        schema:       The DatabaseSession.schema dict.
        max_rows:     Row limit to inject into the system rules.

    Returns:
        A single formatted string ready for llm.generate().
    """
    # ── 1. Build the system instructions (with max_rows injected) ────────────
    system_section = SYSTEM_PROMPT.format(max_rows=max_rows)

    # ── 2. Schema ────────────────────────────────────────────────────────────
    schema_text = schema_to_prompt_text(schema)

    # ── 3. Conversation history ──────────────────────────────────────────────
    history_text = chat_memory.history_to_prompt_text(session_id)
    history_note = (
        f"CONVERSATION HISTORY ({len(chat_memory.get_window(session_id))} recent turns):\n{history_text}"
        if history_text else
        f"CONVERSATION HISTORY:\n{NO_HISTORY_NOTE}"
    )

    # ── 4. Assemble using Granite 3 chat template ────────────────────────────
    # Format: <|system|>...<|user|>...<|assistant|>
    # The SYSTEM_PROMPT already contains <|system|> and ends with <|assistant|>
    # We inject schema + history + question inside the <|user|> turn.
    user_content = (
        f"DATABASE SCHEMA:\n{schema_text}\n\n"
        f"{history_note}\n\n"
        f"CURRENT QUESTION: {user_message}\n\n"
        f"Write the SQL query and explanation now."
    )

    prompt = f"{system_section}\n<|user|>\n{user_content}\n<|assistant|>"

    return prompt


def build_summary_prompt(
    user_message: str,
    sql: str,
    columns: list,
    rows: list,
    row_count: int,
    execution_time_ms: float,
) -> str:
    """
    Build a follow-up prompt that asks Granite to summarise query results
    in plain English after the SQL has already been executed.

    This is called when the first pass generates SQL + runs it,
    and we want a natural language narrative to go with the table.

    The result preview is capped at 20 rows to avoid token explosion.
    """
    preview_rows = rows[:20]
    rows_text = _format_rows_for_prompt(columns, preview_rows)

    truncation_note = ""
    if row_count > 20:
        truncation_note = f"\n(Showing first 20 of {row_count:,} rows)"

    prompt = f"""\
A user asked: "{user_message}"

The following SQL query was executed:
```sql
{sql}
```

Execution time: {execution_time_ms:.1f}ms
Total rows returned: {row_count:,}

Results:
{rows_text}{truncation_note}

Write a clear, concise explanation of these results in plain English.
Address the user's original question directly.
If there are 0 rows, explain what that means.
Be specific about numbers, names, and values from the results.
Write in 1–3 sentences maximum. No bullet points. No markdown.
"""
    return prompt


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_rows_for_prompt(columns: list, rows: list) -> str:
    """Format a result set as a compact ASCII table for the prompt."""
    if not rows:
        return "(no rows returned)"

    # Header
    col_widths = [max(len(str(c)), max((len(str(r[i])) for r in rows), default=0)) for i, c in enumerate(columns)]
    header = " | ".join(str(c).ljust(w) for c, w in zip(columns, col_widths))
    separator = "-+-".join("-" * w for w in col_widths)
    data_rows = [
        " | ".join(str(v).ljust(w) for v, w in zip(row, col_widths))
        for row in rows
    ]
    return "\n".join([header, separator] + data_rows)
