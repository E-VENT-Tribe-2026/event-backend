from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding
from app.services.notification_service import create_notification

def validate_coordinates(lat, lng):
    if lat is None or lng is None:
        return

    try:
        lat = float(lat)
        lng = float(lng)
    except:
        raise HTTPException(status_code=400, detail="Invalid coordinates format")

    if not (-90 <= lat <= 90):
        raise HTTPException(status_code=400, detail="Invalid latitude")

    if not (-180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="Invalid longitude")
    

def create_event(user_id: str, data: dict):
    # 1. Clean data and attach user
    data["created_by"] = user_id
    validate_coordinates(data.get("latitude"), data.get("longitude"))

    # 2. Fix numeric fields
    if "cost" in data and data["cost"] is not None:
        try:
            data["cost"] = int(float(data["cost"]))
        except (ValueError, TypeError):
            data["cost"] = 0
            
    if "max_capacity" in data and data["max_capacity"] is not None:
        try:
            data["max_capacity"] = int(float(data["max_capacity"]))
        except (ValueError, TypeError):
            data["max_capacity"] = 50

    # 3. Cleanup
    data.pop('id', None)
    if "event_embedding" in data:
        data.pop("event_embedding")

    # 4. Insert event
    response = supabase.table("events").insert(data).execute()

    if not response.data:
        raise HTTPException(status_code=400, detail="Event creation failed")

    event = response.data[0]
    event_id = event["id"]

    print("EVENT CREATED:", event_id)

    try:
        supabase.table("event_participants").insert({
            "user_id": user_id,
            "event_id": event_id
        }).execute()

        print("CREATOR ADDED AS PARTICIPANT")

    except Exception as e:
        print("Participant insert failed:", str(e))

    return event


def get_event(event_id: str):
    response = (
        supabase.table("events")
        .select("*")
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
    print("UPDATE EVENT CALLED")

    event = get_event(event_id)

    validate_coordinates(
        update_data.get("latitude"),
        update_data.get("longitude")
    )

    if event["created_by"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this event"
        )

    # Regenerate embedding if needed
    if "title" in update_data or "description" in update_data or "category" in update_data:
        title = update_data.get("title", event.get("title", ""))
        description = update_data.get("description", event.get("description", ""))
        category = update_data.get("category", event.get("category", ""))
        text_for_embedding = f"{title} {description} {category}"
        embedding = generate_embedding(text_for_embedding)
        if embedding:
            update_data["event_embedding"] = embedding

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    response = supabase.table("events") \
        .update(update_data) \
        .eq("id", event_id) \
        .execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event update failed"
        )

    print("EVENT UPDATED SUCCESSFULLY")

    participants = supabase.table("event_participants") \
        .select("user_id") \
        .eq("event_id", event_id) \
        .execute()

    print("Participants:", participants.data)

    create_notification(
        user_id,
        event_id,
        "event_updated",
        f"Your event '{event['title']}' has been updated"
    )

    for p in participants.data:
        print("Creating notification for:", p["user_id"])

        create_notification(
            p["user_id"],
            event_id,
            "event_updated",
            f"Event '{event['title']}' has been updated"
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
    
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")

    try:
        response = (
            supabase
            .table("events")
            .select("*")
            .eq("created_by", str(user_id))
            .order("created_at", desc=True)
            .execute()
        )

        event_list = response.data if response.data else []

        return {
            "status": "success",
            "total_count": len(event_list),
            "data": event_list
        }

    except Exception as e:
        print(f"Error fetching user events: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database Crash: {str(e)}"
        )

    
def list_events(
    page: int = 1,
    limit: int = 10,
    category: str | None = None,
    upcoming: bool = False,
    search: str | None = None,
    date: str | None = None,
    city: str | None = None,
):
    
    query = supabase.table("events").select(
        "id, title, description, category, cost, max_capacity, status, "
        "start_datetime, end_datetime, location_name, latitude, longitude, "
        "created_by, created_at, updated_at"
    )

    # Filter out cancelled/inactive events by default
    query = query.neq("status", "cancelled")
    if date:
        query = query.gte("start_datetime", date)

    if city:
        query = query.ilike("location_name", f"%{city}%")

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
    
    
def cancel_event(user_id: str, event_id: str):
    event = get_event(event_id)

    if event["created_by"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # mark cancelled
    supabase.table("events") \
        .update({"status": "cancelled"}) \
        .eq("id", event_id) \
        .execute()

    # remove participants
    participants = supabase.table("event_participants") \
        .select("user_id") \
        .eq("event_id", event_id) \
        .execute()

    supabase.table("event_participants") \
        .delete() \
        .eq("event_id", event_id) \
        .execute()

    # notify
    from app.services.notification_service import create_notification

    for p in participants.data:
        create_notification(
            p["user_id"],
            event_id,
            "event_cancelled",
            f"Event '{event['title']}' has been cancelled"
        )

    return {"message": "Event cancelled"}

'''def get_events_by_user(user_id: str, page: int = 1, limit: int = 10):
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
'''