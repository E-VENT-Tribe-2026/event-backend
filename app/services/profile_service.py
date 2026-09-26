import logging
from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding
from app.utils.validators import validate_username, validate_full_name

logger = logging.getLogger(__name__)


# Columns needed to build a UserSummary for a user (see build_user_summary below).
# Keep in sync with app.schemas.profile_schema.UserSummary.
USER_SUMMARY_COLUMNS = "id, username, full_name, avatar_url, avatar_kind, icon_id"


def build_user_summary(profile: dict | None, user_id: str | None = None) -> dict:
    """Build the minimal, consistent shape used to show a user next to their content.

    Keep in sync with app.schemas.profile_schema.UserSummary.
    Pass user_id whenever profile may be None or lack an id, since UserSummary.id is required.
    """
    profile = profile or {}

    username = str(profile.get("username") or "").strip() or None
    full_name = profile.get("full_name")
    # An account without a username is shown by its full name.
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


def get_user_summaries(user_ids) -> dict:
    """Batch-fetch UserSummary dicts for a list of user ids in a single query."""
    ids = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not ids:
        return {}

    try:
        response = (
            supabase.table("profiles")
            .select(USER_SUMMARY_COLUMNS)
            .in_("id", ids)
            .execute()
        )
        summaries = {
            row["id"]: build_user_summary(row)
            for row in (response.data or [])
            if row.get("id")
        }
        missing = [uid for uid in ids if uid not in summaries]
        if missing:
            logger.warning(f"No profile row for user ids: {missing}")
    except Exception as e:
        logger.error(f"Failed to fetch user summaries for {ids}: {e}", exc_info=True)
        summaries = {}

    return {uid: summaries.get(uid) or build_user_summary(None, uid) for uid in ids}


def get_profile(user_id: str):
    """Get the full profile for the authenticated user (private)."""
    response = (
        supabase.table("profiles")
        .select("*")
        .eq("id", user_id)
        .single()
        .execute()
    )

    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )

    profile = dict(response.data)

    # Ensure banner and banner_url are aligned once present in database
    if "banner_url" in profile and "banner" not in profile:
        profile["banner"] = profile.get("banner_url")
    elif "banner" in profile and "banner_url" not in profile:
        profile["banner_url"] = profile.get("banner")

    # Ensure avatar_kind defaults to 'icon' once column exists in database
    if "avatar_kind" in profile and not profile["avatar_kind"]:
        profile["avatar_kind"] = "icon"

    return profile


def get_username(user_id: str) -> str:
    """Return the user's username, falling back to their full name, then 'Someone'."""
    try:
        result = (
            supabase.table("profiles")
            .select("username, full_name")
            .eq("id", user_id)
            .single()
            .execute()
        )
        data = result.data or {}
        # An account without a username is shown by its full name.
        for name in (data.get("username"), data.get("full_name")):
            if name and str(name).strip():
                return str(name).strip()
        return "Someone"
    except Exception as e:
        logger.warning(f"Username lookup failed for user {user_id}: {e}")
        return "Someone"


def _compute_interest_embedding(interests: list[str] | None, bio: str | None) -> list[float] | None:
    interests = interests or []
    bio = bio or ""
    text = (" ".join(interests) + " " + bio).strip()
    return generate_embedding(text) if text else None


def update_profile(user_id: str, update_data: dict):
    """Update profile fields for the authenticated user."""
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Refuse to change the username in a profile update, whatever the request contains.
    # A profile update that contains a username leaves the username as it was.
    update_data.pop("username", None)

    # Refuse a profile update whose full name is empty, is only spaces, or breaks full name rules
    if "full_name" in update_data:
        update_data["full_name"] = validate_full_name(update_data["full_name"])

    # Accept banner (via 'banner' or 'banner_url')
    if "banner" in update_data:
        banner_val = update_data.pop("banner")
        if "banner_url" not in update_data:
            update_data["banner_url"] = banner_val

    # Accept profile_picture alias for avatar_kind
    if "profile_picture" in update_data:
        pic_val = update_data.pop("profile_picture")
        if "avatar_kind" not in update_data:
            update_data["avatar_kind"] = pic_val

    # Accept whether profile picture is an uploaded photo or an icon
    if "avatar_kind" in update_data:
        kind = update_data["avatar_kind"]
        if kind is not None:
            kind_str = str(kind).strip().lower()
            if kind_str not in ("photo", "icon"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="avatar_kind must be either 'photo' or 'icon'."
                )
            update_data["avatar_kind"] = kind_str

    # If the user updates interests and/or bio, regenerate the interest embedding.
    # We fetch the existing profile so partial updates still produce a correct embedding.
    if "interests" in update_data or "bio" in update_data:
        existing = (
            supabase.table("profiles")
            .select("interests, bio")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if existing.data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found",
            )

        interests = update_data.get("interests", existing.data.get("interests"))
        bio = update_data.get("bio", existing.data.get("bio"))
        update_data["interest_embedding"] = _compute_interest_embedding(interests, bio)

    response = (
        supabase.table("profiles")
        .update(update_data)
        .eq("id", user_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile update failed"
        )

    res = dict(response.data[0])
    if "banner_url" in res and "banner" not in res:
        res["banner"] = res.get("banner_url")
    elif "banner" in res and "banner_url" not in res:
        res["banner_url"] = res.get("banner")
    if "avatar_kind" in res and not res["avatar_kind"]:
        res["avatar_kind"] = "icon"

    return res


def choose_username(user_id: str, username: str, full_name: str):
    """
    Allow an account without a username (e.g. existing user or Google sign-in)
    to choose a username once and save a full name under the same validation rules
    and availability check used at registration.
    """
    valid_username = validate_username(username)
    valid_full_name = validate_full_name(full_name)

    existing_profile = (
        supabase.table("profiles")
        .select("*")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if existing_profile.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )

    if existing_profile.data.get("username"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username has already been chosen and cannot be changed."
        )

    # Check username availability
    avail = (
        supabase.table("profiles")
        .select("id")
        .eq("username", valid_username)
        .neq("id", user_id)
        .execute()
    )
    if avail.data and len(avail.data) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is unavailable. That username is already in use."
        )

    update_payload = {
        "username": valid_username,
        "full_name": valid_full_name,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    response = (
        supabase.table("profiles")
        .update(update_payload)
        .eq("id", user_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update profile."
        )

    return response.data[0]


def update_location(user_id: str, latitude: float, longitude: float):
    """Update the geographic location of the authenticated user."""
    response = (
        supabase.table("profiles")
        .update({
            "latitude": latitude,
            "longitude": longitude,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        .eq("id", user_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Location update failed"
        )

    return response.data[0]


def get_public_profile(user_id: str):
    """
    Get a user's public profile.
    Only returns data if the profile visibility is 'public'.
    Private profiles return a 403 to avoid leaking existence.
    """
    response = (
        supabase.table("profiles")
        .select("id, full_name, avatar_url, bio, visibility, created_at, username")
        .eq("id", user_id)
        .single()
        .execute()
    )

    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )

    profile = response.data

    if profile.get("visibility") != "public":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This profile is private"
        )

    return profile


def search_profiles(query: str, page: int = 1, limit: int = 10):
    """Search public profiles by username. Returns only public profiles."""
    start = (page - 1) * limit
    end = start + limit - 1

    response = (
        supabase.table("profiles")
        .select("id, full_name, avatar_url, bio, visibility")
        .eq("visibility", "public")
        .ilike("username", f"%{query}%")
        .range(start, end)
        .execute()
    )

    return {
        "page": page,
        "limit": limit,
        "data": response.data
    }