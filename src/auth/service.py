import hashlib
from datetime import datetime, timedelta, timezone
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import jwt
from jwt import PyJWTError as JWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import RefreshToken, User
from src.auth.schemas import UserCreate
from src.config import settings
from src.database import async_session, get_redis
from src.exceptions import AppException

ph = PasswordHasher()

REFRESH_TOKEN_KEY_PREFIX = "refresh_token:"
FAMILY_KEY_PREFIX = "family:"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def get_password_hash(password: str) -> str:
    return ph.hash(password)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def create_refresh_token(user_id: str, family: str | None = None) -> str:
    jti = uuid.uuid4().hex
    family = family or uuid.uuid4().hex
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
    to_encode = {"sub": user_id, "jti": jti, "family": family, "exp": expire, "type": "refresh"}
    token = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    token_hash = _hash_token(token)

    try:
        redis = get_redis()
        await redis.set(f"{REFRESH_TOKEN_KEY_PREFIX}{jti}", user_id, ex=timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS))
        await redis.sadd(f"{FAMILY_KEY_PREFIX}{family}", jti)
        await redis.expire(f"{FAMILY_KEY_PREFIX}{family}", timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS))
    except Exception:
        pass

    try:
        async with async_session() as session:
            db_token = RefreshToken(
                user_id=uuid.UUID(user_id),
                family=family,
                jti=jti,
                token_hash=token_hash,
                expires_at=expire,
            )
            session.add(db_token)
            await session.commit()
    except Exception:
        pass

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
    family = payload.get("family")
    if not jti or not user_id or not family:
        return None

    redis = get_redis()

    used_key = f"{FAMILY_KEY_PREFIX}{family}:used"
    try:
        if await redis.sismember(used_key, jti):
            await _revoke_family(family)
            return None
    except Exception:
        pass

    stored_user_id = None
    try:
        stored_user_id = await redis.get(f"{REFRESH_TOKEN_KEY_PREFIX}{jti}")
        if stored_user_id is not None and isinstance(stored_user_id, bytes):
            stored_user_id = stored_user_id.decode()
    except Exception:
        pass

    if stored_user_id is None:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(RefreshToken).where(
                        RefreshToken.jti == jti,
                        RefreshToken.revoked == False,
                    )
                )
                db_token = result.scalar_one_or_none()
                if db_token and not db_token.revoked:
                    stored_user_id = str(db_token.user_id)
        except Exception:
            pass

    if stored_user_id is None:
        return None
    if stored_user_id != user_id:
        return None

    try:
        await redis.sadd(used_key, jti)
        await redis.expire(used_key, timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS))
    except Exception:
        pass

    try:
        async with async_session() as session:
            result = await session.execute(
                select(RefreshToken).where(RefreshToken.jti == jti)
            )
            db_token = result.scalar_one_or_none()
            if db_token:
                db_token.revoked = True
                await session.commit()
    except Exception:
        pass

    return user_id


async def _revoke_family(family: str) -> None:
    redis = get_redis()
    try:
        jti_members = await redis.smembers(f"{FAMILY_KEY_PREFIX}{family}")
        if jti_members:
            keys_to_delete = [f"{REFRESH_TOKEN_KEY_PREFIX}{j}" for j in jti_members]
            keys_to_delete.append(f"{FAMILY_KEY_PREFIX}{family}")
            keys_to_delete.append(f"{FAMILY_KEY_PREFIX}{family}:used")
            await redis.delete(*keys_to_delete)
    except Exception:
        pass

    try:
        async with async_session() as session:
            await session.execute(
                RefreshToken.__table__.update()
                .where(RefreshToken.family == family)
                .values(revoked=True)
            )
            await session.commit()
    except Exception:
        pass


async def revoke_refresh_token(token: str) -> bool:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM], options={"verify_exp": False})
    except JWTError:
        return False
    jti = payload.get("jti")
    family = payload.get("family")
    if not jti:
        return False

    redis = get_redis()
    deleted = 0
    try:
        deleted = await redis.delete(f"{REFRESH_TOKEN_KEY_PREFIX}{jti}")
    except Exception:
        pass

    try:
        async with async_session() as session:
            result = await session.execute(
                select(RefreshToken).where(RefreshToken.jti == jti)
            )
            db_token = result.scalar_one_or_none()
            if db_token:
                db_token.revoked = True
                await session.commit()
    except Exception:
        pass

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
