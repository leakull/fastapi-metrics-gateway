import pytest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from src.events.schemas import EventCreate, MAX_PAYLOAD_BYTES


def test_valid_payload_accepted():
    event = EventCreate(
        user_id="user-1",
        event_type="click",
        payload={"page": "/home", "x": 1},
    )
    assert event.user_id == "user-1"
    assert event.payload == {"page": "/home", "x": 1}


def test_empty_payload_accepted():
    event = EventCreate(user_id="user-1", event_type="view")
    assert event.payload == {}


def test_payload_at_limit_accepted():
    large_payload = {"data": "x" * (MAX_PAYLOAD_BYTES - 20)}
    event = EventCreate(user_id="user-1", event_type="bulk", payload=large_payload)
    assert event.payload == large_payload


def test_payload_exceeding_limit_rejected():
    oversized_payload = {"data": "x" * (MAX_PAYLOAD_BYTES + 100)}
    with pytest.raises(ValidationError, match="payload exceeds"):
        EventCreate(user_id="user-1", event_type="bulk", payload=oversized_payload)


@pytest.mark.asyncio
async def test_redis_failure_returns_503():
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock(side_effect=Exception("Redis connection refused"))

    with patch("src.events.service.get_redis", return_value=mock_redis):
        from src.events.service import queue_event
        from src.exceptions import AppException

        with pytest.raises(AppException) as exc_info:
            await queue_event({
                "user_id": "user-1",
                "event_type": "click",
                "payload": {},
            })
        assert exc_info.value.status_code == 503
        assert "unavailable" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_user_id_max_length():
    with pytest.raises(ValidationError):
        EventCreate(user_id="x" * 256, event_type="click")


@pytest.mark.asyncio
async def test_event_type_max_length():
    with pytest.raises(ValidationError):
        EventCreate(user_id="user-1", event_type="x" * 256)
