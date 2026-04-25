from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user
from app.services.notification_service import (
    get_notifications,
    mark_as_read,
    delete_notification,
)

router = APIRouter()

@router.get("/all")
def fetch_notifications(
    page: int = Query(1),
    limit: int = Query(10),
    user=Depends(get_current_user)
):
    return get_notifications(user.id, page, limit)


@router.patch("/mark-read/{notification_id}")
def mark_read(notification_id: int, user=Depends(get_current_user)):
    return mark_as_read(notification_id, user.id)


@router.delete("/{notification_id}")
def remove_notification(notification_id: int, user=Depends(get_current_user)):
    return delete_notification(notification_id, user.id)