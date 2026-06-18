from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.limiter import limiter
from src.main import app
from src.models import Base

# Rate limiting uses a single in-memory counter for the whole process, so leaving it
# on would let calls accumulate across tests and trip the limit. Disable it for unit
# tests; limit behaviour is exercised separately in test_auth.test_rate_limit_returns_429.
limiter.enabled = False

TEST_DATABASE_URL = "postgresql+asyncpg://analytics:analytics@localhost:5434/analytics"
TEST_REDIS_URL = "redis://localhost:6381/0"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_redis():
    r = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()


@pytest_asyncio.fixture
async def client(engine, test_redis) -> AsyncGenerator[AsyncClient, None]:
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    from src.auth.dependencies import get_db
    app.dependency_overrides[get_db] = override_get_db

    with patch("src.database.get_redis", return_value=test_redis), \
         patch("src.main.get_redis", return_value=test_redis), \
         patch("src.events.service.get_redis", return_value=test_redis), \
         patch("src.auth.service.get_redis", return_value=test_redis), \
         patch("src.worker.consumer.get_redis", return_value=test_redis), \
         patch("src.analytics.router.get_redis", return_value=test_redis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict:
    await client.post(
        "/api/v1/auth/register/",
        json={"email": "test@test.com", "password": "secret123", "company_id": 1},
    )
    login_resp = await client.post(
        "/api/v1/auth/login/",
        json={"email": "test@test.com", "password": "secret123"},
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
