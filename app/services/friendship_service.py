import logging
import uuid
from fastapi import HTTPException
from app.db.supabase_client import supabase
from app.services.profile_service import (
    USER_SUMMARY_COLUMNS,
    build_user_summary,
    get_user_summaries,
    get_username,
)
from app.services.notification_service import create_notification, delete_notifications_for
from app.services.block_visibility import get_hidden_user_ids, has_blocked
from app.utils.embedding_helper import cosine_similarity, generate_embedding, parse_embedding

logger = logging.getLogger(__name__)

FRIEND_REQUEST_RECEIVED = "friend_request_received"
FRIEND_REQUEST_ACCEPTED = "friend_request_accepted"
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
REQUEST_COLUMNS = "id, initiator_id, receiver_id, status, created_at"
FRIENDSHIP_COLUMNS = "id, user_id, friend_id, created_at"
SUGGESTION_COLUMNS = f"{USER_SUMMARY_COLUMNS}, interest_embedding"


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

    # A user who was blocked gets the same answer as for a user that does not exist.
    if has_blocked(receiver_id, sender_id):
        raise friend_error(404, "user_not_found", "User not found.")
    if has_blocked(sender_id, receiver_id):
        raise friend_error(403, "user_blocked", "You blocked this user. Unblock them to send a friend request.")

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
        # Lost a race with a concurrent request or accept (the database rejects a
        # pending request between friends with 23505): map it to the matching 409
        # if the state now shows a conflict, otherwise re-raise the original error.
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


def _rpc_unavailable(exc: Exception) -> bool:
    """True when accept_friend_request() is missing or cannot return a matching row type."""
    text = str(exc)
    code = str(getattr(exc, "code", "") or "")
    return (
        code in {"PGRST202", "PGRST203", "42883", "42804"}
        or "PGRST202" in text
        or "PGRST203" in text
        or "schema cache" in text
        or "Could not find the function" in text
        or "structure of query does not match function result type" in text
        or "undefined function" in text.lower()
    )


def _first_rpc_row(data):
    """PostgREST may return a table as a list or a single composite as a dict."""
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _parse_accept_row(row: dict) -> dict:
    """Read the RPC result whether it used RETURNS TABLE names or friendship columns."""
    if not isinstance(row, dict):
        raise TypeError("accept_friend_request RPC row is not an object")
    friend_since = row.get("friend_since") or row.get("created_at")
    if friend_since is None:
        raise ValueError("accept_friend_request RPC row missing friend_since")
    created = row.get("created")
    if created is None:
        created = True
    elif isinstance(created, str):
        created = created.strip().lower() in {"true", "t", "1", "yes"}
    return {"friend_since": friend_since, "created": bool(created)}


def _accept_via_tables(request_id: int, user_id: str, row: dict) -> dict:
    """Delete the request and insert the friendship when the atomic RPC is unavailable."""
    _claim_request(request_id, "receiver_id", row["receiver_id"])

    already_friends = False
    try:
        resp = (
            supabase.table("friendships")
            .insert({
                "user_id": row["initiator_id"],
                "friend_id": row["receiver_id"],
                "origin": row["initiator_id"],
                "status": "active",
            })
            .execute()
        )
        if not resp.data:
            raise RuntimeError("friendship insert returned no row")
        friendship = _first_rpc_row(resp.data)
        if not friendship:
            raise RuntimeError("friendship insert returned no row")
    except Exception as e:
        if not _is_unique_violation(e):
            logger.error("Friendship insert failed on accept: request_id=%s initiator=%s receiver=%s",
                         request_id, row["initiator_id"], row["receiver_id"], exc_info=True)
            _restore_request(row)
            raise
        friendship = _find_friendship(row["initiator_id"], row["receiver_id"])
        if not friendship:
            raise
        already_friends = True

    return {
        "friend_since": friendship.get("friend_since") or friendship["created_at"],
        "created": not already_friends,
    }


def _accept_atomically(request_id: int, user_id: str, row: dict) -> dict:
    """Prefer the transactional RPC; fall back to table writes if it is not deployed."""
    try:
        resp = supabase.rpc("accept_friend_request", {
            "p_request_id": request_id,
            "p_receiver_id": _uuid(user_id),
        }).execute()
    except Exception as e:
        if not _rpc_unavailable(e):
            raise
        logger.warning(
            "accept_friend_request RPC unavailable, using table fallback: request_id=%s receiver=%s error=%s",
            request_id, user_id, e,
        )
        return _accept_via_tables(request_id, user_id, row)

    parsed = _first_rpc_row(getattr(resp, "data", None))
    if not parsed:
        raise friend_error(404, "request_not_found", "Friend request not found.")
    try:
        return _parse_accept_row(parsed)
    except (TypeError, ValueError):
        logger.error("accept_friend_request RPC returned an unexpected row: %s", parsed, exc_info=True)
        friendship = _find_friendship(row["initiator_id"], row["receiver_id"])
        if friendship:
            return {"friend_since": friendship["created_at"], "created": True}
        raise friend_error(404, "request_not_found", "Friend request not found.")


def cancel_friend_request(request_id: int, user_id: str) -> dict:
    """Cancel a pending request the user sent."""
    row = _load_pending_request(request_id, user_id)
    if _norm(user_id) != _norm(row["initiator_id"]):
        raise friend_error(403, "not_request_sender", "Only the sender can cancel this friend request.")

    _claim_request(request_id, "initiator_id", user_id)
    _cleanup_request_notification(row, "cancel")
    return {"message": "Friend request cancelled"}


def accept_friend_request(request_id: int, user_id: str) -> dict:
    """Accept a pending request addressed to the user and create the friendship."""
    row = _load_pending_request(request_id, user_id)
    if _norm(user_id) != _norm(row["receiver_id"]):
        raise friend_error(403, "not_request_receiver",
                           "Only the recipient can accept or decline this friend request.")

    initiator = str(row["initiator_id"])
    receiver = str(row["receiver_id"])

    # Deletes the request and creates the friendship in one transaction, under a
    # per-pair lock shared with request inserts, so no pending request can appear
    # between the two steps. Falls back to table writes if the SQL function is
    # missing (undeployed migration / schema cache) or cannot return its row type.
    friendship = _accept_atomically(request_id, user_id, row)

    _cleanup_request_notification(row, "accept")

    if friendship["created"]:
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
        "friend_since": friendship["friend_since"],
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


def get_friend_ids(user_id: str) -> list:
    """Return the ids of all of the user's friends."""
    uid = _uuid(user_id)
    resp = (
        supabase.table("friendships")
        .select("user_id, friend_id")
        .or_(f"user_id.eq.{uid},friend_id.eq.{uid}")
        .execute()
    )
    return [
        row["friend_id"] if _norm(row["user_id"]) == _norm(uid) else row["user_id"]
        for row in resp.data or []
    ]


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


def _viewer_interest_embedding(user_id: str) -> list[float] | None:
    """Interest vector for k-NN: stored embedding, else one generated from interests/bio."""
    resp = (
        supabase.table("profiles")
        .select("interests, bio, interest_embedding")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    profile = (resp.data or [None])[0] or {}
    embedding = parse_embedding(profile.get("interest_embedding"))
    if embedding:
        return embedding
    interests = profile.get("interests") or []
    bio = profile.get("bio") or ""
    text = (" ".join(interests) + " " + bio).strip()
    return generate_embedding(text) if text else None


def _knn_sort_key(query: list[float] | None, row: dict) -> tuple:
    """Nearest first (higher cosine), then id. Profiles with no comparable vector go last."""
    parsed = parse_embedding(row.get("interest_embedding"))
    similarity = cosine_similarity(query, parsed) if query and parsed else None
    if similarity is None:
        return (1, 0.0, str(row.get("id") or ""))
    return (0, -similarity, str(row.get("id") or ""))


def get_friend_suggestions(user_id: str, page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """Return the k nearest eligible users, ranked by interest-embedding cosine similarity.

    Eligible means not the current user, not already friends, no pending request either
    way, and not hidden by a block. `limit` is k for the page; later pages continue the
    same nearest-neighbor order.
    """
    uid = _uuid(user_id)
    start = (page - 1) * limit

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

    excluded = friend_ids | pending_ids | get_hidden_user_ids(uid) | {_norm(uid)}
    query_embedding = _viewer_interest_embedding(uid)

    candidates = supabase.table("profiles").select(SUGGESTION_COLUMNS)
    if excluded:
        candidates = candidates.not_.in_("id", list(excluded))
    rows = [
        row for row in (candidates.execute().data or [])
        if _norm(row.get("id")) not in excluded
    ]

    ranked = sorted(rows, key=lambda row: _knn_sort_key(query_embedding, row))
    window, has_more = _page(ranked[start:start + limit + 1], limit)
    return {
        "page": page,
        "limit": limit,
        "has_more": has_more,
        "data": [{"user": build_user_summary(row)} for row in window],
    }
