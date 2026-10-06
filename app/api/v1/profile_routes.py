import time
import mimetypes
from uuid import UUID
from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from app.core.dependencies import get_current_user, get_current_onboarded_user
from app.db.supabase_client import supabase
from app.schemas.profile_schema import (
    ProfileUpdateRequest,
    LocationUpdateRequest,
)
from app.schemas.auth_schema import ChooseUsernameRequest
from app.services.public_profile_service import build_public_profile
from app.services.profile_service import (
    get_profile,
    update_profile,
    update_location,
    search_profiles,
    choose_username,
)

router = APIRouter()

# Allowed avatar formats, matched to the Supabase "avatars" bucket's MIME allowlist.
ALLOWED_AVATAR_EXTENSIONS = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


# IMPORTANT: Static routes (/me, /location, /search, /choose-username, /username, /upload-photo) must be declared BEFORE
# the dynamic route (/{user_id}) to prevent routing conflicts.

@router.post("/choose-username")
def post_choose_username(
    data: ChooseUsernameRequest,
    user=Depends(get_current_user)
):
    """Allow an account without a username to choose one and set a full name."""
    return choose_username(user.id, data.username, data.full_name)


@router.post("/username")
def post_username(
    data: ChooseUsernameRequest,
    user=Depends(get_current_user)
):
    """Set username and full name for an account without a username."""
    return choose_username(user.id, data.username, data.full_name)


@router.put("/username")
def put_username(
    data: ChooseUsernameRequest,
    user=Depends(get_current_user)
):
    """Set username and full name for an account without a username."""
    return choose_username(user.id, data.username, data.full_name)


@router.get("/me")
def read_my_profile(user=Depends(get_current_onboarded_user)):
    """Returns the full profile of the authenticated user."""
    return get_profile(user.id)


@router.put("/me")
def update_my_profile(
    data: ProfileUpdateRequest,
    user=Depends(get_current_onboarded_user)
):
    """Update profile fields for the authenticated user."""
    update_data = data.model_dump(exclude_unset=True)
    return update_profile(user.id, update_data)


@router.patch("/location")
def update_my_location(
    data: LocationUpdateRequest,
    user=Depends(get_current_onboarded_user)
):
    """Update the location of the authenticated user."""
    return update_location(user.id, data.latitude, data.longitude)

@router.post("/upload-photo")
async def upload_profile_photo(
    file: UploadFile = File(...),
    user=Depends(get_current_onboarded_user)
):
    """Upload profile photo to Supabase storage and update profile avatar_url."""
    try:
        user_id = user.id

        file_ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else ""
        content_type = ALLOWED_AVATAR_EXTENSIONS.get(file_ext)

        if not content_type:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file format. Please upload a JPG, PNG, or WEBP image."
            )

        file_path = f"{user_id}/avatar-{int(time.time())}.{file_ext}"
        file_bytes = await file.read()

        res = supabase.storage.from_("avatars").upload(
            path=file_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )

        public_url_res = supabase.storage.from_("avatars").get_public_url(file_path)
        public_url = public_url_res if isinstance(public_url_res, str) else public_url_res.get("publicUrl")

        if not public_url:
            raise HTTPException(status_code=500, detail="Failed to generate public URL for photo.")

        update_profile(user_id, {"avatar_url": public_url})

        return {"avatar_url": public_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search")
def search_public_profiles(
    q: str = Query(..., min_length=1, description="Search query for username"),
    page: int = Query(1, ge=1, le=10000),
    limit: int = Query(10, ge=1, le=50),
    user=Depends(get_current_user),
):
    """Search public profiles by username. Requires authentication."""
    return search_profiles(q, page, limit, user.id)


@router.get("/{user_id}")
def read_public_profile(user_id: UUID, user=Depends(get_current_user)):
    """Get a profile by user ID, including events and friendship state."""
    return build_public_profile(str(user_id), user.id)
