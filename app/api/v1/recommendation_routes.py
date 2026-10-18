from fastapi import APIRouter, Depends
from app.services.recommendation_service import get_recommendations
from app.services.event_service import attach_organizers
from app.services.participant_service import attach_friends_attending_count
from app.core.dependencies import get_current_user, get_current_onboarded_user

router = APIRouter()  # ← must be its own router, not imported from app.api.router

@router.get("")
def recommendations(limit: int = 10, user=Depends(get_current_onboarded_user)):
    result = get_recommendations(user.id, limit)
    attach_organizers(result.get("data") or [])
    attach_friends_attending_count(result.get("data") or [], user.id)
    return result
