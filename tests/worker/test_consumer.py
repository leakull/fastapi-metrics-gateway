import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.events.models import Event


@pytest.mark.asyncio
async def test_consumer_empty_queue(engine, test_redis):
    await test_redis.delete("queue:events")
    from src.worker.consumer import consumer_loop

    iteration_count = 0

    async def mock_sleep(_):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count >= 2:
            raise StopAsyncIteration()

    test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("src.worker.consumer.redis_client", test_redis), \
         patch("src.worker.consumer.async_session", test_session_factory), \
         patch("src.worker.consumer.asyncio.sleep", mock_sleep):
        with pytest.raises(StopAsyncIteration):
            await consumer_loop()


@pytest.mark.asyncio
async def test_consumer_timezone_utc(engine, test_redis):
    await test_redis.delete("queue:events")

    event = json.dumps({
        "company_id": 1,
        "user_id": "tz-user",
        "event_type": "test",
        "payload": {},
        "created_at": "2026-06-15T12:00:00+03:00",
    })
    await test_redis.rpush("queue:events", event)

    from src.worker.consumer import consumer_loop
    iteration_count = 0

    async def mock_sleep(_):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count >= 1:
            raise StopAsyncIteration()

    test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("src.worker.consumer.redis_client", test_redis), \
         patch("src.worker.consumer.async_session", test_session_factory), \
         patch("src.worker.consumer.asyncio.sleep", mock_sleep):
        with pytest.raises(StopAsyncIteration):
            await consumer_loop()

    async with test_session_factory() as session:
        result = await session.execute(
            select(Event).where(Event.user_id == "tz-user")
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.created_at.hour == 9


@pytest.mark.asyncio
async def test_consumer_graceful_shutdown(engine, test_redis):
    await test_redis.delete("queue:events")

    for i in range(3):
        event = json.dumps({
            "company_id": 1,
            "user_id": f"shutdown-{i}",
            "event_type": "test",
            "payload": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await test_redis.rpush("queue:events", event)

    from src.worker.consumer import consumer_loop

    async def mock_sleep(_):
        raise asyncio.CancelledError()

    test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("src.worker.consumer.redis_client", test_redis), \
         patch("src.worker.consumer.async_session", test_session_factory), \
         patch("src.worker.consumer.asyncio.sleep", mock_sleep):
        await consumer_loop()

    queue_len = await test_redis.llen("queue:events")
    assert queue_len == 0


@pytest.mark.asyncio
async def test_consumer_db_error_retry(engine, test_redis):
    await test_redis.delete("queue:events")

    event = json.dumps({
        "company_id": 1,
        "user_id": "retry-user",
        "event_type": "test",
        "payload": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await test_redis.rpush("queue:events", event)

    from src.worker.consumer import consumer_loop

    call_count = 0

    async def mock_sleep(_):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise StopAsyncIteration()

    class FailingSession:
        async def __aenter__(self):
            raise Exception("DB connection failed")
        async def __aexit__(self, *args):
            pass

    call_count_inner = 0

    class EventuallyWorkingSession:
        async def __aenter__(self):
            nonlocal call_count_inner
            call_count_inner += 1
            if call_count_inner == 1:
                raise Exception("DB connection failed")
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            self._session = factory()
            return self._session
        async def __aexit__(self, *args):
            pass

    with patch("src.worker.consumer.redis_client", test_redis), \
         patch("src.worker.consumer.async_session", EventuallyWorkingSession), \
         patch("src.worker.consumer.asyncio.sleep", mock_sleep):
        with pytest.raises(StopAsyncIteration):
            await consumer_loop()

    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        from sqlalchemy import select
        result = await session.execute(select(Event).where(Event.user_id == "retry-user"))
        row = result.scalar_one_or_none()
        assert row is not None


@pytest.mark.asyncio
async def test_consumer_recovers_processing_on_startup(engine, test_redis):
    """Items stranded in the processing list by a crashed run must be re-inserted."""
    from src.worker.config import PROCESSING_KEY, QUEUE_KEY

    await test_redis.delete(QUEUE_KEY)
    await test_redis.delete(PROCESSING_KEY)

    # Simulate a previous crash: a batch was moved to processing but never committed.
    for i in range(3):
        await test_redis.rpush(PROCESSING_KEY, json.dumps({
            "company_id": 1,
            "user_id": f"recovered-{i}",
            "event_type": "test",
            "payload": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))

    from src.worker.consumer import consumer_loop

    iteration_count = 0

    async def mock_sleep(_):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count >= 1:
            raise StopAsyncIteration()

    test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("src.worker.consumer.redis_client", test_redis), \
         patch("src.worker.consumer.async_session", test_session_factory), \
         patch("src.worker.consumer.asyncio.sleep", mock_sleep):
        with pytest.raises(StopAsyncIteration):
            await consumer_loop()

    async with test_session_factory() as session:
        result = await session.execute(select(Event).where(Event.user_id.like("recovered-%")))
        rows = result.scalars().all()

    assert len(rows) == 3
    assert await test_redis.llen(QUEUE_KEY) == 0
    assert await test_redis.llen(PROCESSING_KEY) == 0


@pytest.mark.asyncio
async def test_consumer_dedup_on_event_id(engine, test_redis):
    """Two queue entries with the same id must produce a single row (ON CONFLICT)."""
    import uuid as uuidlib
    from sqlalchemy import func

    await test_redis.delete("queue:events")

    event_id = str(uuidlib.uuid4())
    for _ in range(2):
        await test_redis.rpush("queue:events", json.dumps({
            "id": event_id,
            "company_id": 1,
            "user_id": "dup-user",
            "event_type": "test",
            "payload": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))

    from src.worker.consumer import consumer_loop
    iteration_count = 0

    async def mock_sleep(_):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count >= 1:
            raise StopAsyncIteration()

    test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("src.worker.consumer.redis_client", test_redis), \
         patch("src.worker.consumer.async_session", test_session_factory), \
         patch("src.worker.consumer.asyncio.sleep", mock_sleep):
        with pytest.raises(StopAsyncIteration):
            await consumer_loop()

    async with test_session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(Event).where(Event.user_id == "dup-user")
        )
        count = result.scalar()
    assert count == 1
