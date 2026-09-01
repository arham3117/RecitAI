"""FastAPI application (spec §12)."""

from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from recitai.api.routes import attempts, content, flashcards, quizzes

log = structlog.get_logger(__name__)

app = FastAPI(
    title="RecitAI",
    description=(
        "Local-first study partner. Practice questions drawn only from your own " "course material."
    ),
    version="0.1.0",
)

# The frontend is served separately in development (§14).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """The demo UI. Phase 6 proper is a Next.js app (§14); this is the interim
    single-page client — see plan/DECISIONS.md D-015."""
    return FileResponse(STATIC / "index.html")


app.include_router(content.router, prefix="/api")
app.include_router(quizzes.router, prefix="/api")
app.include_router(attempts.router, prefix="/api")
app.include_router(flashcards.router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Structured errors (§12). An ingest failure or model timeout must say what failed,
    not return an opaque 500."""
    log.error("api.unhandled", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__, "detail": str(exc)[:500], "path": request.url.path},
    )
