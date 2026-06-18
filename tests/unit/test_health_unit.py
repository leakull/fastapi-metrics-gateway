import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.worker.config import HEARTBEAT_KEY, HEARTBEAT_TTL


@pytest.mark.asyncio
async def test_health_worker_ok_when_heartbeat_recent():
    now = datetime.now(timezone.utc).isoformat()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.llen = AsyncMock(return_value=5)
    mock_redis.get = AsyncMock(return_value=now)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.execute = AsyncMock()
    mock_session_ctx.commit = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session_ctx)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("src.main.async_session", mock_session_factory), \
         patch("src.main.get_redis", return_value=mock_redis):
        from src.main import health
        result = await health()
        assert result["worker"] == "ok"
        assert result["queue_depth"] == 5


@pytest.mark.asyncio
async def test_health_worker_dead_when_heartbeat_old():
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.llen = AsyncMock(return_value=10)
    mock_redis.get = AsyncMock(return_value=old_time)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.execute = AsyncMock()
    mock_session_ctx.commit = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session_ctx)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("src.main.async_session", mock_session_factory), \
         patch("src.main.get_redis", return_value=mock_redis):
        from src.main import health
        result = await health()
        assert result["worker"] == "dead"
        assert result["queue_depth"] == 10


@pytest.mark.asyncio
async def test_health_worker_dead_when_no_heartbeat():
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.llen = AsyncMock(return_value=20)
    mock_redis.get = AsyncMock(return_value=None)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.execute = AsyncMock()
    mock_session_ctx.commit = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session_ctx)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("src.main.async_session", mock_session_factory), \
         patch("src.main.get_redis", return_value=mock_redis):
        from src.main import health
        result = await health()
        assert result["worker"] == "dead"
        assert result["queue_depth"] == 20


@pytest.mark.asyncio
async def test_health_unhealthy_when_db_down():
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.llen = AsyncMock(return_value=0)

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("src.main.async_session", mock_session_factory), \
         patch("src.main.get_redis", return_value=mock_redis):
        from src.main import health
        from fastapi.responses import JSONResponse
        result = await health()
        assert isinstance(result, JSONResponse)
        assert result.status_code == 503
