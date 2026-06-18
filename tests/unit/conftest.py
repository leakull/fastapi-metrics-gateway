from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.limiter import limiter

limiter.enabled = False


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def client(fake_redis) -> AsyncGenerator[AsyncClient, None]:
    mock_session_factory = MagicMock()

    async def override_get_db():
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = AsyncMock()
        yield session

    from src.auth.dependencies import get_db
    app_patcher = patch("src.main.async_session", new_callable=MagicMock)
    db_patcher = patch("src.auth.dependencies.async_session", new_callable=MagicMock)
    redis_event_patcher = patch("src.events.service.redis_client", fake_redis)
    redis_consumer_patcher = patch("src.worker.consumer.redis_client", fake_redis)
    redis_main_patcher = patch("src.main.redis_client", fake_redis)
    redis_analytics_patcher = patch("src.analytics.router.redis_client", fake_redis)

    with app_patcher as mock_app_session, \
         db_patcher as mock_db_session, \
         redis_event_patcher, \
         redis_consumer_patcher, \
         redis_main_patcher, \
         redis_analytics_patcher:

        mock_app_session.return_value.__aenter__ = AsyncMock()
        mock_app_session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db_session.return_value.__aenter__ = AsyncMock()
        mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from src.main import app
        app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()
