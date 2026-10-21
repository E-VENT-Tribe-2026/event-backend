"""The audit log: every action administrators take in the panel (table `logs`).

Keeps the row shape grant_admin_role already writes:
type, description, created_by_id, entity_id, values, created_date (+ entity_type, #191).
"""
import logging
from datetime import datetime, timezone

from app.db.supabase_client import supabase
from app.services.admin_service import _build_user_summary

logger = logging.getLogger(__name__)

AUDIT_PAGE_MAX = 100


def record_audit(action: str, admin_id: str, entity_type: str, entity_id: str,
                 description: str, details: dict | None = None) -> None:
    """Write one audit entry. A failure is logged, never raised: the action itself already happened."""
    entry = {
        "type": action,
        "description": description,
        "created_by_id": admin_id,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "values": [f"{k}:{v}" for k, v in (details or {}).items()],
        "created_date": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table("logs").insert(entry).execute()
    except Exception as e:
        logger.error(f"Could not write audit log entry {action} for {entity_type} {entity_id}: {e}")


def _people(ids) -> dict:
    """Profile picture, full name and username (also for administrators) by id."""
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return {}
    res = (
        supabase.table("profiles")
        .select("id, username, full_name, avatar_url, avatar_kind, icon_id")
        .in_("id", ids)
        .execute()
    )
    return {row["id"]: _build_user_summary(row) for row in (res.data or [])}


def list_audit_log(before: str | None = None, limit: int = 20) -> dict:
    """Newest first. `before` is the next_before value of the previous page."""
    limit = max(1, min(AUDIT_PAGE_MAX, limit))

    query = supabase.table("logs").select("*")
    if before:
        query = query.lt("created_date", before)
    res = query.order("created_date", desc=True).limit(limit + 1).execute()

    rows = res.data or []
    has_more = len(rows) > limit
    rows = rows[:limit]

    user_target_ids = [r.get("entity_id") for r in rows if (r.get("entity_type") or "user") == "user"]
    people = _people([r.get("created_by_id") for r in rows] + user_target_ids)

    items = []
    for r in rows:
        entity_type = r.get("entity_type") or "user"   # older rows (make_admin) have no entity_type
        entity_id = r.get("entity_id")
        items.append({
            "id": str(r["id"]) if r.get("id") is not None else None,
            "created_at": r.get("created_date"),
            "action": r.get("type") or "",
            "administrator": people.get(r.get("created_by_id")),
            "target": {
                "type": entity_type,
                "id": entity_id,
                "user": people.get(entity_id) if entity_type == "user" else None,
            },
            "description": r.get("description"),
            "details": r.get("values") or [],
        })

    return {
        "items": items,
        "has_more": has_more,
        "next_before": items[-1]["created_at"] if has_more and items else None,
    }