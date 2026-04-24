from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding
from app.services.notification_service import create_notification
from app.services.chat_service import post_system_notification
from app.services.profile_service import get_display_name
import logging

logger = logging.getLogger(__name__)


def _email_participants(event: dict, email_type: str):
    """
    Fire-and-forget: fetch all participant emails and send update/cancellation emails.
    Failures are logged and never bubble up to the caller.
    """
    from app.services.email_service import (
        send_email, build_update_email, build_cancellation_email
    )
    from app.core.config import settings

    from app.core.config import settings

    logger.info(f"_email_participants called: type={email_type}, event={event.get('id')}, smtp_user={settings.SMTP_USER}, smtp_configured={bool(settings.SMTP_USER and settings.SMTP_PASSWORD)}")

    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured — skipping participant emails.")
        return

    event_id = event.get("id")
    try:
        rows = (
            supabase.table("event_participants")
            .select("user_id")
            .eq("event_id", event_id)
            .execute()
        ).data or []
    except Exception as e:
        logger.error(f"Could not fetch participants for email ({event_id}): {e}")
        return

    logger.info(f"Sending {email_type} emails to {len(rows)} participants for event {event_id}")

    if email_type == "update":
        subject, plain, html = build_update_email(event)
    else:
        subject, plain, html = build_cancellation_email(event)

    for row in rows:
        user_id = row["user_id"]
        try:
            import httpx
            url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}"
            headers = {
                "apikey": settings.SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            }
            resp = httpx.get(url, headers=headers, timeout=10)
            email = resp.json().get("email") if resp.status_code == 200 else None
            if email:
                send_email(email, subject, plain, html)
                logger.info(f"Sent {email_type} email to {email} for event {event_id}")
            else:
                logger.warning(f"No email found for user {user_id}")
        except Exception as e:
            logger.error(f"Email ({email_type}) failed for user {user_id}: {e}")


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
    data.pop("event_embedding", None)
    data["status"] = "active"

    # 4. Generate embedding
    embedding_text = " ".join(filter(None, [
        data.get("title"),
        data.get("description"),
        data.get("category"),
    ]))
    embedding = generate_embedding(embedding_text)
    if embedding:
        data["event_embedding"] = embedding

    # 5. Insert event
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

    # Post welcome system message in the event chat
    post_system_notification(event_id, f"👋 Welcome to {event.get('title', 'the event')}! Say hello to everyone.")

    create_notification(
        user_id,
        event_id,
        "event_created",
        f"Your event '{event.get('title', 'New Event')}' has been created"
    )

    return event

def get_event(event_id: str):
    response = (
        supabase.table("events")
        .select("*")
        .eq("id", event_id)
        .single()
        .execute()
    )

    if not response.data:
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
    
    # Fix numeric fields for PostgreSQL bigint
    if "cost" in update_data and update_data["cost"] is not None:
        try:
            update_data["cost"] = int(float(update_data["cost"]))
        except (ValueError, TypeError):
            update_data["cost"] = 0

    if "max_capacity" in update_data and update_data["max_capacity"] is not None:
        try:
            update_data["max_capacity"] = int(float(update_data["max_capacity"]))
        except (ValueError, TypeError):
            update_data["max_capacity"] = 50

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

    display_name = get_display_name(user_id)

    create_notification(
        user_id,
        event_id,
        "event_updated",
        f"Event '{event['title']}' was updated by {display_name}"
    )

    for p in participants.data:
        if p["user_id"] == user_id:
            continue


        create_notification(
            p["user_id"],
            event_id,
            "event_updated",
            f"Event '{event['title']}' was updated by {display_name}"
        )

    # Send update emails to all participants using the full merged event data
    updated_event = {**event, **response.data[0]}
    _email_participants(updated_event, "update")

    return response.data[0]

def delete_event(user_id: str, event_id: str):
    event = get_event(event_id)

    if event["created_by"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this event"
        )

    participants = supabase.table("event_participants") \
        .select("user_id") \
        .eq("event_id", event_id) \
        .execute()
    
    delete_response = supabase.table("events").delete().eq("id", event_id).execute()
    if delete_response.data:
        # Send cancellation emails before notifying
        _email_participants(event, "cancellation")
        display_name = get_display_name(user_id)
        for p in participants.data:
            create_notification(
                p["user_id"],
                event_id,
                "event_deleted",
                f"Event '{event['title']}' was deleted by {display_name}"
            )
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
    now = datetime.now(timezone.utc).isoformat()

    # If search query provided, use semantic search
    if search:
        embedding = generate_embedding(search)
        if embedding:
            response = supabase.rpc("search_events", {
                "query_embedding": embedding,
                "query_text": search,
                "match_count": limit
            }).execute()

            data = [
                e for e in (response.data or [])
                if e.get("end_datetime", "") >= now
                and e.get("status") == "active"
            ]

            return {
                "page": page,
                "limit": limit,
                "data": data
            }

    # Otherwise standard filtered query
    query = supabase.table("events").select(
        "id, title, description, category, cost, max_capacity, status, "
        "start_datetime, end_datetime, location_name, latitude, longitude, "
        "created_by, created_at, updated_at"
    )

    query = query.eq("status", "active")
    query = query.gte("end_datetime", now)

    if date:
        query = query.gte("start_datetime", date)
    if city:
        query = query.ilike("location_name", f"%{city}%")
    if category:
        query = query.eq("category", category)
    if upcoming:
        query = query.gt("start_datetime", now)
        query = query.order("start_datetime", desc=False)
    else:
        query = query.order("created_at", desc=True)

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

    # Send cancellation emails before removing participants
    _email_participants(event, "cancellation")

    supabase.table("event_participants") \
        .delete() \
        .eq("event_id", event_id) \
        .execute()

    # notify
    from app.services.notification_service import create_notification
    
    display_name = get_display_name(user_id)

    for p in participants.data:
        create_notification(
            p["user_id"],
            event_id,
            "event_cancelled",
            f"Event '{event['title']}' was cancelled by {display_name}"
        )

    return {"message": "Event cancelled"}


def get_max_event_price():  # Make sure the name is exactly this
    try:
        response = supabase.table("events") \
            .select("cost") \
            .order("cost", desc=True) \
            .limit(1) \
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0].get("cost", 0)
        return 0
    except Exception as e:
        print(f"Database error in get_max_event_price: {e}")
        return 0

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

