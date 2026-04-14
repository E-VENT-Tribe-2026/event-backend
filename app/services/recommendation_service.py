import json
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding
from fastapi import HTTPException
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        value = json.loads(value)
    return [float(v) for v in value]


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
        ids.add(row["event_id"])
    for row in (saved.data or []):
        ids.add(row["event_id"])
    return ids


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_recommendations(user_id: str, limit: int = 10) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    # 1. Gather all signal embeddings
    profile = _fetch_profile(user_id)

    # Parse stored interest embedding (may be a string from Supabase)
    interest_embedding = _parse_embedding(profile.get("interest_embedding"))

    # If no pre-computed interest embedding, generate one on the fly
    if not interest_embedding:
        interests = profile.get("interests") or []
        bio = profile.get("bio") or ""
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
    response = supabase.rpc("search_events", {
        "query_embedding": query_embedding,
        "query_text": "",           # pure vector search, no keyword boost
        "match_count": limit + 20,  # fetch extra to allow filtering below
    }).execute()

    already_seen = _fetch_already_seen_ids(user_id)

    # 4. Filter out already joined/saved events and past events
    results = [
        event for event in (response.data or [])
        if event["id"] not in already_seen
        and event.get("end_datetime", "") >= now
        and event.get("status") == "active"
    ][:limit]

    return {
        "user_id": user_id,
        "total": len(results),
        "data": results,
    }