from fastapi import HTTPException, status
from openai import APIError
from app.db.supabase_client import supabase
from gotrue.errors import AuthApiError

def register_user(
    email: str, 
    password: str, 
    dob: str,           
    gender: str, 
    interests: list[str],
    full_name: str | None = None
):
    try:
        
        auth_response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "full_name": full_name  # Stores name in auth metadata
                }
            }
        })

        if not auth_response.user:
            raise HTTPException(status_code=400, detail="Registration failed")

        user_id = auth_response.user.id

 

        profile_response = (
            supabase.table("profiles")
            .update({
                "dob": dob,
                "gender": gender,
                "interests": interests,
                "full_name": full_name,
            })
            .eq("id", user_id)
            .execute()
        )

        if auth_response.session is None:
            return {"message": "User registered. Please confirm email to activate profile."}

        return {
            "access_token": auth_response.session.access_token,
            "user_id": user_id,
            "data": profile_response.data
        }

    except AuthApiError as e:
        raise HTTPException(status_code=400, detail=f"Auth Error: {str(e)}")
    
    except APIError as e:
        if "age_18_or_older" in str(e):
            
            raise HTTPException(
                status_code=400, 
                detail="Registration blocked: You must be 18 or older."
            )
        raise HTTPException(status_code=400, detail=f"Database Error: {str(e)}")
def login_user(email: str, password: str):
    response = supabase.auth.sign_in_with_password({
        "email": email,
        "password": password
    })

    if response.session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or email not confirmed"
        )

    return {
        "access_token": response.session.access_token,
        "token_type": "bearer"
    }