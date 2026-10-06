from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.api import router as api_router
from app.api.routes.auth import router as auth_router
from app.api.routes.connections import router as connections_router
from app.auth.gmail_oauth import authenticated_user
from app.config import get_settings
from app.database.session import init_db
from app.logging.logger import get_logger, setup_logging
from app.scheduler.scheduler import create_scheduler

settings = get_settings()
logger = get_logger("main")
ROOT_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT_DIR / "dashboard"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    logger.info("Initializing RSR ErrorSentinel AI database...")
    init_db()

    logger.info("Starting background scheduler...")
    scheduler = create_scheduler(settings)
    scheduler.start()

    logger.info("RSR ErrorSentinel AI backend is fully initialized and operational.")
    yield

    logger.info("Shutting down background scheduler...")
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="RSR ErrorSentinel AI",
    description="Email Error Intelligence & Monitoring Agent — Detect. Understand. Verify. Alert.",
    version="1.0.0",
    lifespan=lifespan,
)

if settings.app_env == "production" and not settings.session_secret_key:
    raise RuntimeError("SESSION_SECRET_KEY must be configured in production.")

# CORS Middleware
origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# Mount API routes
app.include_router(api_router)
app.include_router(auth_router)
app.include_router(connections_router)


@app.middleware("http")
async def require_google_sign_in(request, call_next):
    path = request.url.path
    protected = (
        path == "/"
        or path.startswith("/api/")
        or path in {"/docs", "/openapi.json", "/redoc"}
    )
    if protected:
        try:
            authenticated_user(request)
        except HTTPException:
            if path == "/":
                return RedirectResponse("/login", status_code=303)
            return JSONResponse(
                status_code=401,
                content={"detail": "Sign in with Google to continue."},
            )
    return await call_next(request)

# Session middleware must wrap authentication middleware so request.session has
# been loaded before protected routes are checked.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key or secrets.token_urlsafe(48),
    session_cookie="errorsentinel_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=settings.app_env == "production",
)

# Mount dashboard static assets
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def get_dashboard():
    index_file = DASHBOARD_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>RSR ErrorSentinel AI</h1><p>Dashboard under construction</p>")


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    auth_status = request.query_params.get("auth")
    message = {
        "cancelled": "Sign-in was cancelled. You can try again.",
        "failed": "Unable to sign in. Please try again.",
    }.get(auth_status, "Sign in to manage Gmail connections and monitoring.")
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in — RSR ErrorSentinel AI</title><link rel="stylesheet" href="/static/styles.css"></head>
<body class="dark-theme"><main style="max-width:440px;margin:12vh auto;padding:24px">
<section class="glass-panel"><div class="panel-header"><h3>RSR ErrorSentinel AI</h3></div>
<div class="gmail-connection-content"><p>{message}</p>
<a class="btn-primary-action" href="/auth/google/login">Continue with Google</a></div></section></main></body></html>"""
    )
