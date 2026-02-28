from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(db: AsyncSession = Depends(get_db)):
    # TODO: accept UserCreate schema
    # TODO: check if email already exists via UserService
    # TODO: hash password and create user via UserService
    # TODO: return UserRead schema
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post("/login")
async def login(db: AsyncSession = Depends(get_db)):
    # TODO: accept LoginRequest schema
    # TODO: fetch user by email via UserService
    # TODO: verify password with verify_password()
    # TODO: return access + refresh tokens
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post("/refresh")
async def refresh():
    # TODO: accept RefreshRequest schema
    # TODO: decode refresh token with decode_token()
    # TODO: verify token type is "refresh"
    # TODO: issue new access token
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout():
    # TODO: blacklist token (Redis) or clear cookie
    pass