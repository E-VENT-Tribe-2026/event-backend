import logging
import uuid
from fastapi import HTTPException
from app.db.supabase_client import supabase
from app.services.profile_service import get_user_summaries, get_username
from app.services.notification_service import create_notification, delete_notifications_for

logger = logging.getLogger(__name__)

FRIEND_REQUEST_RECEIVED = "friend_request_received"
FRIEND_REQUEST_ACCEPTED = "friend_request_accepted"
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
REQUEST_COLUMNS = "id, initiator_id, receiver_id, status, created_at"
FRIENDSHIP_COLUMNS = "id, user_id, friend_id, created_at"


def friend_error(status_code: int, code: str, message: str, request_id: int | None = None) -> HTTPException:
    """Build an HTTPException with a structured friendship error detail."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "request_id": request_id},
    )


def _norm(value) -> str:
    return str(value).strip().lower()


def _is_unique_violation(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "23505" or "23505" in str(exc)


def _uuid(value) -> str:
    """Return the canonical form of a uuid, raising ValueError for anything else."""
    return str(uuid.UUID(str(value)))


def _pair_filter(a, b, col_a: str, col_b: str) -> str:
    a, b = _uuid(a), _uuid(b)
    return f"and({col_a}.eq.{a},{col_b}.eq.{b}),and({col_a}.eq.{b},{col_b}.eq.{a})"


def _find_friendship(a, b) -> dict | None:
    """Return the friendship row between two users (either direction), if any."""
    resp = (
        supabase.table("friendships")
        .select(FRIENDSHIP_COLUMNS)
        .or_(_pair_filter(a, b, "user_id", "friend_id"))
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _find_pending_request(a, b) -> dict | None:
    """Return the pending friend request between two users (either direction), if any."""
    resp = (
        supabase.table("friend_requests")
        .select(REQUEST_COLUMNS)
        .eq("status", "pending")
        .or_(_pair_filter(a, b, "initiator_id", "receiver_id"))
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _load_pending_request(request_id: int, user_id: str) -> dict:
    """Load a pending request the user is part of, otherwise raise 404."""
    resp = (
        supabase.table("friend_requests")
        .select(REQUEST_COLUMNS)
        .eq("id", request_id)
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    row = resp.data[0] if resp.data else None
    if not row or _norm(user_id) not in (_norm(row["initiator_id"]), _norm(row["receiver_id"])):
        raise friend_error(404, "request_not_found", "Friend request not found.")
    return row


def _raise_for_state(state: dict) -> None:
    """Raise the matching 409 when a conflict exists; return None only when the state is 'none'."""
    status = state["status"]
    request_id = state.get("request_id")
    if status == "friends":
        raise friend_error(409, "already_friends", "You are already friends with this user.")
    if status == "request_sent":
        raise friend_error(409, "request_already_sent",
                           "You have already sent this user a friend request.", request_id)
    if status == "request_received":
        raise friend_error(409, "request_already_received",
                           "This user has already sent you a friend request.", request_id)


def get_friendship_state(viewer_id: str, other_id: str) -> dict:
    """Describe the relationship between the viewer and another user."""
    if _norm(viewer_id) == _norm(other_id):
        return {"status": "self", "request_id": None}

    try:
        _uuid(other_id)
    except ValueError:
        return {"status": "none", "request_id": None}

    if _find_friendship(viewer_id, other_id):
        return {"status": "friends", "request_id": None}

    pending = _find_pending_request(viewer_id, other_id)
    if pending:
        is_sender = _norm(pending["initiator_id"]) == _norm(viewer_id)
        return {
            "status": "request_sent" if is_sender else "request_received",
            "request_id": pending["id"],
        }

    return {"status": "none", "request_id": None}


def send_friend_request(sender_id: str, receiver_id: str) -> dict:
    """Send a friend request and notify the receiver."""
    if _norm(sender_id) == _norm(receiver_id):
        raise friend_error(400, "cannot_friend_self", "You cannot send a friend request to yourself.")

    profile = supabase.table("profiles").select("id").eq("id", receiver_id).limit(1).execute()
    if not profile.data:
        raise friend_error(404, "user_not_found", "User not found.")

    _raise_for_state(get_friendship_state(sender_id, receiver_id))

    try:
        resp = (
            supabase.table("friend_requests")
            .insert({"initiator_id": sender_id, "receiver_id": receiver_id, "status": "pending"})
            .execute()
        )
    except Exception as e:
        if not _is_unique_violation(e):
            raise
        # Lost a race with a concurrent request: map it to the matching 409 if the
        # state now shows a conflict, otherwise re-raise the original error.
        _raise_for_state(get_friendship_state(sender_id, receiver_id))
        raise

    if not resp.data:
        logger.error("Friend request insert returned no row: initiator=%s receiver=%s",
                     sender_id, receiver_id)
        raise RuntimeError("friend request insert returned no row")
    row = resp.data[0]

    try:
        create_notification(
            receiver_id, None, FRIEND_REQUEST_RECEIVED,
            f"{get_username(sender_id)} sent you a friend request",
            related_user_id=sender_id,
        )
    except Exception:
        logger.error("Failed to create friend request notification on send: request_id=%s initiator=%s receiver=%s",
                     row["id"], sender_id, receiver_id, exc_info=True)

    return {
        "request_id": row["id"],
        "created_at": row["created_at"],
        "user": get_user_summaries([receiver_id])[receiver_id],
    }


def _claim_request(request_id: int, role_column: str, user_id: str) -> dict:
    """Atomically delete a pending request the user holds in role_column, else raise 404."""
    resp = (
        supabase.table("friend_requests")
        .delete()
        .eq("id", request_id)
        .eq(role_column, user_id)
        .eq("status", "pending")
        .execute()
    )
    if not resp.data:
        raise friend_error(404, "request_not_found", "Friend request not found.")
    return resp.data[0]


def _cleanup_request_notification(row: dict, context: str):
    """Remove the receiver's friend-request notification, never failing the caller."""
    try:
        delete_notifications_for(row["receiver_id"], FRIEND_REQUEST_RECEIVED, row["initiator_id"])
    except Exception:
        logger.error("Failed to clean up friend request notification on %s: request_id=%s initiator=%s receiver=%s",
                     context, row["id"], row["initiator_id"], row["receiver_id"], exc_info=True)


def cancel_friend_request(request_id: int, user_id: str) -> dict:
    """Cancel a pending request the user sent."""
    row = _load_pending_request(request_id, user_id)
    if _norm(user_id) != _norm(row["initiator_id"]):
        raise friend_error(403, "not_request_sender", "Only the sender can cancel this friend request.")

    _claim_request(request_id, "initiator_id", user_id)
    _cleanup_request_notification(row, "cancel")
    return {"message": "Friend request cancelled"}


def _restore_request(row: dict):
    """Re-insert a claimed request after a failed follow-up step."""
    try:
        supabase.table("friend_requests").insert({
            "id": row["id"],
            "initiator_id": row["initiator_id"],
            "receiver_id": row["receiver_id"],
            "status": "pending",
            "created_at": row["created_at"],
        }).execute()
    except Exception:
        logger.error("Failed to restore friend request on accept: request_id=%s initiator=%s receiver=%s",
                     row["id"], row["initiator_id"], row["receiver_id"], exc_info=True)


def accept_friend_request(request_id: int, user_id: str) -> dict:
    """Accept a pending request addressed to the user and create the friendship."""
    row = _load_pending_request(request_id, user_id)
    if _norm(user_id) != _norm(row["receiver_id"]):
        raise friend_error(403, "not_request_receiver",
                           "Only the recipient can accept or decline this friend request.")

    initiator = row["initiator_id"]
    receiver = row["receiver_id"]

    _claim_request(request_id, "receiver_id", user_id)

    already_friends = False
    try:
        resp = (
            supabase.table("friendships")
            .insert({"user_id": initiator, "friend_id": receiver, "origin": initiator, "status": "active"})
            .execute()
        )
        if not resp.data:
            raise RuntimeError("friendship insert returned no row")
        friendship = resp.data[0]
    except Exception as e:
        if not _is_unique_violation(e):
            logger.error("Friendship insert failed on accept: request_id=%s initiator=%s receiver=%s",
                         request_id, initiator, receiver, exc_info=True)
            _restore_request(row)
            raise
        # Friendship already exists (concurrent accept): reuse it, else re-raise the original error.
        friendship = _find_friendship(initiator, receiver)
        if not friendship:
            raise
        already_friends = True

    _cleanup_request_notification(row, "accept")

    if not already_friends:
        try:
            create_notification(
                initiator, None, FRIEND_REQUEST_ACCEPTED,
                f"{get_username(receiver)} accepted your friend request",
                related_user_id=receiver,
            )
        except Exception:
            logger.error("Failed to create friend accepted notification on accept: request_id=%s initiator=%s receiver=%s",
                         request_id, initiator, receiver, exc_info=True)

    return {
        "friend_since": friendship["created_at"],
        "user": get_user_summaries([initiator])[initiator],
    }


def decline_friend_request(request_id: int, user_id: str) -> dict:
    """Decline a pending request addressed to the user."""
    row = _load_pending_request(request_id, user_id)
    if _norm(user_id) != _norm(row["receiver_id"]):
        raise friend_error(403, "not_request_receiver",
                           "Only the recipient can accept or decline this friend request.")

    _claim_request(request_id, "receiver_id", user_id)
    _cleanup_request_notification(row, "decline")
    return {"message": "Friend request declined"}


def _page(rows: list, limit: int) -> tuple[list, bool]:
    """Trim a limit+1 fetch to limit rows and report whether more rows exist."""
    return rows[:limit], len(rows) > limit


def _list_requests(user_id: str, own_col: str, other_col: str, page: int, limit: int) -> dict:
    """Paginated pending requests where the user is own_col."""
    start = (page - 1) * limit
    resp = (
        supabase.table("friend_requests")
        .select(REQUEST_COLUMNS)
        .eq(own_col, user_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(start, start + limit)
        .execute()
    )
    rows, has_more = _page(resp.data or [], limit)

    summaries = get_user_summaries([r[other_col] for r in rows]) if rows else {}
    data = [
        {"request_id": r["id"], "created_at": r["created_at"], "user": summaries[r[other_col]]}
        for r in rows
    ]
    return {"page": page, "limit": limit, "has_more": has_more, "data": data}


def get_incoming_requests(user_id: str, page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """List pending requests received by the user."""
    return _list_requests(user_id, "receiver_id", "initiator_id", page, limit)


def get_sent_requests(user_id: str, page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """List pending requests sent by the user."""
    return _list_requests(user_id, "initiator_id", "receiver_id", page, limit)


def count_incoming_requests(user_id: str) -> dict:
    """Count pending requests received by the user."""
    resp = (
        supabase.table("friend_requests")
        .select("id", count="exact")
        .eq("receiver_id", user_id)
        .eq("status", "pending")
        .execute()
    )
    return {"count": resp.count or 0}


def get_friends(user_id: str, page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """List the user's friends, newest first."""
    start = (page - 1) * limit
    uid = _uuid(user_id)
    resp = (
        supabase.table("friendships")
        .select(FRIENDSHIP_COLUMNS)
        .or_(f"user_id.eq.{uid},friend_id.eq.{uid}")
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(start, start + limit)
        .execute()
    )
    rows, has_more = _page(resp.data or [], limit)

    others = [r["friend_id"] if _norm(r["user_id"]) == _norm(user_id) else r["user_id"] for r in rows]
    summaries = get_user_summaries(others) if others else {}
    data = [
        {"friend_since": r["created_at"], "user": summaries[other]}
        for r, other in zip(rows, others)
    ]
    return {"page": page, "limit": limit, "has_more": has_more, "data": data}


def remove_friend(user_id: str, friend_id: str) -> dict:
    """Remove an existing friendship."""
    try:
        _uuid(friend_id)
    except ValueError:
        raise friend_error(404, "friendship_not_found", "You are not friends with this user.")
    resp = (
        supabase.table("friendships")
        .delete()
        .or_(_pair_filter(user_id, friend_id, "user_id", "friend_id"))
        .execute()
    )
    if not resp.data:
        raise friend_error(404, "friendship_not_found", "You are not friends with this user.")
    return {"message": "Friend removed"}

def get_friend_suggestions(user_id: str, page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """Return paginated profiles that are not the current user, not already friends,
    and have no pending friend request (in either direction) with the current user."""
    uid = _uuid(user_id)
    start = (page - 1) * limit

    # --- 1. Collect IDs to exclude ---

    # Existing friends (one row per pair, either direction)
    fs_resp = (
        supabase.table("friendships")
        .select("user_id, friend_id")
        .or_(f"user_id.eq.{uid},friend_id.eq.{uid}")
        .execute()
    )
    friend_ids = set()
    for row in fs_resp.data or []:
        other = row["friend_id"] if _norm(row["user_id"]) == _norm(uid) else row["user_id"]
        friend_ids.add(_norm(other))

    # Pending requests (sent or received)
    rq_resp = (
        supabase.table("friend_requests")
        .select("initiator_id, receiver_id")
        .eq("status", "pending")
        .or_(f"initiator_id.eq.{uid},receiver_id.eq.{uid}")
        .execute()
    )
    pending_ids = set()
    for row in rq_resp.data or []:
        other = row["receiver_id"] if _norm(row["initiator_id"]) == _norm(uid) else row["initiator_id"]
        pending_ids.add(_norm(other))

    excluded = friend_ids | pending_ids | {_norm(uid)}

    # --- 2. Query profiles, excluding collected IDs ---
    base = supabase.table("profiles").select(
        "id, username, full_name, avatar_kind, icon_id, avatar_url",
        count="exact",
    )
    if excluded:
        base = base.not_.in_("id", list(excluded))

    count_resp = base.execute()
    total = count_resp.count or 0

    if total == 0:
        return {"page": page, "limit": limit, "has_more": False, "data": []}

    page_query = (
        supabase.table("profiles")
        .select("id, username, full_name, avatar_kind, icon_id, avatar_url")
        .order("id")
        .range(start, start + limit - 1)
    )
    if excluded:
        page_query = page_query.not_.in_("id", list(excluded))

    page_resp = page_query.execute()
    rows = page_resp.data or []
    has_more = (start + len(rows)) < total

    from app.services.profile_service import build_user_summary
    data = [{"user": build_user_summary(row)} for row in rows]
    return {"page": page, "limit": limit, "has_more": has_more, "data": data}
