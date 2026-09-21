import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from app.api.router import api_router
from app.core.limiter import limiter
from app.db.database import engine, Base
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

Base.metadata.bind = engine


DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}

import os
ENV = os.getenv("ENV", "development")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.reminder_service import send_event_reminders
    from app.core.config import settings

    logger.debug(f"SMTP config loaded — password_set: {bool(settings.SMTP_PASSWORD)}")

    scheduler = BackgroundScheduler()
    # Poll every hour; reminder window is 12-13 h before start so each event is caught once
    scheduler.add_job(send_event_reminders, "interval", hours=1, id="event_reminders")
    scheduler.start()
    logger.info("Reminder scheduler started.")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Reminder scheduler stopped.")


app = FastAPI(
    title="E-VENT Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if ENV == "production" else "/docs",
    redoc_url=None if ENV == "production" else "/redoc",
    openapi_url=None if ENV == "production" else "/openapi.json",
)

# Rate limiter state and error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        
        if request.url.path not in DOCS_PATHS:
            response.headers['Content-Security-Policy'] = "default-src 'self'"
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response


app.add_middleware(SecurityHeadersMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",    # for local dev
        "https://event-frontend-delta-tawny.vercel.app"
        ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
)


app.include_router(api_router, prefix="/api")


@app.get("/")
def root():
    return {
        "status": "E-VENT Orchestrator is Online",
        "message": "Backend is running on Render",
        "docs": "/docs" if ENV != "production" else None,
    }


@app.get("/health")
def health_check():

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "up"
    except Exception:
        logger.exception("Health check DB connection failed")
        db_status = "down"

    return {
        "status": "healthy" if db_status == "up" else "degraded",
        "database": db_status,
    }