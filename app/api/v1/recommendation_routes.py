from fastapi import APIRouter, Depends
from app.services.recommendation_service import get_recommendations
from app.core.dependencies import get_current_user

router = APIRouter()  # ← must be its own router, not imported from app.api.router

@router.get("/recommendations")
def recommendations(limit: int = 10, user=Depends(get_current_user)):
    return get_recommendations(user.id, limit)