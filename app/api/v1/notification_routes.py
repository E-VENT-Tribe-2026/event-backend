from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user
from app.services.notification_service import *

router = APIRouter()

@router.get("/")
def fetch_notifications(
    page: int = Query(1),
    limit: int = Query(10),
    user=Depends(get_current_user)
):
    return get_notifications(user.id, page, limit)


@router.patch("/{notification_id}")
def mark_read(notification_id: int, user=Depends(get_current_user)):
    return mark_as_read(notification_id, user.id)