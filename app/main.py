import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from app.api.router import api_router
from app.db.database import engine, Base
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

# SQLAlchemy bind
Base.metadata.bind = engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.reminder_service import send_event_reminders
    from app.core.config import settings

    # Log SMTP config on startup so we can verify it's set on Render
    logger.info(f"SMTP config — host: {settings.SMTP_HOST}, port: {settings.SMTP_PORT}, "
                f"user: {settings.SMTP_USER}, password_set: {bool(settings.SMTP_PASSWORD)}, "
                f"from: {settings.EMAIL_FROM}")

    scheduler = BackgroundScheduler()
    # Poll every hour; reminder window is 12–13 h before start so each event is caught once
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
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers['Content-Security-Policy'] = "default-src 'self'"
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

app.add_middleware(SecurityHeadersMiddleware)

# FIXED CORS: Explicitly allowing headers for compatibility
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

# Include routes
app.include_router(api_router, prefix="/api")


@app.get("/")
def root():
    return {
        "status": "E-VENT Orchestrator is Online",
        "message": "Backend is running on Render",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
