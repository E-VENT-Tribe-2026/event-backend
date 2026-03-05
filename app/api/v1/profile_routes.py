from fastapi import APIRouter, Depends
from app.core.dependencies import get_current_user
from app.schemas.profile_schema import (
    ProfileUpdateRequest,
    LocationUpdateRequest
)
from app.services.profile_service import (
    get_profile,
    update_profile,
    update_location,
    get_public_profile
)

router = APIRouter()


@router.get("/me")
def read_my_profile(user_id: str = Depends(get_current_user)):
    return get_profile(user_id)


@router.put("/me")
def update_my_profile(
    data: ProfileUpdateRequest,
    user_id: str = Depends(get_current_user)
):
    update_data = data.model_dump(exclude_unset=True)
    return update_profile(user_id, update_data)


@router.patch("/location")
def update_my_location(
    data: LocationUpdateRequest,
    user_id: str = Depends(get_current_user)
):
    return update_location(user_id, data.latitude, data.longitude)


@router.get("/{user_id}")
def read_public_profile(user_id: str):
    return get_public_profile(user_id)