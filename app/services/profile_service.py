from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.utils.embedding_helper import generate_embedding
from app.utils.validators import validate_username, validate_full_name



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

    return response.data


def get_display_name(user_id: str) -> str:
    """Return the user's full_name from profiles, falling back to 'Someone' if empty."""
    try:
        result = (
            supabase.table("profiles")
            .select("full_name")
            .eq("id", user_id)
            .single()
            .execute()
        )
        name = result.data.get("full_name") if result.data else None
        # if the name is strictly empty or whitespace, treat as missing
        if name and name.strip():
            return name.strip()
        return "Someone"
    except Exception:
        return "Someone"


def _compute_interest_embedding(interests: list[str] | None, bio: str | None) -> list[float] | None:
    interests = interests or []
    bio = bio or ""
    text = (" ".join(interests) + " " + bio).strip()
    return generate_embedding(text) if text else None


def update_profile(user_id: str, update_data: dict):
    """Update profile fields for the authenticated user."""
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if "full_name" in update_data:
        update_data["full_name"] = validate_full_name(update_data["full_name"])

    if "username" in update_data:
        curr_resp = (
            supabase.table("profiles")
            .select("username")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if curr_resp.data and curr_resp.data.get("username"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username cannot be changed once chosen."
            )
        valid_username = validate_username(update_data["username"])
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
        update_data["username"] = valid_username

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

    return response.data[0]


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
    """Search public profiles by name. Returns only public profiles."""
    start = (page - 1) * limit
    end = start + limit - 1

    response = (
        supabase.table("profiles")
        .select("id, full_name, avatar_url, bio, visibility")
        .eq("visibility", "public")
        .ilike("full_name", f"%{query}%")
        .range(start, end)
        .execute()
    )

    return {
        "page": page,
        "limit": limit,
        "data": response.data
    }