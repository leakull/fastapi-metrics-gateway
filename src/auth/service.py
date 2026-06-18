from datetime import datetime, timedelta, timezone
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import jwt
from jwt import PyJWTError as JWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.auth.schemas import UserCreate
from src.config import settings
from src.database import redis_client
from src.exceptions import AppException

ph = PasswordHasher()

REFRESH_TOKEN_KEY_PREFIX = "refresh_token:"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def get_password_hash(password: str) -> str:
    return ph.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def create_refresh_token(user_id: str) -> str:
    jti = uuid.uuid4().hex
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
    to_encode = {"sub": user_id, "jti": jti, "exp": expire, "type": "refresh"}
    token = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    await redis_client.set(f"{REFRESH_TOKEN_KEY_PREFIX}{jti}", user_id, ex=timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS))
    return token


async def verify_refresh_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "refresh":
        return None
    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        return None
    stored_user_id = await redis_client.get(f"{REFRESH_TOKEN_KEY_PREFIX}{jti}")
    if stored_user_id is None:
        return None
    if isinstance(stored_user_id, bytes):
        stored_user_id = stored_user_id.decode()
    if stored_user_id != user_id:
        return None
    return user_id


async def revoke_refresh_token(token: str) -> bool:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM], options={"verify_exp": False})
    except JWTError:
        return False
    jti = payload.get("jti")
    if not jti:
        return False
    deleted = await redis_client.delete(f"{REFRESH_TOKEN_KEY_PREFIX}{jti}")
    return deleted > 0


async def create_user(session: AsyncSession, user_data: UserCreate) -> User:
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        company_id=user_data.company_id,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AppException(status_code=409, message="Email already registered")
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user and verify_password(password, user.hashed_password):
        return user
    return None


async def get_user_by_id(session: AsyncSession, user_id) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
