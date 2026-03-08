from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import api_router
from app.db.database import engine, Base #

# This ensures your SQLAlchemy models are recognized, 
# even though the tables are created manually.
Base.metadata.bind = engine 

app = FastAPI(
    title="E-VENT Orchestrator",
    version="1.0.0"
)

# Without this, the Vercel frontend will be blocked from talking to Render.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace "*" with the Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include  routes
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    return {"message": "E-VENT Backend is running on Render"}

@app.get("/")
def read_root():
    return {"status": "E-VENT Orchestrator is Online", "docs": "/docs"}

@app.get("/health")
def health_check():

    return {"status": "healthy"}