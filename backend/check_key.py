"""
Deep API key checker — run: python check_key.py
"""
import re
from pathlib import Path

config = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    config[k.strip()] = v.strip().strip('"').strip("'").strip()

api_key = config.get("WATSONX_API_KEY", "")
proj_id = config.get("WATSONX_PROJECT_ID", "")
url     = config.get("WATSONX_URL", "")

print("=" * 55)
print("  IBM Credentials Deep Check")
print("=" * 55)

# ── API Key ────────────────────────────────────────────────
print(f"\nWATSONX_API_KEY")
print(f"  Length   : {len(api_key)} chars")
print(f"  Preview  : {api_key[:4]}...{api_key[-4:]}")

uuid_pattern = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE
)

if uuid_pattern.match(api_key):
    print("  STATUS   : [FAIL] This looks like a UUID (Project ID format),")
    print("             NOT an IBM API key.")
    print("             You probably pasted the Project ID here by mistake.")
    print()
    print("  IBM API keys look like this (44 chars, no hyphens at start):")
    print("    AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_AbCdEf")
elif len(api_key) == 44 and re.match(r"^[A-Za-z0-9_\-]+$", api_key):
    print("  STATUS   : [OK]  Correct format (44 chars, alphanumeric)")
elif len(api_key) < 30:
    print("  STATUS   : [FAIL] Too short. IBM API keys are 44 characters.")
elif " " in api_key:
    print("  STATUS   : [FAIL] Contains a space. Copy the key again carefully.")
else:
    print(f"  STATUS   : [WARN] Unexpected length ({len(api_key)}). Expected 44.")
    print("             Try creating a fresh API key at:")
    print("             https://cloud.ibm.com/iam/apikeys")

# ── Project ID ────────────────────────────────────────────
print(f"\nWATSONX_PROJECT_ID")
print(f"  Value    : {proj_id}")
print(f"  Length   : {len(proj_id)} chars")
if uuid_pattern.match(proj_id):
    print("  STATUS   : [OK]  Correct UUID format")
else:
    print("  STATUS   : [FAIL] Should be a UUID like:")
    print("             a1b2c3d4-1234-5678-abcd-ef0123456789")

# ── URL / Region ────────────────────────────────────────────
print(f"\nWATSONX_URL")
print(f"  Value    : {url}")
if "eu-de" in url:
    print("  STATUS   : [OK]  Frankfurt region (correct for your account)")
elif "us-south" in url:
    print("  STATUS   : [WARN] US-South — but your IBM account is Frankfurt.")
    print("             Change to: https://eu-de.ml.cloud.ibm.com")
else:
    print("  STATUS   : [WARN] Verify this is the correct region.")

print("\n" + "=" * 55)
print("  HOW TO GET A REAL API KEY:")
print("  1. Go to https://cloud.ibm.com/iam/apikeys")
print("  2. Click 'Create an IBM Cloud API key'")
print("  3. Name it: dbchat")
print("  4. Click Create")
print("  5. IMMEDIATELY click Copy")
print("     (44 chars, contains letters + numbers + _ )")
print("  6. Paste it in .env as: WATSONX_API_KEY=<paste>")
print("=" * 55)
