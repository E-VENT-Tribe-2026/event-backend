from fastapi import APIRouter
from app.api.v1 import event_routes

api_router = APIRouter()

@api_router.get("/health")
def health_check():
    return {"status": "OK"}

api_router.include_router(
    event_routes.router,
    prefix="/events",
    tags=["Events"]
)