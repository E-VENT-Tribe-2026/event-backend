import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException

from app.db.supabase_client import supabase


logger = logging.getLogger(__name__)

HISTORY_LIMIT = 40
USER_CONTENT_LIMIT = 2000
ASSISTANT_CONTENT_LIMIT = 12000


def list_history(user_id: str) -> dict[str, Any]:
    """Return the signed-in user's latest conversation, newest messages last."""
    try:
        latest = _latest_conversation(user_id)
        if not latest:
            return {"conversation_id": None, "messages": []}
        response = (
            supabase.table("ai_messages")
            .select("id, role, content, metadata, created_at")
            .eq("conversation_id", latest["id"])
            .order("created_at", desc=True)
            .limit(HISTORY_LIMIT)
            .execute()
        )
    except Exception:
        logger.exception("Could not load assistant history")
        raise HTTPException(status_code=503, detail="Chat history is temporarily unavailable.") from None

    messages = []
    for row in _in_conversation_order(_rows(response)):
        message = _public_message(row)
        if message:
            messages.append(message)
    return {"conversation_id": str(latest["id"]), "messages": messages}


def start_conversation(user_id: str) -> dict[str, str]:
    """Open a fresh conversation. An empty latest conversation is reused."""
    try:
        latest = _latest_conversation(user_id)
        if latest and not _has_messages(latest["id"]):
            _touch(latest["id"])
            return {"conversation_id": str(latest["id"])}
        created = _insert_conversation(user_id, "New chat")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Could not start a new assistant conversation")
        raise HTTPException(status_code=503, detail="Could not start a new chat.") from None
    return {"conversation_id": created}


def record_exchange(user_id: str, user_text: str, assistant_text: str, metadata: Any = None) -> None:
    """Append one completed turn. A storage failure must not fail the reply."""
    user_content = _clip("user", user_text)
    assistant_content = _clip("assistant", assistant_text)
    if not user_id or not user_content or not assistant_content:
        return
    try:
        latest = _latest_conversation(user_id)
        conversation_id = latest["id"] if latest else _insert_conversation(user_id, _title(user_content))
        sent_at = datetime.now(timezone.utc)
        supabase.table("ai_messages").insert(
            [
                {
                    "conversation_id": conversation_id,
                    "role": "user",
                    "content": user_content,
                    "metadata": {},
                    "created_at": sent_at.isoformat(),
                },
                {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": assistant_content,
                    "metadata": _card_metadata(metadata),
                    "created_at": (sent_at + timedelta(milliseconds=1)).isoformat(),
                },
            ]
        ).execute()
        _touch(conversation_id)
    except Exception:
        logger.exception("Could not store the assistant turn")


def _latest_conversation(user_id: str) -> Optional[dict[str, Any]]:
    _require_client()
    response = (
        supabase.table("ai_conversations")
        .select("id")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = _rows(response)
    return rows[0] if rows else None


def _has_messages(conversation_id: str) -> bool:
    response = (
        supabase.table("ai_messages")
        .select("id")
        .eq("conversation_id", conversation_id)
        .limit(1)
        .execute()
    )
    return bool(_rows(response))


def _insert_conversation(user_id: str, title: str) -> str:
    response = (
        supabase.table("ai_conversations")
        .insert({"user_id": user_id, "title": title})
        .execute()
    )
    rows = _rows(response)
    conversation_id = rows[0].get("id") if rows else None
    if not conversation_id:
        raise HTTPException(status_code=503, detail="Could not start a new chat.")
    return str(conversation_id)


def _touch(conversation_id: str) -> None:
    supabase.table("ai_conversations").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", conversation_id).execute()


def _require_client() -> None:
    if supabase is None:
        raise RuntimeError("Supabase client is not configured")


def _in_conversation_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Oldest first. A user line stays before the reply when both share a timestamp."""

    def sort_key(row: dict[str, Any]) -> tuple:
        role = row.get("role")
        role_rank = 0 if role == "user" else 1
        return (str(row.get("created_at") or ""), role_rank)

    return sorted(rows, key=sort_key)


def _rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _public_message(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    role = row.get("role")
    if role not in {"user", "assistant"}:
        return None
    content = _clip(role, row.get("content"))
    if not content or row.get("id") is None:
        return None
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    created_at = row.get("created_at")
    return {
        "id": str(row["id"]),
        "role": role,
        "content": content,
        "created_at": None if created_at is None else str(created_at),
        "metadata": metadata,
    }


def _clip(role: str, content: Any) -> str:
    if not isinstance(content, str):
        return ""
    limit = USER_CONTENT_LIMIT if role == "user" else ASSISTANT_CONTENT_LIMIT
    return content.strip()[:limit]


def _title(user_content: str) -> str:
    compact = " ".join(user_content.split())
    return compact[:80] or "New chat"


def _card_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    stored: dict[str, Any] = {}
    kind = metadata.get("type")
    if kind == "event_search_results" and isinstance(metadata.get("events"), list):
        stored["type"] = kind
        stored["events"] = metadata["events"]
    elif kind == "event_details_card" and isinstance(metadata.get("event"), dict):
        stored["type"] = kind
        stored["event"] = metadata["event"]
    elif kind == "draft_event_preview" and isinstance(metadata.get("draft"), dict):
        stored["type"] = kind
        stored["draft"] = metadata["draft"]
        issues = metadata.get("validation_issues")
        if isinstance(issues, list):
            stored["validation_issues"] = [str(issue) for issue in issues if str(issue).strip()]
    try:
        cleaned = json.loads(json.dumps(stored, default=str))
    except (TypeError, ValueError):
        return {}
    return cleaned if isinstance(cleaned, dict) else {}
