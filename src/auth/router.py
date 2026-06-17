from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user, get_db
from src.auth.models import User
from src.auth.schemas import LoginRequest, Token, UserCreate, UserResponse
from src.auth.service import authenticate_user, create_access_token, create_user
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
    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token)


@router.get("/me/", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    return current_user
