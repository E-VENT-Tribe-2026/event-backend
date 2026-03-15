from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding


def create_event(user_id: str, data: dict):
    data["created_by"] = user_id

    for key, value in data.items():

        if isinstance(value, datetime):
            data[key] = value.isoformat()

        # Convert float → int for bigint fields
        if key in ["cost", "max_capacity"] and value is not None:
            data[key] = int(value)

    response = supabase.table("events").insert(data).execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event creation failed"
        )

    return response.data[0]


def get_event(event_id: str):
    response = (
        supabase.table("events")
        .select("*, profiles(full_name, avatar_url), event_tags(tags(name))")
        .eq("id", event_id)
        .single()
        .execute()
    )
    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    return response.data


def _get_event_owner(event_id: str) -> str:
    """Internal use only — returns just created_by as a plain string."""
    response = (
        supabase.table("events")
        .select("id, created_by")
        .eq("id", event_id)
        .single()
        .execute()
    )
    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    return response.data["created_by"]


def update_event(user_id: str, event_id: str, update_data: dict):
    if _get_event_owner(event_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this event"
        )

    for key, value in update_data.items():
        if isinstance(value, datetime):
            update_data[key] = value.isoformat()

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    response = supabase.table("events").update(update_data).eq("id", event_id).execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event update failed"
        )
    return response.data[0]


def delete_event(user_id: str, event_id: str):
    if _get_event_owner(event_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this event"
        )

    supabase.table("events").delete().eq("id", event_id).execute()
    return {"message": "Event deleted successfully"}


def list_events(
    page: int = 1,
    limit: int = 10,
    category: str | None = None,
    upcoming: bool = False,
    search: str | None = None,
):
    query = supabase.table("events").select(
        "id, title, description, category, cost, max_capacity, status, "
        "start_datetime, end_datetime, location_name, latitude, longitude, "
        "created_by, created_at, updated_at"
    )

    # Filter out cancelled/inactive events by default
    query = query.neq("status", "cancelled")

    if category:
        query = query.eq("category", category)

    if upcoming:
        query = query.gt("start_datetime", datetime.now(timezone.utc).isoformat())
        query = query.order("start_datetime", desc=False)
    else:
        query = query.order("created_at", desc=True)

    if search:
        query = query.ilike("title", f"%{search}%")

    start = (page - 1) * limit
    end = start + limit - 1

    response = query.range(start, end).execute()

    return {
        "page": page,
        "limit": limit,
        "data": response.data
    }


def get_events_by_user(user_id: str, page: int = 1, limit: int = 10):
    start = (page - 1) * limit
    end = start + limit - 1

    response = (
        supabase.table("events")
        .select("*")
        .eq("created_by", user_id)
        .order("created_at", desc=True)
        .range(start, end)
        .execute()
    )

    return {
        "page": page,
        "limit": limit,
        "data": response.data
    }