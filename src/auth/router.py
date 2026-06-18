from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import jwt as pyjwt

from src.auth.dependencies import get_current_active_user, get_db
from src.auth.models import User
from src.auth.schemas import LoginRequest, RefreshRequest, Token, UserCreate, UserResponse
from src.auth.service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    create_user,
    revoke_refresh_token,
    verify_refresh_token,
)
from src.config import settings
from src.limiter import limiter

router = APIRouter()


@router.post("/register/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(request: Request, user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    return await create_user(db, user_data)


@router.post("/login/", response_model=Token)
@limiter.limit("5/minute")
async def login(request: Request, user_data: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, user_data.email, user_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_id = str(user.id)
    access_token = create_access_token(data={"sub": user_id})
    refresh_token = await create_refresh_token(user_id)
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh/", response_model=Token)
@limiter.limit("20/minute")
async def refresh(request: Request, body: RefreshRequest):
    try:
        unverified = pyjwt.decode(body.refresh_token, options={"verify_signature": False})
        family = unverified.get("family")
    except Exception:
        family = None

    user_id = await verify_refresh_token(body.refresh_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    await revoke_refresh_token(body.refresh_token)
    access_token = create_access_token(data={"sub": user_id})
    refresh_token = await create_refresh_token(user_id, family=family)
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout/", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest):
    await revoke_refresh_token(body.refresh_token)


@router.get("/me/", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    return current_user
