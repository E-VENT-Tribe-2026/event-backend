import json
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding
from fastapi import HTTPException
from datetime import datetime, timezone
from app.services.block_visibility import filter_hidden_events
from app.services.removed_content import filter_removed_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_interests(value) -> list[str]:
    """Normalise interests from various storage formats (list, postgres array, json string, comma-separated string)."""
    if not value:
        return []
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if v is not None and str(v).strip()]
            except (ValueError, TypeError):
                pass
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
        return [part.strip().strip('"\'') for part in value.split(",") if part.strip().strip('"\'')]
    if isinstance(value, (list, tuple, set)):
        items = []
        for v in value:
            if v is not None:
                s = str(v).strip()
                if s:
                    items.append(s)
        return items
    return []


def _parse_embedding(value) -> list[float] | None:
    """Normalise an embedding coming out of Supabase.

    Supabase can return vector/jsonb columns as:
      - None          → return None
      - str  "[…]"   → parse JSON then cast every element to float
      - list […]     → cast every element to float
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    if not isinstance(value, (list, tuple)):
        return None
    try:
        parsed = [float(v) for v in value]
        return parsed if parsed else None
    except (ValueError, TypeError):
        return None


def _average_embeddings(embeddings: list[list[float]]) -> list[float] | None:
    if not embeddings:
        return None
    dim = len(embeddings[0])
    averaged = [0.0] * dim
    for emb in embeddings:
        for i, val in enumerate(emb):
            averaged[i] += val
    return [v / len(embeddings) for v in averaged]


def _blend_embeddings(
    sources: list[tuple[list[float] | None, float]],
) -> list[float] | None:
    valid = [(emb, w) for emb, w in sources if emb is not None]
    if not valid:
        return None

    total_weight = sum(w for _, w in valid)
    dim = len(valid[0][0])
    blended = [0.0] * dim

    for emb, weight in valid:
        for i, val in enumerate(emb):
            blended[i] += val * (weight / total_weight)

    return blended


# ---------------------------------------------------------------------------
# DB fetchers
# ---------------------------------------------------------------------------

def _fetch_profile(user_id: str) -> dict:
    response = (
        supabase.table("profiles")
        .select("interests, bio, interest_embedding")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return response.data


def _fetch_joined_event_embeddings(user_id: str) -> list[list[float]]:
    response = (
        supabase.table("event_participants")
        .select("events(event_embedding)")
        .eq("user_id", user_id)
        .execute()
    )
    embeddings = []
    for item in (response.data or []):
        raw = item.get("events", {}) and item["events"].get("event_embedding")
        parsed = _parse_embedding(raw)
        if parsed is not None:
            embeddings.append(parsed)
    return embeddings


def _fetch_saved_event_embeddings(user_id: str) -> list[list[float]]:
    response = (
        supabase.table("saved_events")
        .select("events(event_embedding)")
        .eq("user_id", user_id)
        .execute()
    )
    embeddings = []
    for item in (response.data or []):
        raw = item.get("events", {}) and item["events"].get("event_embedding")
        parsed = _parse_embedding(raw)
        if parsed is not None:
            embeddings.append(parsed)
    return embeddings


def _fetch_already_seen_ids(user_id: str) -> set[str]:
    """Collect event IDs the user has already joined or saved."""
    joined = (
        supabase.table("event_participants")
        .select("event_id")
        .eq("user_id", user_id)
        .execute()
    )
    saved = (
        supabase.table("saved_events")
        .select("event_id")
        .eq("user_id", user_id)
        .execute()
    )
    ids: set[str] = set()
    for row in (joined.data or []):
        if row.get("event_id"):
            ids.add(row["event_id"])
    for row in (saved.data or []):
        if row.get("event_id"):
            ids.add(row["event_id"])
    return ids


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_recommendations(user_id: str, limit: int = 10) -> dict:
    limit = max(1, int(limit))
    now = datetime.now(timezone.utc).isoformat()

    # 1. Gather all signal embeddings
    profile = _fetch_profile(user_id)

    # Parse stored interest embedding (may be a string from Supabase)
    interest_embedding = _parse_embedding(profile.get("interest_embedding"))

    # If no pre-computed interest embedding, generate one on the fly from normalised interests and bio
    if not interest_embedding:
        interests = _parse_interests(profile.get("interests"))
        bio = profile.get("bio") or ""
        if isinstance(bio, str):
            bio = bio.strip()
        else:
            bio = str(bio).strip() if bio else ""
        text = (" ".join(interests) + " " + bio).strip()
        interest_embedding = generate_embedding(text) if text else None

    joined_embeddings = _fetch_joined_event_embeddings(user_id)
    saved_embeddings = _fetch_saved_event_embeddings(user_id)

    avg_joined = _average_embeddings(joined_embeddings)
    avg_saved = _average_embeddings(saved_embeddings)

    # 2. Blend signals with weights:
    #    - interests/bio  = strong baseline      (0.5)
    #    - joined events  = behavioural signal   (0.3)
    #    - saved events   = intent signal        (0.2)
    query_embedding = _blend_embeddings([
        (interest_embedding, 0.5),
        (avg_joined, 0.3),
        (avg_saved, 0.2),
    ])

    if not query_embedding:
        raise HTTPException(
            status_code=400,
            detail="Not enough profile data to generate recommendations",
        )

    # 3. Semantic search against events
    # Over-fetch candidate events (e.g. max(100, limit * 10)) so past, inactive,
    # already-joined, already-saved, or hidden events do not starve the results
    # of active upcoming recommendations.
    candidate_count = max(limit * 10, 100)
    response = supabase.rpc("search_events", {
        "query_embedding": query_embedding,
        "query_text": "",           # pure vector search, no keyword boost
        "match_count": candidate_count,  # fetch extra to allow filtering below
    }).execute()

    already_seen = _fetch_already_seen_ids(user_id)

    # 4. Filter out already joined/saved events and past events
    results = [
        event for event in (response.data or [])
        if event["id"] not in already_seen
        and event.get("end_datetime", "") >= now
        and event.get("status") == "active"
    ]
    # Over-fetched above, so hiding blocked organizers' events still leaves a full page.
    results = filter_removed_events(results)
    results = filter_hidden_events(results, user_id)[:limit]

    return {
        "user_id": user_id,
        "total": len(results),
        "data": results,
    }