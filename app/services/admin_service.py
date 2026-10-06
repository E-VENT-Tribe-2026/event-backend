import math
import logging
from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.utils.query_safety import like_contains

logger = logging.getLogger(__name__)


def _parse_iso_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _build_user_summary(profile: dict | None, user_id: str | None = None) -> dict:
    profile = profile or {}
    username = str(profile.get("username") or "").strip() or None
    full_name = profile.get("full_name")
    display_name = username or full_name

    avatar_kind = str(profile.get("avatar_kind") or "").strip().lower()
    if avatar_kind not in ("photo", "icon"):
        avatar_kind = "icon"

    return {
        "id": profile.get("id") or user_id,
        "username": username,
        "full_name": full_name,
        "display_name": display_name,
        "avatar_kind": avatar_kind,
        "icon_id": profile.get("icon_id"),
        "avatar_url": profile.get("avatar_url"),
    }


def get_admin_counts() -> dict:
    """
    Returns:
    - Total number of registered users.
    - Total number of events split into past, upcoming, and cancelled.
    A cancelled event counts only as cancelled.
    """
    # 1. Total registered users
    users_res = (
        supabase.table("profiles")
        .select("id", count="exact")
        .execute()
    )
    total_users = users_res.count if users_res.count is not None else len(users_res.data or [])

    # 2. Events counts
    events_res = (
        supabase.table("events")
        .select("id, status, start_datetime")
        .execute()
    )
    events = events_res.data or []
    now_utc = datetime.now(timezone.utc)

    cancelled_count = 0
    upcoming_count = 0
    past_count = 0

    for ev in events:
        ev_status = str(ev.get("status") or "").lower()
        if ev_status == "cancelled":
            cancelled_count += 1
            continue

        start_dt = _parse_iso_datetime(ev.get("start_datetime"))
        if start_dt and start_dt >= now_utc:
            upcoming_count += 1
        else:
            past_count += 1

    return {
        "total_users": total_users,
        "events": {
            "total": len(events),
            "upcoming": upcoming_count,
            "past": past_count,
            "cancelled": cancelled_count,
        }
    }


def list_admin_users(search: str | None = None, page: int = 1, limit: int = 20) -> dict:
    """
    Lists every registered account (public and private) in pages.
    Supports case-insensitive substring search by username.
    """
    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit

    query = supabase.table("profiles").select(
        "id, username, full_name, avatar_url, avatar_kind, icon_id, role, created_at",
        count="exact"
    )

    pattern = like_contains(search) if search else None
    if pattern:
        query = query.ilike("username", pattern)

    res = (
        query
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    total = res.count if res.count is not None else len(res.data or [])
    total_pages = max(1, math.ceil(total / limit))

    items = []
    for row in (res.data or []):
        username = str(row.get("username") or "").strip() or None
        full_name = row.get("full_name")
        role = row.get("role") or "user"
        items.append({
            "id": row.get("id"),
            "username": username,
            "full_name": full_name,
            "display_name": username or full_name,
            "avatar_url": row.get("avatar_url"),
            "avatar_kind": row.get("avatar_kind") or "icon",
            "icon_id": row.get("icon_id"),
            "role": role,
            "is_admin": (role == "administrator"),
            "created_at": row.get("created_at"),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


def list_admin_events(status_filter: str = "all", search: str | None = None, page: int = 1, limit: int = 20) -> dict:
    """
    Lists events in pages across four lists: all, past, upcoming, cancelled.
    A cancelled event appears only in all events and cancelled, never in past or upcoming.
    Supports case-insensitive substring search by title.
    """
    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit
    now_iso = datetime.now(timezone.utc).isoformat()
    filter_norm = (status_filter or "all").lower().strip()

    query = supabase.table("events").select(
        "id, title, start_datetime, end_datetime, status, created_by",
        count="exact"
    )

    if filter_norm == "cancelled":
        query = query.eq("status", "cancelled")
    elif filter_norm == "upcoming":
        query = query.neq("status", "cancelled").gte("start_datetime", now_iso)
    elif filter_norm == "past":
        query = query.neq("status", "cancelled").lt("start_datetime", now_iso)
    # "all" does not filter by status or date

    pattern = like_contains(search) if search else None
    if pattern:
        query = query.ilike("title", pattern)

    if filter_norm == "upcoming":
        query = query.order("start_datetime", desc=False)
    else:
        query = query.order("start_datetime", desc=True)

    res = query.range(offset, offset + limit - 1).execute()
    total = res.count if res.count is not None else len(res.data or [])
    total_pages = max(1, math.ceil(total / limit))

    raw_events = res.data or []
    creator_ids = list(dict.fromkeys(ev.get("created_by") for ev in raw_events if ev.get("created_by")))

    organizer_map = {}
    if creator_ids:
        try:
            prof_res = (
                supabase.table("profiles")
                .select("id, username, full_name, avatar_url, avatar_kind, icon_id")
                .in_("id", creator_ids)
                .execute()
            )
            for p in (prof_res.data or []):
                organizer_map[p["id"]] = _build_user_summary(p)
        except Exception as e:
            logger.error(f"Failed to fetch organizers for admin events: {e}")

    items = []
    for ev in raw_events:
        is_canc = str(ev.get("status") or "").lower() == "cancelled"
        items.append({
            "id": ev.get("id"),
            "title": ev.get("title"),
            "date": ev.get("start_datetime"),
            "start_datetime": ev.get("start_datetime"),
            "end_datetime": ev.get("end_datetime"),
            "status": ev.get("status"),
            "is_cancelled": is_canc,
            "organizer": organizer_map.get(ev.get("created_by")) or _build_user_summary(None, ev.get("created_by")),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


def get_admin_user_details(user_id: str) -> dict:
    """
    Returns a user's details:
    - Profile picture, full name, username, creation date, admin status.
    - Events they organize (upcoming, past, cancelled).
    - Events they joined (upcoming, past, cancelled).
    """
    # 1. Fetch user profile
    prof_res = (
        supabase.table("profiles")
        .select("*")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not prof_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    profile = dict(prof_res.data)
    username = str(profile.get("username") or "").strip() or None
    full_name = profile.get("full_name")
    is_admin = (profile.get("role") == "administrator")
    now_utc = datetime.now(timezone.utc)

    # 2. Fetch organized events
    org_res = (
        supabase.table("events")
        .select("id, title, start_datetime, end_datetime, status")
        .eq("created_by", user_id)
        .order("start_datetime", desc=True)
        .execute()
    )
    organized_events = {"upcoming": [], "past": [], "cancelled": []}
    for ev in (org_res.data or []):
        is_canc = str(ev.get("status") or "").lower() == "cancelled"
        item = {
            "id": ev.get("id"),
            "title": ev.get("title"),
            "date": ev.get("start_datetime"),
            "start_datetime": ev.get("start_datetime"),
            "end_datetime": ev.get("end_datetime"),
            "status": ev.get("status"),
            "is_cancelled": is_canc,
        }
        if is_canc:
            organized_events["cancelled"].append(item)
        else:
            start_dt = _parse_iso_datetime(ev.get("start_datetime"))
            if start_dt and start_dt >= now_utc:
                organized_events["upcoming"].append(item)
            else:
                organized_events["past"].append(item)

    # 3. Fetch joined events
    part_res = (
        supabase.table("event_participants")
        .select("event_id")
        .eq("user_id", user_id)
        .execute()
    )
    joined_event_ids = [p["event_id"] for p in (part_res.data or []) if p.get("event_id")]

    joined_events = {"upcoming": [], "past": [], "cancelled": []}
    if joined_event_ids:
        ev_res = (
            supabase.table("events")
            .select("id, title, start_datetime, end_datetime, status")
            .in_("id", joined_event_ids)
            .order("start_datetime", desc=True)
            .execute()
        )
        for ev in (ev_res.data or []):
            is_canc = str(ev.get("status") or "").lower() == "cancelled"
            item = {
                "id": ev.get("id"),
                "title": ev.get("title"),
                "date": ev.get("start_datetime"),
                "start_datetime": ev.get("start_datetime"),
                "end_datetime": ev.get("end_datetime"),
                "status": ev.get("status"),
                "is_cancelled": is_canc,
            }
            if is_canc:
                joined_events["cancelled"].append(item)
            else:
                start_dt = _parse_iso_datetime(ev.get("start_datetime"))
                if start_dt and start_dt >= now_utc:
                    joined_events["upcoming"].append(item)
                else:
                    joined_events["past"].append(item)

    return {
        "id": profile.get("id"),
        "username": username,
        "full_name": full_name,
        "display_name": username or full_name,
        "avatar_url": profile.get("avatar_url"),
        "avatar_kind": profile.get("avatar_kind") or "icon",
        "icon_id": profile.get("icon_id"),
        "created_at": profile.get("created_at"),
        "is_admin": is_admin,
        "role": profile.get("role") or "user",
        "organized_events": organized_events,
        "joined_events": joined_events,
    }


def get_admin_event_details(event_id: str) -> dict:
    """
    Returns an event's full details:
    Title, category, description, date and time, location, organizer, price,
    number of participants and participant limit, whether it is cancelled,
    and its participant list (with profile picture, full name, username).
    """
    # 1. Fetch event
    ev_res = (
        supabase.table("events")
        .select("*")
        .eq("id", event_id)
        .single()
        .execute()
    )
    if not ev_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    event = dict(ev_res.data)
    is_canc = str(event.get("status") or "").lower() == "cancelled"

    # 2. Fetch organizer
    organizer = None
    if event.get("created_by"):
        try:
            org_res = (
                supabase.table("profiles")
                .select("id, username, full_name, avatar_url, avatar_kind, icon_id")
                .eq("id", event["created_by"])
                .single()
                .execute()
            )
            if org_res.data:
                organizer = _build_user_summary(org_res.data)
        except Exception as e:
            logger.error(f"Failed to fetch event organizer {event.get('created_by')}: {e}")

    if not organizer:
        organizer = _build_user_summary(None, event.get("created_by"))

    # 3. Fetch participants
    part_res = (
        supabase.table("event_participants")
        .select("id, user_id, status, created_at")
        .eq("event_id", event_id)
        .order("created_at", desc=False)
        .execute()
    )
    raw_participants = part_res.data or []
    part_user_ids = list(dict.fromkeys(p["user_id"] for p in raw_participants if p.get("user_id")))

    profile_map = {}
    if part_user_ids:
        try:
            prof_res = (
                supabase.table("profiles")
                .select("id, username, full_name, avatar_url, avatar_kind, icon_id")
                .in_("id", part_user_ids)
                .execute()
            )
            for p in (prof_res.data or []):
                profile_map[p["id"]] = _build_user_summary(p)
        except Exception as e:
            logger.error(f"Failed to fetch participant profiles for event {event_id}: {e}")

    participants = []
    for p in raw_participants:
        u_info = profile_map.get(p.get("user_id")) or _build_user_summary(None, p.get("user_id"))
        participants.append({
            "id": u_info.get("id"),
            "username": u_info.get("username"),
            "full_name": u_info.get("full_name"),
            "display_name": u_info.get("display_name"),
            "avatar_url": u_info.get("avatar_url"),
            "avatar_kind": u_info.get("avatar_kind"),
            "icon_id": u_info.get("icon_id"),
            "status": p.get("status") or "registered",
            "registered_at": p.get("created_at"),
        })

    return {
        "id": event.get("id"),
        "title": event.get("title"),
        "category": event.get("category"),
        "description": event.get("description"),
        "date": event.get("start_datetime"),
        "start_datetime": event.get("start_datetime"),
        "end_datetime": event.get("end_datetime"),
        "location_name": event.get("location_name"),
        "latitude": event.get("latitude"),
        "longitude": event.get("longitude"),
        "cost": float(event.get("cost") or 0),
        "max_capacity": event.get("max_capacity"),
        "status": event.get("status"),
        "is_cancelled": is_canc,
        "organizer": organizer,
        "participant_count": len(participants),
        "participants": participants,
    }


def grant_admin_role(target_user_id: str, admin_user_id: str) -> dict:
    """
    Grants the administrator role to an account that is not an administrator.
    Refuses if the account already is an administrator.
    Offers no way to remove the administrator role.
    """
    # 1. Fetch target user
    prof_res = (
        supabase.table("profiles")
        .select("id, role")
        .eq("id", target_user_id)
        .single()
        .execute()
    )
    if not prof_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    current_role = prof_res.data.get("role")
    if current_role == "administrator":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already an administrator."
        )

    # 2. Update role to administrator
    upd_res = (
        supabase.table("profiles")
        .update({"role": "administrator"})
        .eq("id", target_user_id)
        .execute()
    )
    if not upd_res.data:
        raise HTTPException(status_code=500, detail="Failed to grant administrator role.")

    return {
        "message": "Administrator role granted successfully.",
        "user_id": target_user_id,
        "role": "administrator",
    }
