"""
verify_watsonx.py — Live end-to-end IBM watsonx.ai verifier
Run: python verify_watsonx.py

Tests:
  1. IAM token exchange (validates API key)
  2. Project existence in eu-de region
  3. Project existence in us-south region (auto-detect correct region)
  4. A minimal Granite generation call
"""
import httpx
import re
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
config = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    config[k.strip()] = v.strip().strip('"').strip("'").strip()

API_KEY    = config.get("WATSONX_API_KEY", "")
PROJECT_ID = config.get("WATSONX_PROJECT_ID", "")
URL        = config.get("WATSONX_URL", "").rstrip("/")
MODEL_ID   = config.get("GRANITE_MODEL_ID", "ibm/granite-13b-chat-v2")

REGIONS = {
    "eu-de (Frankfurt)" : "https://eu-de.ml.cloud.ibm.com",
    "us-south (Dallas)" : "https://us-south.ml.cloud.ibm.com",
    "eu-gb (London)"    : "https://eu-gb.ml.cloud.ibm.com",
    "jp-tok (Tokyo)"    : "https://jp-tok.ml.cloud.ibm.com",
    "au-syd (Sydney)"   : "https://au-syd.ml.cloud.ibm.com",
    "ca-tor (Toronto)"  : "https://ca-tor.ml.cloud.ibm.com",
}

print("=" * 58)
print("  IBM watsonx.ai Live Verifier")
print("=" * 58)
print(f"  API Key    : {API_KEY[:4]}...{API_KEY[-4:]} ({len(API_KEY)} chars)")
print(f"  Project ID : {PROJECT_ID}")
print(f"  URL        : {URL}")
print(f"  Model      : {MODEL_ID}")
print("=" * 58)

# ── Step 1: Get IAM token ──────────────────────────────────────────────────────
print("\n[1] Getting IBM IAM token...")
try:
    r = httpx.post(
        "https://iam.cloud.ibm.com/identity/token",
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": API_KEY},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"    [OK] IAM token obtained ({len(token)} chars)")
except Exception as e:
    print(f"    [FAIL] {e}")
    print("\n    Your API key is invalid. Create a new one at:")
    print("    https://cloud.ibm.com/iam/apikeys")
    exit(1)

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ── Step 2: Find which region has the project ──────────────────────────────────
print(f"\n[2] Searching for project {PROJECT_ID} across all regions...")

found_region_url = None
found_region_name = None

# First look up the project via DataPlatform API (works regardless of region)
try:
    dp = httpx.get(
        f"https://api.dataplatform.cloud.ibm.com/v2/projects/{PROJECT_ID}",
        headers=headers,
        timeout=10,
    )
    if dp.status_code == 200:
        proj_name = dp.json().get("entity", {}).get("name", "unnamed")
        print(f"    Found via DataPlatform: '{proj_name}'")
    else:
        print(f"    DataPlatform lookup: {dp.status_code}")
except Exception:
    pass

# Now test inference directly against each region
for region_name, region_url in REGIONS.items():
    try:
        test_payload = {
            "model_id": MODEL_ID,
            "project_id": PROJECT_ID,
            "input": "Say: OK",
            "parameters": {"max_new_tokens": 5, "temperature": 0.0},
        }
        r = httpx.post(
            f"{region_url}/ml/v1/text/generation?version=2023-05-29",
            json=test_payload, headers=headers, timeout=15,
        )
        if r.status_code == 200:
            print(f"    [FOUND + WORKING] {region_name}")
            found_region_url  = region_url
            found_region_name = region_name
            break
        elif r.status_code == 404:
            print(f"    [NOT FOUND] {region_name}")
        else:
            print(f"    [ERROR {r.status_code}] {region_name}: {r.text[:80]}")
    except Exception as e:
        print(f"    [TIMEOUT] {region_name}: {e}")

if not found_region_url:
    print()
    print("    [FAIL] Project not found in any region.")
    print()
    print("    Listing ALL projects visible to your API key...")
    print()

    # Try to list actual projects from the Global Catalog / platform API
    all_projects = []
    for region_name, region_url in REGIONS.items():
        try:
            r = httpx.get(
                f"{region_url}/v2/projects",
                headers=headers,
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                projects = data.get("results", [])
                if projects:
                    print(f"    Projects in {region_name}:")
                    for p in projects:
                        pid  = p.get("metadata", {}).get("id", "?")
                        name = p.get("entity", {}).get("name", "unnamed")
                        print(f"      ID: {pid}  Name: {name}")
                        all_projects.append((region_name, region_url, pid, name))
        except Exception:
            pass

    if not all_projects:
        print("    No projects found under this API key.")
        print()
        print("    ACTION REQUIRED — choose one:")
        print()
        print("    OPTION A: Create a new watsonx.ai project")
        print("      1. Go to https://dataplatform.cloud.ibm.com")
        print("      2. Click 'New project' -> 'Create an empty project'")
        print("      3. Name it anything")
        print("      4. Associate Cloud Object Storage (free Lite)")
        print("      5. Click Create")
        print("      6. Open project -> Manage tab -> copy Project ID")
        print("      7. Paste it in backend/.env as WATSONX_PROJECT_ID=")
        print()
        print("    OPTION B: Use an existing project from a different IBM account")
        print("      Make sure you are logged into the correct IBM Cloud account")
        print("      at https://cloud.ibm.com before creating the API key.")
    else:
        print()
        print("    FOUND YOUR PROJECTS. Update backend/.env with the")
        print("    correct Project ID from the list above, then re-run.")
    exit(1)

# ── Step 3: Check if URL in .env matches found region ────────────────────────
print()
if found_region_url != URL:
    print(f"[3] REGION MISMATCH DETECTED")
    print(f"    .env URL      : {URL}")
    print(f"    Correct URL   : {found_region_url}")
    print()
    print(f"    >>> FIX: Change WATSONX_URL in backend/.env to:")
    print(f"    >>> WATSONX_URL={found_region_url}")
    print()
    print("    Updating check with correct region for step 4...")
    USE_URL = found_region_url
else:
    print(f"[3] Region matches .env: {found_region_name} [OK]")
    USE_URL = URL

# ── Step 4: Test actual Granite inference ─────────────────────────────────────
print(f"\n[4] Testing Granite inference ({MODEL_ID})...")

payload = {
    "model_id": MODEL_ID,
    "project_id": PROJECT_ID,
    "input": "Say exactly: WORKING",
    "parameters": {"max_new_tokens": 10, "temperature": 0.0},
}

try:
    r = httpx.post(
        f"{USE_URL}/ml/v1/text/generation?version=2023-05-29",
        json=payload,
        headers=headers,
        timeout=30,
    )
    if r.status_code == 200:
        result = r.json()["results"][0]["generated_text"].strip()
        print(f"    [OK] Granite responded: '{result}'")
    elif r.status_code == 404:
        data = r.json()
        err  = data.get("errors", [{}])[0].get("message", "")
        print(f"    [FAIL 404] {err}")
        if "model" in err.lower():
            print()
            print("    The model ID may not be available in this region.")
            print("    Try: ibm/granite-3-8b-instruct")
    elif r.status_code == 403:
        print(f"    [FAIL 403] Access denied.")
        print("    Your project may not have WML service associated.")
        print("    Go to: project -> Manage -> Services & integrations")
    else:
        print(f"    [FAIL {r.status_code}] {r.text[:200]}")
except Exception as e:
    print(f"    [ERROR] {e}")

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("=" * 58)
if found_region_url and found_region_url != URL:
    print("  ACTION REQUIRED:")
    print(f"  Change WATSONX_URL in backend/.env to:")
    print(f"  WATSONX_URL={found_region_url}")
elif found_region_url:
    print("  All checks passed - your configuration is correct.")
print("=" * 58)
