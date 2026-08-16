"""FastAPI app entrypoint. Wires up routers, static files, uploads, and auth login."""
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text

from .database import engine, init_db, uploads_dir
from .auth import DEFAULT_USERNAME, authenticate, create_token, validate_secrets
from .schemas import LoginRequest, TokenResponse
from .routers import cards, scan, pricing, ebay, ebay_compliance, sheets, analytics, news

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


# Heartbeat state for /api/health: whether the call-up poller is running in this
# process and when its loop last completed a cycle (success or error — either
# proves the loop is alive).
POLL_MINUTES = int(os.getenv("CALLUP_POLL_MINUTES", "15"))
_poller_state = {"enabled": False, "last_cycle_at": None}
_started_at = datetime.utcnow()


async def _callup_poller():
    """Poll for MLB call-ups on a cadence. In-process; Railway keeps us alive."""
    from .services.callups import run_poll_cycle
    from .database import SessionLocal

    while True:
        try:
            db = SessionLocal()
            try:
                # run_poll_cycle does sync network I/O (MLB fetch + email send,
                # up to ~35s of timeouts) — keep it off the single event loop
                # so requests don't stall while a cycle runs.
                result = await run_in_threadpool(run_poll_cycle, db)
                if result["new"] or result["emailed"]:
                    logger.info("Call-up poll: %s", result)
            finally:
                db.close()
        except Exception:
            logger.exception("Call-up poll cycle errored")
        _poller_state["last_cycle_at"] = datetime.utcnow()
        await asyncio.sleep(POLL_MINUTES * 60)


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
        _poller_state["enabled"] = True
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
    """Deep health check for uptime monitors and the daily routine.

    Unauthenticated by design, so it only reports coarse liveness facts:
    DB reachability, the deployed revision (Railway injects the commit SHA),
    and the call-up poller heartbeat. Returns 503 when the DB is unreachable
    so HTTP-status-based monitors alert without parsing the body.
    """
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: database unreachable")
        db_ok = False

    now = datetime.utcnow()
    last = _poller_state["last_cycle_at"]
    # Stale = poller should be running but hasn't completed a cycle within
    # 3 poll intervals (measured from startup until the first cycle lands).
    stale = (
        _poller_state["enabled"]
        and (now - (last or _started_at)).total_seconds() > 3 * POLL_MINUTES * 60
    )
    body = {
        "ok": db_ok,
        "db": db_ok,
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA", "")[:7] or None,
        "poller": {
            "enabled": _poller_state["enabled"],
            "interval_minutes": POLL_MINUTES,
            "last_cycle_at": last.isoformat() + "Z" if last else None,
            "stale": stale,
        },
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


# --- Feature routers (all guarded by auth dependency inside each router) ---
app.include_router(cards.router, prefix="/api/cards", tags=["cards"])
app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
app.include_router(pricing.router, prefix="/api/pricing", tags=["pricing"])
app.include_router(ebay.router, prefix="/api/ebay", tags=["ebay"])
# Public: eBay's servers call these (deletion notices, OAuth redirects) — no auth.
app.include_router(ebay_compliance.router, prefix="/api/ebay-compliance", tags=["ebay-compliance"])
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
    # Stored names are uuid-hex, so a given URL's bytes never change — cache
    # forever instead of refetching full-size photos on every inventory render.
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=31536000, immutable",
    }
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

class SpaStaticFiles(StaticFiles):
    """StaticFiles with a real SPA fallback.

    `html=True` alone only serves index.html for *directory* requests, so a hard
    load of a client route (refresh or bookmark on /inventory, /analytics, or a
    card permalink) fell through to a bare `{"detail":"Not Found"}` 404 — the
    router only ever ran when navigating from `/`.

    Unknown paths under the API roots keep their 404: an API client that
    typo'd an endpoint must not get 200 + HTML back, and neither must a missing
    upload, which `serve_upload` 404s deliberately. `assets` is excluded for
    the same reason — Vite's bundles live there under content-hashed names, and
    answering a stale bundle request with HTML turns a bad deploy into an
    unreadable JS syntax error instead of a clean 404.
    """

    NON_SPA_ROOTS = ("api", "uploads", "assets")

    def _is_page_load(self, path, scope) -> bool:
        # Match the first path segment so both the bare root (/api) and every
        # descendant (/api/nope) are excluded, while a client route that merely
        # starts with the same letters (/apikeys) is not. Case-folded so
        # /API/nope 404s like /api/nope: routing itself stays case-sensitive,
        # but this only decides shell-vs-404 for paths that already missed, and
        # anything shaped like an API path should never render HTML.
        if path.lower().split("/", 1)[0] in self.NON_SPA_ROOTS:
            return False
        # Only GET/HEAD can be a page load; a POST to a bad path stays a 404.
        return scope.get("method") in ("GET", "HEAD")

    async def get_response(self, path, scope):
        # A miss surfaces as a raised HTTPException (Starlette's own path) or,
        # defensively, as a 404 response — handle both.
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self._is_page_load(path, scope):
                raise
            response = await super().get_response("index.html", scope)
        else:
            if response.status_code == 404 and self._is_page_load(path, scope):
                response = await super().get_response("index.html", scope)
        if response.status_code == 200:
            if str(getattr(response, "path", "")).endswith("index.html"):
                # The shell must revalidate on every load: a heuristically
                # cached shell outlives its hashed bundles across a deploy and
                # white-screens on the (deliberate) /assets 404. The ETag
                # Starlette already sets makes revalidation a cheap 304.
                response.headers["Cache-Control"] = "no-cache"
            elif path.split("/", 1)[0] == "assets":
                # Vite bundle names are content-hashed — same forever-cache
                # rule as /uploads.
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if STATIC_DIR.exists():
    # html=True serves index.html at "/"; SpaStaticFiles extends that to deep links.
    app.mount("/", SpaStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    @app.get("/")
    def root():
        return JSONResponse(
            {
                "message": "CardLister API is running. Frontend not built yet.",
                "hint": "Run `npm run build` in /frontend, then restart, or use the Vite dev server on :5173.",
            }
        )
