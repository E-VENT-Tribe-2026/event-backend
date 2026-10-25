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


def _as_text(value) -> str | None:
    if value is None:
        return None
    return str(value)


def _event_card(ev: dict) -> dict:
    start_dt = _as_text(ev.get("start_datetime"))
    end_dt = _as_text(ev.get("end_datetime"))
    return {
        "id": str(ev.get("id")),
        "title": ev.get("title") or "",
        "date": start_dt,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "status": ev.get("status"),
        "is_cancelled": str(ev.get("status") or "").lower() == "cancelled",
        "is_removed": bool(ev.get("removed_at")),
        "removed_at": _as_text(ev.get("removed_at")),
    }


def _removed_by(admin_id, people: dict):
    """The administrator who removed something, as a person summary, or None when not removed."""
    if not admin_id:
        return None
    return people.get(str(admin_id)) or _build_user_summary(None, admin_id)


def _build_user_summary(profile: dict | None, user_id: str | None = None) -> dict:
    profile = profile or {}
    username = str(profile.get("username") or "").strip() or None
    full_name = profile.get("full_name")
    display_name = username or full_name
    uid = profile.get("id") or user_id

    avatar_kind = str(profile.get("avatar_kind") or "").strip().lower()
    if avatar_kind not in ("photo", "icon"):
        avatar_kind = "icon"

    return {
        "id": str(uid) if uid else None,
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


def _is_admin_role(role) -> bool:
    return role in ("administrator", "admin")


def _account_status(profile: dict) -> str:
    return "suspended" if profile.get("suspended_at") else "active"


def _empty_page(page: int, limit: int) -> dict:
    return {"items": [], "total": 0, "page": page, "limit": limit, "total_pages": 1}


def list_admin_users(search: str | None = None, page: int = 1, limit: int = 20,
                     filter_by: str | None = None) -> dict:
    """
    Lists every registered account (public and private) in pages.
    Supports case-insensitive substring search by username, combined with
    one counter filter: administrators, suspended or with_warnings.
    """
    from app.services.warning_service import counted_warning_counts, user_ids_with_counted_warnings

    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit

    query = supabase.table("profiles").select(
        "id, username, full_name, avatar_url, avatar_kind, icon_id, role, created_at, suspended_at",
        count="exact"
    )

    pattern = like_contains(search) if search else None
    if pattern:
        query = query.ilike("username", pattern)

    if filter_by == "administrators":
        query = query.eq("role", "administrator")
    elif filter_by == "suspended":
        query = query.neq("role", "administrator").not_.is_("suspended_at", "null")
    elif filter_by == "with_warnings":
        warned_ids = user_ids_with_counted_warnings()
        if not warned_ids:
            return _empty_page(page, limit)
        query = query.in_("id", warned_ids)

    try:
        res = (
            query
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception as e:
        logger.error(f"list_admin_users failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load users.",
        )

    total = res.count if res.count is not None else len(res.data or [])
    total_pages = max(1, math.ceil(total / limit))

    rows = [row for row in (res.data or []) if row.get("id")]
    try:
        counts = counted_warning_counts(
            [r.get("id") for r in rows if not _is_admin_role(r.get("role"))]
        )
    except Exception as e:
        logger.warning(f"list_admin_users warning counts unavailable: {e}")
        counts = {}

    items = []
    for row in rows:
        username = str(row.get("username") or "").strip() or None
        full_name = row.get("full_name")
        role = row.get("role") or "user"
        is_admin = _is_admin_role(role)
        created_at = row.get("created_at")
        if created_at is not None and not isinstance(created_at, str):
            created_at = str(created_at)
        items.append({
            "id": str(row.get("id")),
            "username": username,
            "full_name": full_name,
            "display_name": username or full_name,
            "avatar_url": row.get("avatar_url"),
            "avatar_kind": row.get("avatar_kind") or "icon",
            "icon_id": row.get("icon_id"),
            "role": role,
            "is_admin": is_admin,
            "created_at": created_at,
            # #191: an administrator's entry shows the role only.
            "warning_count": None if is_admin else counts.get(row.get("id"), 0),
            "status": None if is_admin else _account_status(row),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }

def get_user_list_counters() -> dict:
    """The three counters at the top of the user list."""
    from app.services.warning_service import user_ids_with_counted_warnings

    admins = (
        supabase.table("profiles").select("id", count="exact")
        .eq("role", "administrator").execute()
    )
    suspended = (
        supabase.table("profiles").select("id", count="exact")
        .neq("role", "administrator").not_.is_("suspended_at", "null").execute()
    )
    try:
        warned = len(user_ids_with_counted_warnings())
    except Exception as e:
        logger.warning(f"get_user_list_counters warning count unavailable: {e}")
        warned = 0
    return {
        "administrators": admins.count if admins.count is not None else len(admins.data or []),
        "suspended": suspended.count if suspended.count is not None else len(suspended.data or []),
        "with_warnings": warned,
    }


def _summaries_for(ids) -> list:
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return []
    res = (
        supabase.table("profiles")
        .select("id, username, full_name, avatar_url, avatar_kind, icon_id")
        .in_("id", ids)
        .execute()
    )
    return [_build_user_summary(row) for row in (res.data or [])]


def _relations_of(user_id: str) -> dict:
    """Friends, users they blocked, users who blocked them. Ignores profile visibility on purpose."""
    friends = (
        supabase.table("friendships").select("user_id, friend_id")
        .or_(f"user_id.eq.{user_id},friend_id.eq.{user_id}").execute()
    )
    friend_ids = [
        r["friend_id"] if str(r["user_id"]) == str(user_id) else r["user_id"]
        for r in (friends.data or [])
    ]
    blocked = supabase.table("user_blocks").select("blocked_id").eq("blocker_id", user_id).execute()
    blocked_by = supabase.table("user_blocks").select("blocker_id").eq("blocked_id", user_id).execute()
    return {
        "friends": _summaries_for(friend_ids),
        "blocked_users": _summaries_for(r["blocked_id"] for r in (blocked.data or [])),
        "blocked_by": _summaries_for(r["blocker_id"] for r in (blocked_by.data or [])),
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
        "id, title, start_datetime, end_datetime, status, created_by, banner_url, removed_at, removed_by",
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

    try:
        res = query.range(offset, offset + limit - 1).execute()
    except Exception as e:
        logger.error(f"list_admin_events failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load events.",
        )
    total = res.count if res.count is not None else len(res.data or [])
    total_pages = max(1, math.ceil(total / limit))

    raw_events = [ev for ev in (res.data or []) if ev.get("id")]
    creator_ids = list(dict.fromkeys(
        person for ev in raw_events for person in (ev.get("created_by"), ev.get("removed_by")) if person
    ))

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
                organizer_map[str(p["id"])] = _build_user_summary(p)
        except Exception as e:
            logger.error(f"Failed to fetch organizers for admin events: {e}")

    items = []
    for ev in raw_events:
        is_canc = str(ev.get("status") or "").lower() == "cancelled"
        created_by = ev.get("created_by")
        organizer = organizer_map.get(str(created_by) if created_by else "") or (
            _build_user_summary(None, created_by) if created_by else None
        )
        if organizer and not organizer.get("id"):
            organizer = None
        start_dt = ev.get("start_datetime")
        if start_dt is not None and not isinstance(start_dt, str):
            start_dt = str(start_dt)
        end_dt = ev.get("end_datetime")
        if end_dt is not None and not isinstance(end_dt, str):
            end_dt = str(end_dt)
        items.append({
            "id": str(ev.get("id")),
            "title": ev.get("title") or "",
            "date": start_dt,
            "start_datetime": start_dt,
            "end_datetime": end_dt,
            "status": ev.get("status"),
            "is_cancelled": is_canc,
            "organizer": organizer,
            "banner": ev.get("banner_url"),
            "banner_url": ev.get("banner_url"),
            "is_removed": bool(ev.get("removed_at")),
            "removed_at": _as_text(ev.get("removed_at")),
            "removed_by": _removed_by(ev.get("removed_by"), organizer_map),
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
    from app.services.warning_service import counted_warning_counts
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
    is_admin = _is_admin_role(profile.get("role"))
    now_utc = datetime.now(timezone.utc)

    # 2. Fetch organized events
    org_res = (
        supabase.table("events")
        .select("id, title, start_datetime, end_datetime, status, removed_at")
        .eq("created_by", user_id)
        .order("start_datetime", desc=True)
        .execute()
    )
    organized_events = {"upcoming": [], "past": [], "cancelled": []}
    for ev in (org_res.data or []):
        if not ev.get("id"):
            continue
        item = _event_card(ev)
        if item["is_cancelled"]:
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
            .select("id, title, start_datetime, end_datetime, status, removed_at")
            .in_("id", joined_event_ids)
            .order("start_datetime", desc=True)
            .execute()
        )
        for ev in (ev_res.data or []):
            if not ev.get("id"):
                continue
            item = _event_card(ev)
            if item["is_cancelled"]:
                joined_events["cancelled"].append(item)
            else:
                start_dt = _parse_iso_datetime(ev.get("start_datetime"))
                if start_dt and start_dt >= now_utc:
                    joined_events["upcoming"].append(item)
                else:
                    joined_events["past"].append(item)

    try:
        warning_count = None if is_admin else counted_warning_counts([user_id]).get(user_id, 0)
    except Exception as e:
        logger.warning(f"Could not load warning count for {user_id}: {e}")
        warning_count = None if is_admin else 0

    return {
        "id": str(profile.get("id") or user_id),
        "username": username,
        "full_name": full_name,
        "display_name": username or full_name,
        "avatar_url": profile.get("avatar_url"),
        "avatar_kind": profile.get("avatar_kind") or "icon",
        "icon_id": profile.get("icon_id"),
        "created_at": _as_text(profile.get("created_at")),
        "is_admin": is_admin,
        "admin_since": _as_text(profile.get("admin_since")) if is_admin else None,
        "role": profile.get("role") or "user",
        "warnings": [],
        "warning_history": [],
        "organized_events": organized_events,
        "joined_events": joined_events,
        "profile_visibility": None if is_admin else (profile.get("visibility") or "public"),
        "status": None if is_admin else _account_status(profile),
        "suspended_since": None if is_admin else _as_text(profile.get("suspended_at")),
        "suspension_reason": None if is_admin else profile.get("suspension_reason"),
        "warning_count": warning_count,
        **({"friends": [], "blocked_users": [], "blocked_by": []} if is_admin else _relations_of(user_id)),
    }


def get_admin_account_details(admin_id: str) -> dict:
    """
    Returns the signed-in administrator's account details for the account screen:
    profile picture, full name, username and the date they became an administrator.
    """
    prof_res = (
        supabase.table("profiles")
        .select("id, username, full_name, avatar_url, avatar_kind, icon_id, admin_since, role")
        .eq("id", admin_id)
        .single()
        .execute()
    )
    if not prof_res or not prof_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Administrator profile not found.")

    p = prof_res.data
    email = None
    try:
        from app.core.config import settings
        from supabase import create_client
        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
            admin_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
            user_auth = admin_client.auth.admin.get_user_by_id(admin_id)
            if user_auth and user_auth.user:
                email = user_auth.user.email
    except Exception as e:
        logger.debug(f"Could not fetch auth email for admin {admin_id}: {e}")

    return {
        "id": str(p.get("id") or admin_id),
        "email": email,
        "username": p.get("username"),
        "full_name": p.get("full_name"),
        "avatar_url": p.get("avatar_url"),
        "avatar_kind": p.get("avatar_kind") or "icon",
        "icon_id": p.get("icon_id"),
        "admin_since": _as_text(p.get("admin_since")),
        "role": p.get("role") or "administrator",
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

    if not organizer and event.get("created_by"):
        organizer = _build_user_summary(None, event.get("created_by"))
    if organizer and not organizer.get("id"):
        organizer = None

    removed_by = None
    if event.get("removed_by"):
        try:
            rb_res = (
                supabase.table("profiles")
                .select("id, username, full_name, avatar_url, avatar_kind, icon_id")
                .eq("id", event["removed_by"])
                .single()
                .execute()
            )
            people = {str(event["removed_by"]): _build_user_summary(rb_res.data)} if rb_res.data else {}
            removed_by = _removed_by(event["removed_by"], people)
        except Exception as e:
            logger.error(f"Failed to fetch the administrator who removed event {event_id}: {e}")
            removed_by = _build_user_summary(None, event["removed_by"])

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
    role_map = {}
    if part_user_ids:
        try:
            prof_res = (
                supabase.table("profiles")
                .select("id, username, full_name, avatar_url, avatar_kind, icon_id, role")
                .in_("id", part_user_ids)
                .execute()
            )
            for p in (prof_res.data or []):
                profile_map[p["id"]] = _build_user_summary(p)
                role_map[p["id"]] = p.get("role")
        except Exception as e:
            logger.error(f"Failed to fetch participant profiles for event {event_id}: {e}")

    participants = []
    for p in raw_participants:
        u_info = profile_map.get(p.get("user_id")) or _build_user_summary(None, p.get("user_id"))
        p_role = role_map.get(p.get("user_id"))
        is_part_admin = (p_role in ("administrator", "admin"))
        participants.append({
            "id": u_info.get("id"),
            "username": u_info.get("username"),
            "full_name": u_info.get("full_name"),
            "display_name": u_info.get("display_name"),
            "avatar_url": u_info.get("avatar_url"),
            "avatar_kind": u_info.get("avatar_kind"),
            "icon_id": u_info.get("icon_id"),
            "status": p.get("status") or "registered",
            "registered_at": _as_text(p.get("created_at")),
            "is_admin": is_part_admin,
        })

    # 4. Fetch chat messages
    chat_res = (
        supabase.table("event_chats")
        .select("id, sender_id, content, type, created_at, removed_at, removed_by")
        .eq("event_id", event_id)
        .order("created_at", desc=False)
        .execute()
    )
    raw_chats = chat_res.data or []
    chat_sender_ids = list(dict.fromkeys(c["sender_id"] for c in raw_chats if c.get("sender_id")))

    chat_sender_ids += [c["removed_by"] for c in raw_chats
                        if c.get("removed_by") and c["removed_by"] not in chat_sender_ids]
    missing_chat_senders = [sid for sid in chat_sender_ids if sid not in profile_map]
    if missing_chat_senders:
        try:
            cprof_res = (
                supabase.table("profiles")
                .select("id, username, full_name, avatar_url, avatar_kind, icon_id")
                .in_("id", missing_chat_senders)
                .execute()
            )
            for p in (cprof_res.data or []):
                profile_map[p["id"]] = _build_user_summary(p)
        except Exception as e:
            logger.error(f"Failed to fetch chat sender profiles for event {event_id}: {e}")

    chats = []
    for c in raw_chats:
        sender_id = c.get("sender_id")
        msg_type = str(c.get("type") or "chat").lower()
        is_system = (not sender_id) or (msg_type in ("system", "notification"))

        sender_info = None
        if not is_system and sender_id:
            sender_info = profile_map.get(sender_id) or _build_user_summary(None, sender_id)

        username = sender_info.get("username") if sender_info else ("system" if is_system else None)
        full_name = sender_info.get("full_name") if sender_info else ("System" if is_system else None)
        avatar_url = sender_info.get("avatar_url") if sender_info else None
        avatar_kind = sender_info.get("avatar_kind") if sender_info else "icon"
        icon_id = sender_info.get("icon_id") if sender_info else None

        item = {
            "id": c.get("id"),
            "sender_id": sender_id,
            "sender": sender_info,
            "username": username,
            "full_name": full_name,
            "avatar_url": avatar_url,
            "avatar_kind": avatar_kind,
            "icon_id": icon_id,
            "text": c.get("content") or "",
            "content": c.get("content") or "",
            "time": _as_text(c.get("created_at")),
            "created_at": _as_text(c.get("created_at")),
            "is_system_message": is_system,
            "type": "system" if is_system else msg_type,
            "is_removed": bool(c.get("removed_at")),
            "removed_at": _as_text(c.get("removed_at")),
            "removed_by": _removed_by(c.get("removed_by"), profile_map),
        }
        chats.append(item)

    return {
        "id": str(event.get("id") or event_id),
        "title": event.get("title") or "",
        "category": event.get("category"),
        "description": event.get("description"),
        "date": _as_text(event.get("start_datetime")),
        "start_datetime": _as_text(event.get("start_datetime")),
        "end_datetime": _as_text(event.get("end_datetime")),
        "location_name": event.get("location_name"),
        "latitude": event.get("latitude"),
        "longitude": event.get("longitude"),
        "cost": float(event.get("cost") or 0),
        "max_capacity": event.get("max_capacity"),
        "status": event.get("status"),
        "is_cancelled": is_canc,
        "cancellation_reason": event.get("cancellation_reason"),
        "organizer": organizer,
        "participant_count": len(participants),
        "participants": participants,
        "chats": chats,
        "chat": chats,
        "banner": event.get("banner_url"),
        "banner_url": event.get("banner_url"),
        "is_removed": bool(event.get("removed_at")),
        "removed_at": _as_text(event.get("removed_at")),
        "removed_by": removed_by,
    }

def end_upcoming_activity(user_id: str, cancellation_reason: str, notification_text: str) -> tuple[int, int]:
    """
    Shared by "make administrator" (#190) and "suspend" (#192):
    cancels the user's upcoming organized events (reason recorded, participants notified
    and emailed; a cancelled event's chat is read-only) and removes the user from upcoming
    events they joined. Past events are not touched.
    notification_text may contain {title}.
    Returns (cancelled_events_count, joined_events_removed_count).
    """
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    # a. Cancel upcoming events organized by this user
    cancelled_events_count = 0
    try:
        org_events_res = (
            supabase.table("events")
            .select("id, title, start_datetime, status, removed_at")
            .eq("created_by", user_id)
            .neq("status", "cancelled")
            .execute()
        )
        for ev in (org_events_res.data or []):
            if ev.get("removed_at"):
                continue  # an event an administrator removed (#236) is not cancelled on top of that
            start_dt = _parse_iso_datetime(ev.get("start_datetime"))
            if start_dt and start_dt >= now_dt:
                ev_id = ev["id"]
                supabase.table("events").update({
                    "status": "cancelled",
                    "cancellation_reason": cancellation_reason,
                    "updated_at": now_iso
                }).eq("id", ev_id).execute()

                cancelled_events_count += 1

                # Send notifications to participants
                try:
                    from app.services.notification_service import create_notification
                    part_res = (
                        supabase.table("event_participants")
                        .select("user_id")
                        .eq("event_id", ev_id)
                        .execute()
                    )
                    for p in (part_res.data or []):
                        if p.get("user_id") and p["user_id"] != user_id:
                            create_notification(
                                p["user_id"],
                                ev_id,
                                "event_cancelled",
                                notification_text.format(title=ev.get("title"))
                            )
                except Exception as n_err:
                    logger.warning(f"Failed to notify participants for cancelled event {ev_id}: {n_err}")

                try:
                    from app.services.event_service import _email_participants
                    _email_participants(ev, "cancellation")
                except Exception as em_err:
                    logger.warning(f"Failed to email participants for cancelled event {ev_id}: {em_err}")
    except Exception as e:
        logger.error(f"Error cancelling organized events for user {user_id}: {e}")

    # b. Take them off upcoming events they joined
    joined_events_removed_count = 0
    try:
        joined_res = (
            supabase.table("event_participants")
            .select("id, event_id")
            .eq("user_id", user_id)
            .execute()
        )
        joined_rows = joined_res.data or []
        if joined_rows:
            ev_ids = [r["event_id"] for r in joined_rows if r.get("event_id")]
            if ev_ids:
                events_info = (
                    supabase.table("events")
                    .select("id, start_datetime")
                    .in_("id", ev_ids)
                    .execute()
                ).data or []
                upcoming_event_ids = {
                    e["id"] for e in events_info
                    if _parse_iso_datetime(e.get("start_datetime")) and _parse_iso_datetime(e.get("start_datetime")) >= now_dt
                }
                for r in joined_rows:
                    if r.get("event_id") in upcoming_event_ids:
                        supabase.table("event_participants").delete().eq("id", r["id"]).execute()
                        joined_events_removed_count += 1
    except Exception as e:
        logger.error(f"Error removing joined events for user {user_id}: {e}")

    return cancelled_events_count, joined_events_removed_count

def grant_admin_role(target_user_id: str, admin_user_id: str) -> dict:
    """
    Grants the administrator role to an account that is not an administrator,
    ending everything active in that account and recording the audit log.
    Refuses if the account already is an administrator.
    Offers no way to remove the administrator role.
    """
    cleaned_user_id = str(target_user_id or "").strip().strip("{}")
    if not cleaned_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # 1. Fetch target user
    prof_res = None
    try:
        prof_res = (
            supabase.table("profiles")
            .select("id, role, username, full_name, avatar_url, avatar_kind, icon_id")
            .eq("id", cleaned_user_id)
            .single()
            .execute()
        )
    except Exception as e:
        logger.debug(f"Target lookup by id failed for {cleaned_user_id}: {e}")
        try:
            prof_res = (
                supabase.table("profiles")
                .select("id, role, username, full_name, avatar_url, avatar_kind, icon_id")
                .eq("username", cleaned_user_id)
                .single()
                .execute()
            )
        except Exception as e2:
            logger.debug(f"Target lookup by username failed for {cleaned_user_id}: {e2}")

    if not prof_res or not prof_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    prof_data = prof_res.data[0] if isinstance(prof_res.data, list) and prof_res.data else (prof_res.data or {})
    actual_target_id = prof_data.get("id")
    current_role = prof_data.get("role")
    if current_role in ("administrator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already an administrator."
        )

    # Re-assert service role header on postgrest client
    try:
        from app.core.config import settings
        if settings.SUPABASE_SERVICE_KEY and hasattr(supabase, "postgrest"):
            supabase.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
    except Exception as e:
        logger.warning(f"Could not re-assert service key on postgrest client: {e}")

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

        # 2.-3. Cancel upcoming organized events and leave upcoming joined events
    cancelled_events_count, joined_events_removed_count = end_upcoming_activity(
        actual_target_id,
        cancellation_reason="Organizer was made an administrator",
        notification_text="Event '{title}' was cancelled because organizer was made an administrator",
    )

    # 4. Delete friends in both directions
    try:
        supabase.table("friendships").delete().eq("user_id", actual_target_id).execute()
        supabase.table("friendships").delete().eq("friend_id", actual_target_id).execute()
    except Exception as e:
        logger.error(f"Error deleting friendships for user {actual_target_id}: {e}")

    # 5. Delete pending friend requests in both directions
    try:
        supabase.table("friend_requests").delete().eq("initiator_id", actual_target_id).execute()
        supabase.table("friend_requests").delete().eq("receiver_id", actual_target_id).execute()
    except Exception as e:
        logger.error(f"Error deleting friend requests for user {actual_target_id}: {e}")

    # 6. Delete blocks in both directions
    try:
        supabase.table("user_blocks").delete().eq("blocker_id", actual_target_id).execute()
        supabase.table("user_blocks").delete().eq("blocked_id", actual_target_id).execute()
    except Exception as e:
        logger.error(f"Error deleting blocks for user {actual_target_id}: {e}")

    # 7. Delete favourites (saved_events)
    try:
        supabase.table("saved_events").delete().eq("user_id", actual_target_id).execute()
    except Exception as e:
        logger.error(f"Error deleting saved events for user {actual_target_id}: {e}")

    # 8. Delete notifications
    try:
        supabase.table("notifications").delete().eq("user_id", actual_target_id).execute()
        supabase.table("notifications").delete().eq("actor_id", actual_target_id).execute()
    except Exception as e:
        logger.error(f"Error deleting notifications for user {actual_target_id}: {e}")

    # 9. Defensively delete warnings
    try:
        supabase.table("warnings").delete().eq("user_id", actual_target_id).execute()
    except Exception:
        pass

    # 10. Purge profile data, retaining only profile picture, full name and username
    try:
        profile_update = {
            "role": "administrator",
            "admin_since": now_iso,
            "bio": None,
            "interests": None,
            "phone": None,
            "gender": None,
            "banner_url": None,
            "latitude": None,
            "longitude": None,
            "dob": None,
            "tier_id": None,
            "visibility": "public",
            "profile_status": None,
            "is_verified": False,
            "updated_at": now_iso,
        }
        supabase.table("profiles").update(profile_update).eq("id", actual_target_id).execute()
    except Exception as e:
        logger.error(f"Failed to update profile to administrator for {actual_target_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to grant administrator role.")

    # 11. End their sessions at once
    try:
        from app.core.config import settings
        import requests
        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
            logout_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{actual_target_id}/logout"
            headers = {
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                "apikey": settings.SUPABASE_SERVICE_KEY,
            }
            requests.post(logout_url, headers=headers, timeout=5)
    except Exception as e:
        logger.warning(f"Could not revoke sessions for user {actual_target_id}: {e}")

    # 12. Record in audit log
    summary_dict = {
        "cancelled_events_count": cancelled_events_count,
        "joined_events_removed_count": joined_events_removed_count,
        "friendships_deleted": True,
        "friend_requests_deleted": True,
        "blocks_deleted": True,
        "saved_events_deleted": True,
        "notifications_deleted": True,
        "profile_purged": True,
    }
    try:
        audit_entry = {
            "type": "make_admin",
            "description": f"User {actual_target_id} was made an administrator. Cancelled {cancelled_events_count} upcoming events, removed from joined upcoming events, and purged user profile data.",
            "created_by_id": admin_user_id,
            "entity_id": str(actual_target_id),
            "values": [f"{k}:{v}" for k, v in summary_dict.items()],
            "created_date": now_iso,
        }
        supabase.table("logs").insert(audit_entry).execute()
    except Exception as e:
        logger.warning(f"Could not write audit log for user {actual_target_id}: {e}")

    return {
        "message": "User made administrator successfully.",
        "user_id": actual_target_id,
        "role": "administrator",
        "admin_since": now_iso,
        "summary": summary_dict,
    }
