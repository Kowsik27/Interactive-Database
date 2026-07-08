# DBChat AI — Chat with Your Database

> **An AI-powered natural language interface for MySQL databases.**
> Ask questions in plain English. Get SQL, results, and explanations instantly.

---

## What It Does

DBChat AI connects to any MySQL database and lets you interact with it the way you'd talk to a person.

- Type: *"Show all customers who joined last month"*
- The AI generates the SQL, executes it safely, and explains the results.
- Ask follow-up questions. The AI remembers the conversation.

---

## Tech Stack

| Layer    | Technology                                      |
|----------|-------------------------------------------------|
| Frontend | HTML5 · CSS3 · Vanilla JavaScript               |
| Backend  | Python 3.13 · FastAPI · Uvicorn                 |
| Database | MySQL (via SQLAlchemy + PyMySQL)                 |
| AI       | IBM Granite (watsonx.ai) — `ibm/granite-13b-chat-v2` |

---

## Project Structure

```
db-chat-assistant/
│
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Typed settings (Pydantic BaseSettings)
│   ├── models.py            # Request/response Pydantic schemas
│   ├── routes.py            # All API route handlers
│   ├── database.py          # SQLAlchemy engine factory
│   ├── connection_manager.py # In-memory session registry
│   ├── schema_loader.py     # MySQL schema introspector
│   ├── prompt_builder.py    # LLM prompt engineering
│   ├── llm.py               # IBM Granite API client
│   ├── sql_validator.py     # SQL safety gate (allowlist)
│   ├── query_executor.py    # Safe SELECT executor
│   ├── chat_memory.py       # Conversation history manager
│   ├── summary.py           # Natural language summarizer
│   ├── chat_service.py      # Full AI pipeline orchestrator
│   ├── utils.py             # Shared helpers
│   ├── test_core.py         # Unit tests
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/
    ├── index.html           # Single-page app shell
    ├── style.css            # Full design system (dark + light)
    ├── script.js            # App controller + API layer + State
    └── components/
        ├── connection.js    # Connection form logic
        ├── chat.js          # Message rendering
        ├── sidebar.js       # Sidebar + sessions + theme
        └── results.js       # SQL block + results table + CSV export
```

---

## Quick Start

### 1. Clone the project

```bash
git clone https://github.com/your-username/db-chat-assistant
cd db-chat-assistant
```

### 2. Backend setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

### 3. Fill in your `.env`

```ini
WATSONX_API_KEY=your_ibm_api_key_here
WATSONX_PROJECT_ID=your_project_id_here
WATSONX_URL=https://us-south.ml.cloud.ibm.com
GRANITE_MODEL_ID=ibm/granite-13b-chat-v2
```

**How to get your IBM API key:**
1. Go to [https://cloud.ibm.com/iam/apikeys](https://cloud.ibm.com/iam/apikeys)
2. Click **Create an IBM Cloud API key**
3. Copy the key into `.env`

**How to get your project ID:**
1. Open [https://dataplatform.cloud.ibm.com](https://dataplatform.cloud.ibm.com)
2. Open your watsonx.ai project → Settings → copy the Project ID

### 4. Start the backend

```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
═══════════════════════════════════════════════════════════
  DB Chat Assistant — starting up
  Granite : ibm/granite-13b-chat-v2
═══════════════════════════════════════════════════════════
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 5. Open the frontend

```bash
# From the frontend directory — simple static server
python -m http.server 3000

# Then open: http://localhost:3000
```

Or just double-click `frontend/index.html` — it works directly.

---

## API Reference

| Method   | Endpoint                         | Description                          |
|----------|----------------------------------|--------------------------------------|
| `POST`   | `/api/connect`                   | Connect to MySQL, load schema        |
| `DELETE` | `/api/disconnect/{session_id}`   | Disconnect and clean up              |
| `GET`    | `/api/schema/{session_id}`       | Get loaded schema                    |
| `POST`   | `/api/schema/{session_id}/refresh` | Reload schema from DB              |
| `POST`   | `/api/chat`                      | Send message, get AI response        |
| `GET`    | `/api/history/{session_id}`      | Get conversation history             |
| `DELETE` | `/api/history/{session_id}`      | Clear conversation history           |
| `GET`    | `/api/sessions`                  | List all active sessions             |
| `GET`    | `/api/health`                    | Health check                         |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## SQL Safety

Only `SELECT` queries (and `WITH` read-only CTEs) are allowed.

**Blocked keywords:** `INSERT · UPDATE · DELETE · DROP · ALTER · CREATE · TRUNCATE · GRANT · REVOKE · EXEC · LOAD · OUTFILE`

**Additional protections:**
- Row cap enforced at the executor level (default: 500 rows)
- Session-level `MAX_EXECUTION_TIME` timeout
- Query timeout at the MySQL driver level
- SQL injection detection via pattern matching

---

## Running Tests

```bash
cd backend
$env:WATSONX_API_KEY="test"; $env:WATSONX_PROJECT_ID="test"   # Windows
WATSONX_API_KEY=test WATSONX_PROJECT_ID=test                  # macOS/Linux

python test_core.py
```

Expected output:
```
All 13 tests PASSED.
```

---

## Architecture Decisions

| Decision | Rationale |
|---|---|
| In-memory sessions (not DB) | Single-user dev tool — Redis can replace this for multi-user scale |
| httpx instead of IBM SDK | Full control over auth, retries, and error messages |
| Allowlist SQL validator | Harder to bypass than a blocklist; simpler to audit |
| Two LLM calls per turn | First generates SQL, second explains actual results — better quality |
| Pydantic BaseSettings | Typed config with validation at startup — fails fast on misconfiguration |
| asyncio.to_thread | Keeps FastAPI non-blocking while running synchronous DB/LLM calls |
| Schema cached per session | Loaded once at connect time; `/refresh` endpoint for re-introspection |

---

## Common Issues

| Issue | Fix |
|---|---|
| `Cannot reach backend server` | Make sure `uvicorn` is running on port 8000 |
| `IBM IAM token refresh failed` | Check your `WATSONX_API_KEY` in `.env` |
| `2 validation errors for Settings` | You haven't created `.env` yet — copy from `.env.example` |
| `MySQL connection refused` | Verify host, port, and that MySQL is running |
| `Access denied for user` | Wrong username or password |
| CSS not loading | Serve with `python -m http.server` — don't open HTML directly |

---

## License

MIT — free for personal, portfolio, and commercial use.
