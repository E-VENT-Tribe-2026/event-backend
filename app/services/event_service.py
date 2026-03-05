from app.db.supabase_client import supabase

def get_all_events():
    response = supabase.table("events").select("*").execute()
    return response.data


def create_event(user_id: str, data: dict):
    data["created_by"] = user_id

    response = supabase.table("events").insert(data).execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event creation failed"
        )

    return response.data[0]


def get_event(event_id: str):
    response = supabase.table("events").select("*").eq("id", event_id).single().execute()

    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )

    return response.data


def update_event(user_id: str, event_id: str, update_data: dict):
    # Check ownership
    event = get_event(event_id)

    if event["created_by"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this event"
        )

    response = supabase.table("events").update(update_data).eq("id", event_id).execute()

    return response.data[0]


def delete_event(user_id: str, event_id: str):
    event = get_event(event_id)

    if event["created_by"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this event"
        )

    supabase.table("events").delete().eq("id", event_id).execute()

    return {"message": "Event deleted"}

def list_events(
    page: int = 1,
    limit: int = 10,
    category: str | None = None,
    upcoming: bool = False,
    search: str | None = None
):
    query = supabase.table("events").select("*")

    if category:
        query = query.eq("category", category)

    if upcoming:
        query = query.gt("start_datetime", datetime.utcnow().isoformat())

    if search:
        query = query.ilike("title", f"%{search}%")

    start = (page - 1) * limit
    end = start + limit - 1

    response = query.range(start, end).execute()

    return response.data