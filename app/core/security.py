from jose import jwt
from fastapi import HTTPException, status
from app.core.config import settings

def verify_token(token: str):
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_SERVICE_KEY,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        return payload
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )