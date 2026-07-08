"""
Live API integration tests — run against a server already on port 8000.
"""
import httpx

BASE = "http://127.0.0.1:8000"

def test(label, ok, note=""):
    status = "[PASS]" if ok else "[FAIL]"
    print(f"  {status} {label}" + (f"  ({note})" if note else ""))
    assert ok, f"FAILED: {label}"

# 1. Health check
r = httpx.get(f"{BASE}/api/health")
test("GET /api/health", r.status_code == 200 and r.json()["status"] == "healthy",
     f"active_sessions={r.json().get('active_sessions')}")

# 2. Root
r = httpx.get(f"{BASE}/")
test("GET /", r.status_code == 200, r.json().get("name", ""))

# 3. Favicon — must be 204 (not 404)
r = httpx.get(f"{BASE}/favicon.ico")
test("GET /favicon.ico", r.status_code == 204, "no log spam")

# 4. Sessions list (empty at startup)
r = httpx.get(f"{BASE}/api/sessions")
test("GET /api/sessions", r.status_code == 200 and r.json()["total"] == 0,
     f"total={r.json().get('total')}")

# 5. Connect with unreachable port — must be 400 Bad Request (not 500)
r = httpx.post(f"{BASE}/api/connect", json={
    "host": "127.0.0.1", "port": 9999,
    "username": "nobody", "password": "wrong", "database": "noexist"
}, timeout=15)
test("POST /api/connect (bad creds)", r.status_code == 400, "returns 400 with error message")

# 6. Chat with unknown session — must be 404
r = httpx.post(f"{BASE}/api/chat", json={
    "session_id": "00000000-dead-beef-cafe-000000000000",
    "message": "Hello"
})
test("POST /api/chat (invalid session)", r.status_code == 404)

# 7. Schema with unknown session — must be 404
r = httpx.get(f"{BASE}/api/schema/00000000-dead-beef-cafe-111111111111")
test("GET /api/schema/invalid", r.status_code == 404)

# 8. History with unknown session — must be 404
r = httpx.get(f"{BASE}/api/history/00000000-dead-beef-cafe-222222222222")
test("GET /api/history/invalid", r.status_code == 404)

# 9. Validation — missing required fields returns 422
r = httpx.post(f"{BASE}/api/connect", json={"host": "x"})
test("POST /api/connect (missing fields)", r.status_code == 422, "pydantic validation")

# 10. OpenAPI spec is accessible
r = httpx.get(f"{BASE}/openapi.json")
test("GET /openapi.json", r.status_code == 200 and "paths" in r.json())

print()
print("All live API tests PASSED.")
