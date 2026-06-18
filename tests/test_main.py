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
    with patch("src.main.get_redis") as mock_get_redis:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("Redis down"))
        mock_get_redis.return_value = mock_redis

        resp = await client.get("/health")
        assert resp.status_code == 503
        assert resp.json() == {"status": "unhealthy"}


@pytest.mark.asyncio
async def test_lifespan_disposes_resources():
    from src.main import lifespan, app
    from unittest.mock import AsyncMock, patch

    with patch("src.main.engine") as mock_engine, \
         patch("src.main.close_redis") as mock_close:

        mock_engine.dispose = AsyncMock()
        mock_close.return_value = AsyncMock()

        async with lifespan(app):
            pass

        mock_engine.dispose.assert_called_once()
        mock_close.assert_called_once()
