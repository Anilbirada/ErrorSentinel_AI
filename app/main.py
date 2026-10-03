from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.api import router as api_router
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

# Mount dashboard static assets
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def get_dashboard():
    index_file = DASHBOARD_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>RSR ErrorSentinel AI</h1><p>Dashboard under construction</p>")
