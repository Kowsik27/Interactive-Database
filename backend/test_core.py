import sys
sys.path.insert(0, '.')

print('Testing all module imports...')
from utils import Timer, extract_sql_from_text, normalise_sql, rows_to_lists, format_row_count
print('  [OK] utils')
from config import settings
print('  [OK] config')
from sql_validator import validator
print('  [OK] sql_validator')
from query_executor import executor
print('  [OK] query_executor')
from chat_memory import chat_memory
print('  [OK] chat_memory')
from schema_loader import load_schema, schema_to_prompt_text
print('  [OK] schema_loader')
from models import ConnectRequest, ChatRequest, ChatResponse
print('  [OK] models')
from prompt_builder import build_prompt, build_summary_prompt
print('  [OK] prompt_builder')
from summary import summarizer
print('  [OK] summary')
from llm import GraniteClient, IAMTokenManager
print('  [OK] llm')

print()
print('=== Unit Tests ===')

# --- sql_validator ---
r1 = validator.validate('SELECT * FROM users')
assert r1.valid, f'Expected valid: {r1.error}'
assert r1.sql == 'SELECT * FROM users'
print('  [PASS] valid SELECT passes')

r2 = validator.validate('DROP TABLE users')
assert not r2.valid
print('  [PASS] DROP blocked')

r3 = validator.validate('DELETE FROM users')
assert not r3.valid
print('  [PASS] DELETE blocked')

fenced = "```sql\nSELECT id, name FROM employees\n```\nEXPLANATION: shows all employees"
r4 = validator.validate(fenced)
assert r4.valid, f'Expected valid: {r4.error}'
assert 'SELECT' in r4.sql.upper()
print('  [PASS] SQL extraction from fenced block')

cte = 'WITH cte AS (SELECT * FROM t) SELECT * FROM cte'
r5 = validator.validate(cte)
assert r5.valid, f'Expected valid: {r5.error}'
print('  [PASS] WITH...SELECT (CTE) passes')

# --- utils ---
sql = extract_sql_from_text("```sql\nSELECT 1\n```")
assert sql == 'SELECT 1', f'Got: {sql!r}'
print('  [PASS] extract_sql_from_text fenced block')

plain = extract_sql_from_text("Some text SELECT id FROM users WHERE x=1")
assert plain is not None and 'SELECT' in plain.upper()
print('  [PASS] extract_sql_from_text plain text')

assert normalise_sql('  SELECT   *  FROM  t ; ') == 'SELECT * FROM t'
print('  [PASS] normalise_sql strips and collapses whitespace')

assert format_row_count(0) == 'no rows'
assert format_row_count(1) == '1 row'
assert format_row_count(1500) == '1,500 rows'
print('  [PASS] format_row_count')

# --- rows_to_lists ---
import decimal, datetime
raw = [(1, 'Alice', decimal.Decimal('99.50'), datetime.date(2024, 1, 1))]
result = rows_to_lists(raw)
assert result == [[1, 'Alice', 99.50, '2024-01-01']], f'Got: {result}'
print('  [PASS] rows_to_lists coerces Decimal and date')

# --- chat_memory ---
chat_memory.save_turn('sess1', 'hello', 'world', sql='SELECT 1')
h = chat_memory.get_history('sess1')
assert len(h) == 1
assert h[0]['user'] == 'hello'
assert h[0]['sql'] == 'SELECT 1'
chat_memory.clear_history('sess1')
assert chat_memory.get_turn_count('sess1') == 0
print('  [PASS] chat_memory save/retrieve/clear')

# --- Timer ---
import time
with Timer() as t:
    time.sleep(0.05)
assert t.elapsed_ms >= 40, f'Timer too fast: {t.elapsed_ms}'
print('  [PASS] Timer measures elapsed ms')

# --- QueryExecutor limit injection ---
assert executor._has_top_level_limit('SELECT * FROM t LIMIT 10') == True
assert executor._has_top_level_limit('SELECT * FROM t') == False
assert executor._has_top_level_limit('SELECT * FROM (SELECT * FROM t LIMIT 5) s') == False
print('  [PASS] QueryExecutor top-level LIMIT detection')

print()
print('All tests PASSED.')
