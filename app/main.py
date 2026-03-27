from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import api_router
from app.db.database import engine, Base

# SQLAlchemy bind
Base.metadata.bind = engine 

app = FastAPI(
    title="E-VENT Orchestrator",
    version="1.0.0"
)

# FIXED CORS: Explicitly allowing headers for compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}
