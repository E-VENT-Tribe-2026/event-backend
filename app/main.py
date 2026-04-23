import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from app.api.router import api_router
from app.db.database import engine, Base
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# SQLAlchemy bind
Base.metadata.bind = engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.reminder_service import send_event_reminders

    scheduler = BackgroundScheduler()
    # Poll every minute for testing (window is 2–3 min before start)
    scheduler.add_job(send_event_reminders, "interval", minutes=1, id="event_reminders")
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

# FIXED CORS: Explicitly allowing headers for compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
    expose_headers=["*"],
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
