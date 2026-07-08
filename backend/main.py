"""
main.py — FastAPI Application Entry Point
==========================================
This is the top-level file that:
  1. Creates the FastAPI application instance
  2. Registers middleware (CORS, logging, request timing)
  3. Mounts the API router
  4. Registers startup/shutdown lifecycle hooks
  5. Configures global exception handlers
  6. Launches the server when run directly

Architectural decision:
  main.py is intentionally thin.  It wires things together but contains
  zero business logic.  Every config lives in config.py.  Every route
  lives in routes.py.  This makes it trivially easy to find anything.
"""

import logging
import time
import uuid

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from config import settings
from routes import router
from connection_manager import connection_manager


# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("db_chat_assistant")


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code before `yield` runs at startup.
    Code after  `yield` runs at shutdown.
    Using the modern lifespan approach (replaces deprecated on_event handlers).
    """
    logger.info("═" * 60)
    logger.info("  DB Chat Assistant — starting up")
    logger.info(f"  Debug mode : {settings.debug}")
    logger.info(f"  Max rows   : {settings.max_rows_returned}")
    logger.info(f"  History    : {settings.chat_history_window} turns")
    logger.info(f"  Granite    : {settings.granite_model_id}")
    logger.info("═" * 60)

    yield  # ← application runs here

    # Graceful shutdown: dispose all active DB connection pools
    logger.info("Shutting down — disposing all active database connections...")
    sessions = connection_manager.list_sessions()
    for session in sessions:
        connection_manager.remove_session(session["session_id"])
    logger.info(f"Closed {len(sessions)} session(s). Goodbye.")


# ── Application factory ───────────────────────────────────────────────────────

def create_application() -> FastAPI:
    """
    Factory function that builds and configures the FastAPI app.
    Using a factory makes the app easily testable (create a fresh instance per test).
    """
    app = FastAPI(
        title="DB Chat Assistant",
        description=(
            "An AI-powered natural language interface for MySQL databases. "
            "Ask questions in plain English and get SQL + results + explanations."
        ),
        version="1.0.0",
        docs_url="/docs",          # Swagger UI
        redoc_url="/redoc",        # ReDoc UI
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    # In production: replace ["*"] with your actual frontend domain.
    # For local dev: wildcard is fine since auth is session-based in memory.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],   # needed for CSV downloads
    )

    # ── Request ID & Timing Middleware ────────────────────────────────────────
    @app.middleware("http")
    async def add_request_metadata(request: Request, call_next):
        """
        Attaches a unique request ID and logs request timing.
        The X-Request-ID header lets the frontend correlate logs.
        """
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"→ {response.status_code} ({elapsed_ms:.1f}ms)"
        )
        return response

    # ── Global Exception Handlers ─────────────────────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        Pydantic validation errors (422).
        Format them into our standard ErrorResponse shape.
        """
        errors = exc.errors()
        detail = "; ".join(
            f"{' → '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in errors
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "Validation failed", "detail": detail, "status_code": 422},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        """
        Catch-all for any unhandled exception.
        Never expose internal stack traces to the client in production.
        """
        logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
        message = str(exc) if settings.debug else "An internal error occurred"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error", "detail": message, "status_code": 500},
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(router)

    # ── Root endpoint ─────────────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "name": "DB Chat Assistant API",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/api/health",
            "frontend": "Open frontend/index.html in your browser",
        }

    # ── Silence the noisy /favicon.ico 404 ───────────────────────────────────
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        # Return 204 No Content — browser stops asking, no log spam
        from fastapi.responses import Response
        return Response(status_code=204)

    return app


# ── Create the app instance ───────────────────────────────────────────────────
app = create_application()


# ── Dev server entrypoint ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
