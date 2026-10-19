"""Blocking users (ticket #184).

Blocking ends the friendship and every pending friend request between the two users, and
clears the event invitations between them (#186). The blocked user is never notified.
Hiding rules for profiles, search, friend requests and events live where those are served,
based on app.services.block_visibility.
"""
import logging

from fastapi import HTTPException

from app.db.supabase_client import supabase
from app.services.block_visibility import BLOCKS_TABLE
from app.services.friendship_service import (
    DEFAULT_PAGE_LIMIT,
    FRIEND_REQUEST_RECEIVED,
    _norm,
    _page,
    _pair_filter,
    _uuid,
)
from app.services.invitation_service import remove_invitations_for_block
from app.services.notification_service import delete_notifications_for
from app.services.profile_service import get_user_summaries

logger = logging.getLogger(__name__)


def block_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _remove_relationship(a: str, b: str) -> None:
    """Delete the friendship and all pending friend requests between two users, silently."""
    supabase.table("friendships").delete().or_(_pair_filter(a, b, "user_id", "friend_id")).execute()
    removed = (
        supabase.table("friend_requests")
        .delete()
        .eq("status", "pending")
        .or_(_pair_filter(a, b, "initiator_id", "receiver_id"))
        .execute()
    )
    for row in removed.data or []:
        try:
            delete_notifications_for(row["receiver_id"], FRIEND_REQUEST_RECEIVED, row["initiator_id"])
        except Exception:
            logger.error("Failed to clean up friend request notification on block: request_id=%s",
                         row.get("id"), exc_info=True)


def block_user(blocker_id: str, blocked_id: str) -> dict:
    """Block a user. Safe to repeat: the cleanup runs again and the same result is returned."""
    if _norm(blocker_id) == _norm(blocked_id):
        raise block_error(400, "cannot_block_self", "You cannot block yourself.")

    target = supabase.table("profiles").select("id").eq("id", blocked_id).limit(1).execute()
    if not target.data:
        raise block_error(404, "user_not_found", "User not found.")

    # Record the block first, so friend requests are refused even if the cleanup is interrupted.
    resp = (
        supabase.table(BLOCKS_TABLE)
        .upsert({"blocker_id": blocker_id, "blocked_id": blocked_id}, on_conflict="blocker_id,blocked_id")
        .execute()
    )
    row = (resp.data or [{}])[0]

    _remove_relationship(blocker_id, blocked_id)
    try:
        remove_invitations_for_block(blocker_id, blocked_id)
    except Exception:
        logger.error("Failed to remove invitations on block: blocker=%s blocked=%s",
                     blocker_id, blocked_id, exc_info=True)

    return {
        "blocked_at": row.get("created_at"),
        "user": get_user_summaries([blocked_id])[blocked_id],
    }


def unblock_user(blocker_id: str, blocked_id: str) -> dict:
    """Unblock a user the caller blocked. Does not restore a friendship."""
    try:
        _uuid(blocked_id)
    except ValueError:
        raise block_error(404, "block_not_found", "You have not blocked this user.")
    resp = (
        supabase.table(BLOCKS_TABLE)
        .delete()
        .eq("blocker_id", blocker_id)
        .eq("blocked_id", blocked_id)
        .execute()
    )
    if not resp.data:
        raise block_error(404, "block_not_found", "You have not blocked this user.")
    return {"message": "User unblocked"}


def get_blocked_users(user_id: str, page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """The users the caller blocked, newest first."""
    start = (page - 1) * limit
    resp = (
        supabase.table(BLOCKS_TABLE)
        .select("blocked_id, created_at")
        .eq("blocker_id", _uuid(user_id))
        .order("created_at", desc=True)
        .order("blocked_id", desc=True)
        .range(start, start + limit)
        .execute()
    )
    rows, has_more = _page(resp.data or [], limit)
    summaries = get_user_summaries([r["blocked_id"] for r in rows]) if rows else {}
    data = [{"blocked_at": r["created_at"], "user": summaries[r["blocked_id"]]} for r in rows]
    return {"page": page, "limit": limit, "has_more": has_more, "data": data}
