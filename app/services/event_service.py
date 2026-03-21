from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding


def create_event(user_id: str, data: dict):
    # 1. Clean data and attach user
    data["created_by"] = user_id
    
    # 2. THE FIX: Force cost and max_capacity to be pure Integers
    # Even if they come in as 0.0 or "0.0", this turns them into 0
    if "cost" in data and data["cost"] is not None:
        try:
            data["cost"] = int(float(data["cost"]))
        except (ValueError, TypeError):
            data["cost"] = 0
            
    if "max_capacity" in data and data["max_capacity"] is not None:
        try:
            data["max_capacity"] = int(float(data["max_capacity"]))
        except (ValueError, TypeError):
            data["max_capacity"] = 50 # Default fallback

    # 3. Final cleanup for other fields
    data.pop('id', None)
    if "event_embedding" in data:
        data.pop("event_embedding")

    # 4. Execute Insert
    response = supabase.table("events").insert(data).execute()
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


def update_event(user_id: str, event_id: str, update_data: dict):
    event = get_event(event_id)

    if event["created_by"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this event"
        )

    # Regenerate embedding if title or description changed
    if "title" in update_data or "description" in update_data or "category" in update_data:
        title = update_data.get("title", event.get("title", ""))
        description = update_data.get("description", event.get("description", ""))
        category = update_data.get("category", event.get("category", ""))
        text_for_embedding = f"{title} {description} {category}"
        embedding = generate_embedding(text_for_embedding)
        if embedding:
            update_data["event_embedding"] = embedding

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    response = supabase.table("events").update(update_data).eq("id", event_id).execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event update failed"
        )

    return response.data[0]


def delete_event(user_id: str, event_id: str):
    event = get_event(event_id)

    if event["created_by"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this event"
        )

    supabase.table("events").delete().eq("id", event_id).execute()

    return {"message": "Event deleted successfully"}


def get_all_events_by_user(user_id: str):
    """Fetches every event owned by this user without pagination limits."""
    try:
        response = (
            supabase.table("events")
            .select("*, profiles(full_name, avatar_url)") 
            .eq("created_by", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        
        # We return the list directly or wrapped in a data object
        return {
            "status": "success",
            "total_count": len(response.data) if response.data else 0,
            "data": response.data or []
        }
    except Exception as e:
        print(f"Error fetching all user events: {e}")
        # Return an empty list so the frontend doesn't crash
        return {"status": "error", "data": [], "message": str(e)}

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
