"""
find_projects.py — Find ALL watsonx.ai projects under your API key
Run: python find_projects.py
"""
import httpx
from pathlib import Path

# Load API key from .env
config = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    config[k.strip()] = v.strip().strip('"').strip("'").strip()

API_KEY = config.get("WATSONX_API_KEY", "")

print("=" * 60)
print("  Finding all watsonx.ai projects for your API key")
print("=" * 60)

# Step 1: Get IAM token
print("\n[1] Authenticating...")
try:
    r = httpx.post(
        "https://iam.cloud.ibm.com/identity/token",
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": API_KEY},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"    [OK] Token obtained")
except Exception as e:
    print(f"    [FAIL] {e}")
    exit(1)

headers_bearer = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}

# Step 2: Get IBM Cloud account info
print("\n[2] Getting your IBM Cloud account info...")
try:
    r = httpx.get(
        "https://iam.cloud.ibm.com/v1/apikeys/details",
        headers={**headers_bearer, "IAM-Apikey": API_KEY},
        timeout=10,
    )
    if r.status_code == 200:
        data = r.json()
        account_id = data.get("account_id", "unknown")
        iam_id     = data.get("iam_id", "unknown")
        key_name   = data.get("name", "unknown")
        print(f"    Key name   : {key_name}")
        print(f"    Account ID : {account_id}")
        print(f"    IAM ID     : {iam_id}")
    else:
        print(f"    Could not get account info ({r.status_code})")
        account_id = None
except Exception as e:
    print(f"    Warning: {e}")
    account_id = None

# Step 3: List projects via IBM Cloud Resource Controller (platform-level)
print("\n[3] Listing ALL projects via IBM Platform API...")
found_any = False

try:
    r = httpx.get(
        "https://us-south.ml.cloud.ibm.com/v2/projects?limit=100",
        headers=headers_bearer,
        timeout=15,
    )
    data = r.json()
    projects = data.get("results", [])
    if projects:
        found_any = True
        print(f"\n    Found {len(projects)} project(s) in us-south:")
        for p in projects:
            pid  = p.get("metadata", {}).get("id", "?")
            name = p.get("entity", {}).get("name", "?")
            print(f"    --------------------------------------------------")
            print(f"    Name       : {name}")
            print(f"    Project ID : {pid}")
            print(f"    >>> Use this in .env: WATSONX_PROJECT_ID={pid}")
except Exception as e:
    print(f"    us-south error: {e}")

# Try eu-de separately
try:
    r = httpx.get(
        "https://eu-de.ml.cloud.ibm.com/v2/projects?limit=100",
        headers=headers_bearer,
        timeout=15,
    )
    data = r.json()
    projects = data.get("results", [])
    if projects:
        found_any = True
        print(f"\n    Found {len(projects)} project(s) in eu-de:")
        for p in projects:
            pid  = p.get("metadata", {}).get("id", "?")
            name = p.get("entity", {}).get("name", "?")
            print(f"    --------------------------------------------------")
            print(f"    Name       : {name}")
            print(f"    Project ID : {pid}")
            print(f"    >>> Use this in .env: WATSONX_PROJECT_ID={pid}")
except Exception as e:
    print(f"    eu-de error: {e}")

# Step 4: If still nothing — try the DataPlatform API directly
print("\n[4] Trying IBM DataPlatform API...")
try:
    r = httpx.get(
        "https://api.dataplatform.cloud.ibm.com/v2/projects?limit=100",
        headers=headers_bearer,
        timeout=15,
    )
    if r.status_code == 200:
        data = r.json()
        projects = data.get("resources", data.get("results", []))
        if projects:
            found_any = True
            print(f"\n    Found {len(projects)} project(s) via DataPlatform API:")
            for p in projects:
                # Different response shape from this endpoint
                meta   = p.get("metadata", p)
                entity = p.get("entity", p)
                pid    = meta.get("guid", meta.get("id", p.get("id", "?")))
                name   = entity.get("name", p.get("name", "?"))
                print(f"    --------------------------------------------------")
                print(f"    Name       : {name}")
                print(f"    Project ID : {pid}")
                print(f"    >>> Use this in .env: WATSONX_PROJECT_ID={pid}")
        else:
            print(f"    No projects returned (status {r.status_code})")
    else:
        print(f"    Status {r.status_code}: {r.text[:150]}")
except Exception as e:
    print(f"    DataPlatform API error: {e}")

print()
print("=" * 60)
if not found_any:
    print("  STILL NO PROJECTS FOUND.")
    print()
    print("  This means your IBM Cloud account has NO watsonx.ai")
    print("  projects yet. You must create one:")
    print()
    print("  1. Go to: https://dataplatform.cloud.ibm.com")
    print("  2. Click 'New project'")
    print("  3. Select 'Create an empty project'")
    print("  4. Name: DBChat AI")
    print("  5. Storage: click Add -> Create Cloud Object Storage (Lite)")
    print("  6. Click Create")
    print("  7. Inside project: Manage tab -> Services & integrations")
    print("     -> Associate service -> Watson Machine Learning (Lite)")
    print("  8. Manage tab -> General -> copy the Project ID")
    print("  9. Paste in backend/.env as WATSONX_PROJECT_ID=")
    print(" 10. Run: python verify_watsonx.py")
else:
    print("  Copy the Project ID above into backend/.env")
    print("  then run: python verify_watsonx.py")
print("=" * 60)
