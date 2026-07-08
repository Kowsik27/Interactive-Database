"""
Diagnose .env configuration issues.
Run: python diagnose_env.py
"""
from pathlib import Path

env_path = Path(".env")

print("=" * 60)
print("  DBChat AI — .env Diagnostics")
print("=" * 60)
print()

if not env_path.exists():
    print("CRITICAL: backend/.env does NOT exist!")
    print()
    print("Fix: Create the file manually:")
    print("  1. Open Notepad")
    print("  2. Paste your credentials (see README.md)")
    print("  3. Save as: backend\\.env")
    print("     (make sure it is .env not .env.txt)")
    exit(1)

print(f"Found: {env_path.absolute()}")
print()

issues = []
config = {}

for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        continue
    key, _, val = line.partition("=")
    key = key.strip()
    val = val.strip().strip('"').strip("'").strip()
    config[key] = val

# ── Check API Key ─────────────────────────────────────────────
api_key = config.get("WATSONX_API_KEY", "")
print(f"WATSONX_API_KEY:")
print(f"  Value    : {api_key[:4]}{'*' * max(0, len(api_key)-8)}{api_key[-4:] if len(api_key) > 8 else ''}")
print(f"  Length   : {len(api_key)} characters")

PLACEHOLDERS = {
    "your_ibm_api_key_here",
    "paste_your_api_key_here",
    "paste_your_real_key_here",
    "your_api_key",
    "",
}

if api_key.lower() in PLACEHOLDERS:
    issues.append("WATSONX_API_KEY is still a placeholder -- paste your real IBM Cloud API key")
    print("  STATUS   : [FAIL] PLACEHOLDER -- not a real key")
elif len(api_key) < 30:
    issues.append(f"WATSONX_API_KEY looks too short ({len(api_key)} chars) -- IBM keys are ~44 characters")
    print(f"  STATUS   : [WARN] TOO SHORT ({len(api_key)} chars) -- IBM keys are ~44 characters")
elif " " in api_key:
    issues.append("WATSONX_API_KEY contains spaces -- copy the key again without extra spaces")
    print("  STATUS   : [FAIL] CONTAINS SPACES -- copy the key again carefully")
else:
    print("  STATUS   : [OK]  Format looks correct")

print()

# ── Check Project ID ──────────────────────────────────────────
proj_id = config.get("WATSONX_PROJECT_ID", "")
print(f"WATSONX_PROJECT_ID:")
print(f"  Value    : {proj_id}")

PROJ_PLACEHOLDERS = {
    "your_project_id_here",
    "paste_your_project_id_here",
    "",
}

if proj_id.lower() in PROJ_PLACEHOLDERS:
    issues.append("WATSONX_PROJECT_ID is still a placeholder")
    print("  STATUS   : [FAIL] PLACEHOLDER -- paste your real Project ID")
elif len(proj_id) < 30:
    issues.append("WATSONX_PROJECT_ID looks too short -- should be UUID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    print("  STATUS   : [WARN] TOO SHORT -- should be UUID format")
else:
    print("  STATUS   : [OK]  Format looks correct")

print()

# ── Check Region URL ──────────────────────────────────────────
url = config.get("WATSONX_URL", "")
print(f"WATSONX_URL:")
print(f"  Value    : {url}")

REGION_URLS = {
    "https://us-south.ml.cloud.ibm.com": "US South (Dallas)",
    "https://eu-de.ml.cloud.ibm.com":    "Europe (Frankfurt) ← your account",
    "https://eu-gb.ml.cloud.ibm.com":    "Europe (London)",
    "https://jp-tok.ml.cloud.ibm.com":   "Japan (Tokyo)",
    "https://au-syd.ml.cloud.ibm.com":   "Australia (Sydney)",
}

if url in REGION_URLS:
    print(f"  Region   : {REGION_URLS[url]}")
    if "us-south" in url:
        issues.append(
            "WATSONX_URL is set to US-South but your IBM account is in Frankfurt (EU-DE). "
            "Change to: https://eu-de.ml.cloud.ibm.com"
        )
        print("  STATUS   : [WARN] WRONG REGION -- your account is in Frankfurt (EU-DE)")
        print("             Change to: https://eu-de.ml.cloud.ibm.com")
    else:
        print("  STATUS   : [OK]  URL looks correct")
else:
    print("  STATUS   : [WARN] Unrecognised URL -- double-check")

print()

# ── Summary ───────────────────────────────────────────────────
print("=" * 60)
if issues:
    print(f"  FOUND {len(issues)} ISSUE(S) TO FIX:")
    print()
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
    print()
    print("  After fixing, save .env — uvicorn will auto-reload.")
else:
    print("  [ALL OK] Configuration looks correct!")
    print("  If the error persists, the API key may not yet")
    print("  be activated — wait 30 seconds and try again.")
print("=" * 60)
