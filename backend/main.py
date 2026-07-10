"""FastAPI app entrypoint. Wires up routers, static files, uploads, and auth login."""
import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from .database import init_db, uploads_dir
from .auth import DEFAULT_USERNAME, authenticate, create_token, validate_secrets
from .schemas import LoginRequest, TokenResponse
from .routers import cards, scan, pricing, ebay, sheets, analytics, news

logger = logging.getLogger(__name__)

app = FastAPI(title="CardLister", version="1.0.0")

# CORS is open during local dev where frontend runs on a different port (5173).
# In production the frontend is served from the same origin so this is effectively a no-op.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _callup_poller():
    """Poll for MLB call-ups on a cadence. In-process; Railway keeps us alive."""
    from .services.callups import run_poll_cycle
    from .database import SessionLocal

    minutes = int(os.getenv("CALLUP_POLL_MINUTES", "15"))
    while True:
        try:
            db = SessionLocal()
            try:
                result = run_poll_cycle(db)
                if result["new"] or result["emailed"]:
                    logger.info("Call-up poll: %s", result)
            finally:
                db.close()
        except Exception:
            logger.exception("Call-up poll cycle errored")
        await asyncio.sleep(minutes * 60)


@app.on_event("startup")
def on_startup():
    # Refuse to boot a production deploy with default/insecure secrets.
    validate_secrets()
    init_db()
    # Make sure the uploads directory exists. On Railway this should resolve to /data/uploads
    # via the DB_PATH-derived parent, but locally it just sits next to the project.
    uploads_dir().mkdir(parents=True, exist_ok=True)

    # Background call-up poller — skip in tests/dev via env.
    if os.getenv("DISABLE_CALLUP_POLLER") != "1":
        asyncio.create_task(_callup_poller())


# --- Auth route ---
@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    username = (payload.username or DEFAULT_USERNAME).strip()
    if not authenticate(username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return TokenResponse(token=create_token(username), username=username)


@app.get("/api/health")
def health():
    return {"ok": True}


# --- Feature routers (all guarded by auth dependency inside each router) ---
app.include_router(cards.router, prefix="/api/cards", tags=["cards"])
app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
app.include_router(pricing.router, prefix="/api/pricing", tags=["pricing"])
app.include_router(ebay.router, prefix="/api/ebay", tags=["ebay"])
app.include_router(sheets.router, prefix="/api/sheets", tags=["sheets"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(news.router, prefix="/api/news", tags=["news"])


# --- Uploaded images served back to the browser ---
# Mounted lazily (after dir is ensured) via a small wrapper so startup order is safe.

# Suffixes safe to render inline; anything else (PDFs, coerced unknowns) is
# forced to download so a crafted file can't execute in the app's origin.
INLINE_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@app.get("/uploads/{filename}")
def serve_upload(filename: str):
    # Strip any path traversal attempts; only allow the bare filename.
    safe_name = Path(filename).name
    file_path = uploads_dir() / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    # nosniff stops browsers second-guessing the declared content type.
    headers = {"X-Content-Type-Options": "nosniff"}
    if file_path.suffix.lower() not in INLINE_IMAGE_SUFFIXES:
        # Stored names are uuid-hex + allowlisted suffix, so safe_name is
        # header-safe (no quotes/CR/LF can reach an existing file).
        headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    return FileResponse(str(file_path), headers=headers)


# --- Static frontend (built Vite output) ---
# In production the Dockerfile copies the built frontend into backend/static/.
# If that directory exists, mount it at /. Otherwise, return a friendly placeholder
# so the API still works during local backend-only development.
STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists():
    # html=True makes StaticFiles serve index.html for unknown paths (SPA routing).
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    @app.get("/")
    def root():
        return JSONResponse(
            {
                "message": "CardLister API is running. Frontend not built yet.",
                "hint": "Run `npm run build` in /frontend, then restart, or use the Vite dev server on :5173.",
            }
        )
