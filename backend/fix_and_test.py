"""
fix_and_test.py — Find working project + fix .env automatically
Run: python fix_and_test.py
"""
import httpx
from pathlib import Path

config = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    config[k.strip()] = v.strip().strip('"').strip("'").strip()

API_KEY  = config.get("WATSONX_API_KEY", "")
MODEL_ID = config.get("GRANITE_MODEL_ID", "ibm/granite-13b-chat-v2")

# All projects found
PROJECTS = [
    ("Interactive DB",                  "dd86be3f-d730-4759-b7bd-4e8f6c22ae51"),
    ("Kowsik Kumar Reddy's sandbox",    "05c745c3-91a0-4dc3-97c3-154f8db7541e"),
    ("Nutition agent",                  "a2cf9a41-16a9-42c9-a3b3-d62a33e1e896"),
    ("CROP Recommendation System",      "6949f0ed-27bd-438f-8d57-7e136d828d80"),
]

REGIONS = [
    ("eu-de",    "https://eu-de.ml.cloud.ibm.com"),
    ("us-south", "https://us-south.ml.cloud.ibm.com"),
    ("eu-gb",    "https://eu-gb.ml.cloud.ibm.com"),
    ("jp-tok",   "https://jp-tok.ml.cloud.ibm.com"),
]

# Also try newer model IDs in case granite-13b-chat-v2 is deprecated
MODEL_IDS = [
    "ibm/granite-13b-chat-v2",
    "ibm/granite-3-8b-instruct",
    "ibm/granite-3-2b-instruct",
    "ibm/granite-13b-instruct-v2",
    "meta-llama/llama-3-1-8b-instruct",
]

print("=" * 60)
print("  DBChat AI — Auto Fix & Test")
print("=" * 60)

# Get token
print("\n[1] Getting IAM token...")
r = httpx.post(
    "https://iam.cloud.ibm.com/identity/token",
    data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": API_KEY},
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    timeout=15,
)
r.raise_for_status()
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print("    [OK]")

# Test every project × every region × every model until one works
print("\n[2] Testing all project + region + model combinations...")
print("    (This finds the working combination automatically)\n")

winner = None

for proj_name, proj_id in PROJECTS:
    for region_name, region_url in REGIONS:
        # Quick inference test with minimal tokens
        for model_id in MODEL_IDS:
            try:
                payload = {
                    "model_id": model_id,
                    "project_id": proj_id,
                    "input": "Reply with one word: WORKING",
                    "parameters": {"max_new_tokens": 5, "temperature": 0.0},
                }
                r = httpx.post(
                    f"{region_url}/ml/v1/text/generation?version=2023-05-29",
                    json=payload,
                    headers=headers,
                    timeout=20,
                )
                if r.status_code == 200:
                    result = r.json()["results"][0]["generated_text"].strip()
                    print(f"    [WORKING]")
                    print(f"    Project  : {proj_name}")
                    print(f"    ID       : {proj_id}")
                    print(f"    Region   : {region_name} ({region_url})")
                    print(f"    Model    : {model_id}")
                    print(f"    Response : '{result}'")
                    winner = (proj_id, region_url, model_id)
                    break
                elif r.status_code in (404, 403):
                    # Expected — try next combo
                    pass
            except Exception:
                pass
        if winner:
            break
    if winner:
        break

print()
if winner:
    proj_id, region_url, model_id = winner
    print("=" * 60)
    print("  SUCCESS! Working configuration found.")
    print("=" * 60)
    print()
    print("  Update your backend/.env with these exact values:")
    print()
    print(f"  WATSONX_API_KEY={API_KEY}")
    print(f"  WATSONX_PROJECT_ID={proj_id}")
    print(f"  WATSONX_URL={region_url}")
    print(f"  GRANITE_MODEL_ID={model_id}")
    print()

    # Auto-update the .env file
    env_path = Path(".env")
    env_text = env_path.read_text(encoding="utf-8")

    def replace_val(text, key, new_val):
        import re
        return re.sub(
            rf"^{key}=.*$",
            f"{key}={new_val}",
            text,
            flags=re.MULTILINE,
        )

    env_text = replace_val(env_text, "WATSONX_PROJECT_ID", proj_id)
    env_text = replace_val(env_text, "WATSONX_URL",        region_url)
    env_text = replace_val(env_text, "GRANITE_MODEL_ID",   model_id)

    env_path.write_text(env_text, encoding="utf-8")
    print("  [AUTO-UPDATED] backend/.env has been updated.")
    print("  Uvicorn will auto-reload. Go back to the browser")
    print("  and send a message — it will work now.")
    print()
    print("=" * 60)
else:
    print("=" * 60)
    print("  No working combination found.")
    print()
    print("  Most likely cause: none of your projects have")
    print("  Watson Machine Learning service associated.")
    print()
    print("  Fix:")
    print("  1. Go to https://dataplatform.cloud.ibm.com")
    print("  2. Open project 'Interactive DB'")
    print("  3. Click Manage -> Services & integrations")
    print("  4. Click Associate service")
    print("  5. Select Watson Machine Learning")
    print("     (Create a free Lite instance if needed)")
    print("  6. Click Associate")
    print("  7. Run this script again: python fix_and_test.py")
    print("=" * 60)
