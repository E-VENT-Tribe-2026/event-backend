from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.db.supabase_client import supabase

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    
    token = credentials.credentials

    try:
        user = supabase.auth.get_user(token)

        if user.user is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        return user.user

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")