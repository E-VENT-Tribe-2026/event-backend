from jose import jwt, JWTError
from fastapi import HTTPException, status
from app.core.config import settings


ALGORITHM = "HS256"


def verify_token(token: str):
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_SERVICE_KEY,
            algorithms=[ALGORITHM],
            options={"verify_aud": False}
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )