from fastapi import HTTPException, status
from app.db.supabase_client import supabase


def get_profile(user_id: str):
    response = supabase.table("profiles").select("*").eq("id", user_id).single().execute()

    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )

    return response.data


def update_profile(user_id: str, update_data: dict):
    response = supabase.table("profiles").update(update_data).eq("id", user_id).execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile update failed"
        )

    return response.data[0]


def update_location(user_id: str, latitude: float, longitude: float):
    response = supabase.table("profiles").update({
        "latitude": latitude,
        "longitude": longitude
    }).eq("id", user_id).execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Location update failed"
        )

    return response.data[0]


def get_public_profile(user_id: str):
    response = supabase.table("profiles").select("*").eq("id", user_id).single().execute()

    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )

    return response.data