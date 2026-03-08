from fastapi import FastAPI
from app.api.router import api_router
from fastapi.security import HTTPBearer


app = FastAPI(
    title="Local Events API",
    version="1.0.0"
)

security = HTTPBearer() 

app.include_router(api_router, prefix="/api")


@app.get("/")
def root():
    return {"message": "Backend is running"}