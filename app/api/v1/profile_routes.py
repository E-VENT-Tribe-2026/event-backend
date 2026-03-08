from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user
from app.schemas.profile_schema import (
    ProfileUpdateRequest,
    LocationUpdateRequest,
)
from app.services.profile_service import (
    get_profile,
    update_profile,
    update_location,
    get_public_profile,
    search_profiles,
)

router = APIRouter()


# IMPORTANT: Static routes (/me, /location, /search) must be declared BEFORE
# the dynamic route (/{user_id}) to prevent routing conflicts.

@router.get("/me")
def read_my_profile(user=Depends(get_current_user)):
    """Returns the full profile of the authenticated user."""
    return get_profile(user.id)


@router.put("/me")
def update_my_profile(
    data: ProfileUpdateRequest,
    user=Depends(get_current_user)
):
    """Update profile fields for the authenticated user."""
    update_data = data.model_dump(exclude_unset=True)
    return update_profile(user.id, update_data)


@router.patch("/location")
def update_my_location(
    data: LocationUpdateRequest,
    user=Depends(get_current_user)
):
    """Update the location of the authenticated user."""
    return update_location(user.id, data.latitude, data.longitude)


@router.get("/search")
def search_public_profiles(
    q: str = Query(..., min_length=1, description="Search query for profile name"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=50),
):
    """Search public profiles by name. Public endpoint."""
    return search_profiles(q, page, limit)


@router.get("/{user_id}")
def read_public_profile(user_id: str):
    """Get a public profile by user ID."""
    return get_public_profile(user_id)