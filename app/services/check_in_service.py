import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.core.user_rate_limit import (
    CHECK_IN_WRONG_CODE_LIMIT,
    raise_if_user_rate_limited,
    record_user_rate_hit,
)
from app.db.supabase_client import supabase
from app.services.profile_service import get_user_summaries

logger = logging.getLogger(__name__)

CHECK_IN_WINDOW_BEFORE = timedelta(hours=3)
CHECK_IN_WINDOW_AFTER = timedelta(hours=12)
WRONG_CODE_DETAIL = "Too many incorrect check-in codes. Please wait a moment and try again."


def assign_event_check_in_secrets(data: dict) -> dict:
    """Give a new event its six-digit code. The QR code encodes that same code."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    data["check_in_code"] = code
    data["check_in_qr_content"] = code
    return data


def _parse_start(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_text(value) -> str | None:
    if value is None:
        return None
    return str(value)


def _normalize_code(*values: str | None) -> str:
    for value in values:
        if not value:
            continue
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if digits:
            return digits
    return ""


def _load_event(event_id: str) -> dict:
    res = (
        supabase.table("events")
        .select("id, title, status, start_datetime, created_by, check_in_code, check_in_qr_content")
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return rows[0]


def _participant_ids(event_id: str) -> list[str]:
    res = (
        supabase.table("event_participants")
        .select("user_id")
        .eq("event_id", event_id)
        .execute()
    )
    return [str(row["user_id"]) for row in (res.data or []) if row.get("user_id")]


def _is_participant(event_id: str, user_id: str) -> bool:
    return str(user_id) in _participant_ids(event_id)


def _is_organizer(event: dict, user_id: str) -> bool:
    return str(event.get("created_by") or "") == str(user_id)


def _in_check_in_window(event: dict) -> bool:
    start = _parse_start(event.get("start_datetime"))
    if start is None:
        return False
    now = datetime.now(timezone.utc)
    return (start - CHECK_IN_WINDOW_BEFORE) <= now <= (start + CHECK_IN_WINDOW_AFTER)


def get_event_check_in_code(event_id: str, user_id: str) -> dict:
    event = _load_event(event_id)
    if not _is_organizer(event, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organizer can see this event's check-in code.",
        )
    code = event.get("check_in_code") or ""
    qr_content = event.get("check_in_qr_content") or code
    return {
        "event_id": str(event["id"]),
        "code": code,
        "qr_content": qr_content,
    }


def check_in(event_id: str, user_id: str, code: str | None = None, qr_content: str | None = None) -> dict:
    event = _load_event(event_id)

    if str(event.get("status") or "").lower() == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This event is cancelled, so check-in is closed.",
        )

    if not _is_participant(event_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only participants of this event can check in.",
        )

    if not _in_check_in_window(event):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Check-in is only open from three hours before the event starts until twelve hours after it starts.",
        )

    existing = (
        supabase.table("event_check_ins")
        .select("checked_in_at")
        .eq("event_id", event_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return {
            "checked_in": True,
            "already_checked_in": True,
            "checked_in_at": _as_text(existing.data[0].get("checked_in_at")),
        }

    raise_if_user_rate_limited(
        "check_in_wrong_code",
        user_id,
        CHECK_IN_WRONG_CODE_LIMIT,
        bucket=str(event_id),
        detail=WRONG_CODE_DETAIL,
    )

    submitted = _normalize_code(code, qr_content)
    expected_code = _normalize_code(event.get("check_in_code"))
    expected_qr = _normalize_code(event.get("check_in_qr_content")) or expected_code
    if submitted != expected_code and submitted != expected_qr:
        record_user_rate_hit("check_in_wrong_code", user_id, bucket=str(event_id))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect check-in code.",
        )

    try:
        inserted = (
            supabase.table("event_check_ins")
            .insert({"event_id": event_id, "user_id": user_id})
            .execute()
        )
    except Exception as e:
        if "event_check_ins_one_per_participant" in str(e) or "duplicate" in str(e).lower():
            return {
                "checked_in": True,
                "already_checked_in": True,
                "checked_in_at": None,
            }
        logger.error(f"Check-in insert failed for event {event_id} user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not record check-in.",
        )
    row = (inserted.data or [{}])[0]
    return {
        "checked_in": True,
        "already_checked_in": False,
        "checked_in_at": _as_text(row.get("checked_in_at")),
    }


def list_event_check_ins(event_id: str, user_id: str) -> dict:
    event = _load_event(event_id)
    participant_ids = _participant_ids(event_id)
    is_organizer = _is_organizer(event, user_id)
    is_participant = str(user_id) in participant_ids

    if not is_organizer and not is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organizer and participants of this event can see who has checked in.",
        )

    res = (
        supabase.table("event_check_ins")
        .select("user_id, checked_in_at")
        .eq("event_id", event_id)
        .order("checked_in_at", desc=False)
        .execute()
    )
    rows = [
        row for row in (res.data or [])
        if str(row.get("user_id")) in set(participant_ids)
    ]
    summaries = get_user_summaries([row.get("user_id") for row in rows])
    include_times = is_organizer
    items = []
    for row in rows:
        uid = str(row.get("user_id"))
        item = {"user": summaries.get(uid) or {"id": uid}}
        if include_times:
            item["checked_in_at"] = _as_text(row.get("checked_in_at"))
        items.append(item)

    return {
        "event_id": str(event["id"]),
        "checked_in_count": len(items),
        "participant_count": len(participant_ids),
        "viewer_checked_in": str(user_id) in {str(row.get("user_id")) for row in rows},
        "include_times": include_times,
        "items": items,
    }
