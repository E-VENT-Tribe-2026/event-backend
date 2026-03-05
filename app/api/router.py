from fastapi import APIRouter
from app.api.v1 import event_routes, auth_routes, profile_routes, event_routes

api_router = APIRouter()

@api_router.get("/health")
def health_check():
    return {"status": "OK"}

api_router.include_router(
    event_routes.router,
    prefix="/events",
    tags=["Events"]
)

api_router.include_router(
    auth_routes.router,
    prefix="/auth",
    tags=["Authentication"]
)

api_router.include_router(
    profile_routes.router,
    prefix="/profile",
    tags=["Profile"]
)

api_router.include_router(
    event_routes.router,
    prefix="/events",
    tags=["Events"]
)