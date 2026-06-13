from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_unhealthy_db(client: AsyncClient):
    with patch("src.main.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await client.get("/health")
        assert resp.status_code == 503
        assert resp.json() == {"status": "unhealthy"}


@pytest.mark.asyncio
async def test_health_unhealthy_redis(client: AsyncClient):
    with patch("src.main.redis_client") as mock_redis:
        mock_redis.ping = AsyncMock(side_effect=Exception("Redis down"))

        resp = await client.get("/health")
        assert resp.status_code == 503
        assert resp.json() == {"status": "unhealthy"}


@pytest.mark.asyncio
async def test_lifespan_consumer_starts():
    from src.main import lifespan, app
    from unittest.mock import AsyncMock, patch

    with patch("src.main.consumer_loop", new_callable=AsyncMock) as mock_consumer, \
         patch("src.main.engine") as mock_engine, \
         patch("src.main.redis_client") as mock_redis:

        mock_engine.dispose = AsyncMock()
        mock_redis.aclose = AsyncMock()

        async with lifespan(app):
            pass

        mock_engine.dispose.assert_called_once()
        mock_redis.aclose.assert_called_once()
