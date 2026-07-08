"""
test_full_pipeline.py — End-to-end AI pipeline test (no DB needed)
Run: python test_full_pipeline.py
"""
import sys, os
sys.path.insert(0, '.')

print("=" * 58)
print("  DBChat AI — Full Pipeline Test")
print("=" * 58)

# Fake schema for testing (no real DB needed)
FAKE_SCHEMA = {
    "database": "testdb",
    "tables": {
        "employees": {
            "comment": "Company employees",
            "approximate_row_count": 150,
            "columns": [
                {"name": "id",         "type": "int",          "full_type": "int(11)",       "nullable": False, "default": None, "comment": "", "primary_key": True,  "auto_increment": True},
                {"name": "name",       "type": "varchar",      "full_type": "varchar(100)",  "nullable": False, "default": None, "comment": "", "primary_key": False, "auto_increment": False},
                {"name": "department", "type": "varchar",      "full_type": "varchar(50)",   "nullable": True,  "default": None, "comment": "", "primary_key": False, "auto_increment": False},
                {"name": "salary",     "type": "decimal",      "full_type": "decimal(10,2)", "nullable": True,  "default": None, "comment": "", "primary_key": False, "auto_increment": False},
                {"name": "hire_date",  "type": "date",         "full_type": "date",          "nullable": True,  "default": None, "comment": "", "primary_key": False, "auto_increment": False},
            ],
            "primary_keys": ["id"],
            "foreign_keys": [],
            "indexes": [],
        }
    }
}

# Step 1: Build prompt
print("\n[1] Building prompt...")
from prompt_builder import build_prompt
prompt = build_prompt(
    session_id="test-session",
    user_message="Show the top 5 highest paid employees",
    schema=FAKE_SCHEMA,
    max_rows=500,
)
print(f"    Prompt length: {len(prompt)} chars")
print(f"    First 120 chars: {repr(prompt[:120])}")

# Step 2: Call Granite
print("\n[2] Calling IBM Granite...")
from llm import granite
try:
    response = granite.generate(prompt)
    print(f"    Response length: {len(response)} chars")
    print(f"    Raw response:\n{'─'*50}")
    print(response[:600])
    print('─'*50)
except Exception as e:
    print(f"    [FAIL] {e}")
    sys.exit(1)

# Step 3: Validate SQL
print("\n[3] Validating generated SQL...")
from sql_validator import validator
result = validator.validate(response)
if result.valid:
    print(f"    [OK] SQL is safe: {result.sql[:100]}")
else:
    print(f"    [FAIL] Validation failed: {result.error}")
    print(f"    Raw response was: {response[:200]}")
    sys.exit(1)

# Step 4: Check explanation
print("\n[4] Checking explanation extraction...")
from utils import extract_sql_from_text
import re
expl_match = re.search(r'EXPLANATION:\s*(.+)', response, re.DOTALL | re.IGNORECASE)
if expl_match:
    explanation = expl_match.group(1).strip()[:200]
    print(f"    [OK] Explanation: {explanation[:100]}...")
else:
    print(f"    [WARN] No EXPLANATION: tag found — summary.py will handle this")

print()
print("=" * 58)
print("  FULL PIPELINE TEST PASSED")
print("  The AI is generating valid SQL correctly.")
print("  Go to http://localhost:3000 and start chatting!")
print("=" * 58)
