import json
from datetime import datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.events.models import Event


@pytest.mark.asyncio
async def test_summary(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    await db_session.execute(insert(Event), [{
        "company_id": 1,
        "user_id": "user-1",
        "event_type": "page_view",
        "payload": {"url": "/"},
    }])
    await db_session.commit()

    resp = await client.get(
        "/api/v1/analytics/summary/",
        headers=auth_headers,
        params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["company_id"] == 1
    assert data["total_events"] >= 1


@pytest.mark.asyncio
async def test_summary_invalid_date_range(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/api/v1/analytics/summary/",
        headers=auth_headers,
        params={
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_consumer_bulk_insert(engine, test_redis):
    await test_redis.delete("queue:events")
    events = [
        json.dumps({
            "company_id": 1,
            "user_id": f"user-{i}",
            "event_type": "click",
            "payload": {},
            "created_at": datetime.now().isoformat(),
        })
        for i in range(5)
    ]
    for e in events:
        await test_redis.rpush("queue:events", e)

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
        result = await session.execute(select(func.count()).select_from(Event))
        count = result.scalar()
    assert count >= 5


@pytest.mark.asyncio
async def test_summary_unauthorized(client: AsyncClient):
    resp = await client.get(
        "/api/v1/analytics/summary/",
        params={"start_date": "2026-01-01", "end_date": "2026-12-31"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_summary_empty_result(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/api/v1/analytics/summary/",
        headers=auth_headers,
        params={
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_events"] == 0
    assert data["events"] == []


@pytest.mark.asyncio
async def test_summary_multiple_event_types(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    events = [
        {"company_id": 1, "user_id": "u1", "event_type": "page_view", "payload": {}},
        {"company_id": 1, "user_id": "u1", "event_type": "click", "payload": {}},
        {"company_id": 1, "user_id": "u2", "event_type": "page_view", "payload": {}},
    ]
    await db_session.execute(insert(Event), events)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/analytics/summary/",
        headers=auth_headers,
        params={"start_date": "2026-01-01", "end_date": "2026-12-31"},
    )
    data = resp.json()
    assert data["total_events"] == 3
    assert data["total_users"] == 2
    types = {e["event_type"] for e in data["events"]}
    assert types == {"page_view", "click"}


@pytest.mark.asyncio
async def test_summary_correct_unique_users(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    events = [
        {"company_id": 1, "user_id": "same_user", "event_type": "click", "payload": {}},
        {"company_id": 1, "user_id": "same_user", "event_type": "page_view", "payload": {}},
        {"company_id": 1, "user_id": "another_user", "event_type": "click", "payload": {}},
    ]
    await db_session.execute(insert(Event), events)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/analytics/summary/",
        headers=auth_headers,
        params={"start_date": "2026-01-01", "end_date": "2026-12-31"},
    )
    data = resp.json()
    assert data["total_users"] == 2
    assert data["total_events"] == 3


@pytest.mark.asyncio
async def test_summary_cache_hit(client: AsyncClient, auth_headers: dict, db_session: AsyncSession, test_redis):
    from datetime import datetime, timezone

    # A closed past range is cacheable (ranges reaching today are intentionally not).
    await db_session.execute(insert(Event), [{
        "company_id": 1,
        "user_id": "cache-user",
        "event_type": "page_view",
        "payload": {},
        "created_at": datetime(2025, 6, 15, tzinfo=timezone.utc),
    }])
    await db_session.commit()

    await client.get(
        "/api/v1/analytics/summary/",
        headers=auth_headers,
        params={"start_date": "2025-01-01", "end_date": "2025-12-31"},
    )

    keys = await test_redis.keys("cache:analytics:*")
    assert len(keys) >= 1

    resp2 = await client.get(
        "/api/v1/analytics/summary/",
        headers=auth_headers,
        params={"start_date": "2025-01-01", "end_date": "2025-12-31"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["total_events"] >= 1


@pytest.mark.asyncio
async def test_summary_repository_direct(db_session: AsyncSession):
    from src.analytics.repositories import get_summary
    from datetime import date

    await db_session.execute(insert(Event), [
        {"company_id": 42, "user_id": "u1", "event_type": "click", "payload": {}},
        {"company_id": 42, "user_id": "u2", "event_type": "view", "payload": {}},
    ])
    await db_session.commit()

    result = await get_summary(db_session, 42, date(2026, 1, 1), date(2026, 12, 31))
    assert result["company_id"] == 42
    assert result["total_users"] == 2
    assert result["total_events"] == 2
    assert len(result["events"]) == 2


@pytest.mark.asyncio
async def test_summary_includes_full_end_date(db_session: AsyncSession):
    """An event late on the last day of the range must be counted (no off-by-one)."""
    from src.analytics.repositories import get_summary
    from datetime import date, datetime, timezone

    await db_session.execute(insert(Event), [{
        "company_id": 7,
        "user_id": "edge",
        "event_type": "click",
        "payload": {},
        "created_at": datetime(2026, 3, 15, 23, 59, 59, tzinfo=timezone.utc),
    }])
    await db_session.commit()

    result = await get_summary(db_session, 7, date(2026, 3, 1), date(2026, 3, 15))
    assert result["total_events"] == 1
    assert result["total_users"] == 1


@pytest.mark.asyncio
async def test_summary_excludes_day_after_end_date(db_session: AsyncSession):
    """An event on the day after end_date must NOT be counted."""
    from src.analytics.repositories import get_summary
    from datetime import date, datetime, timezone

    await db_session.execute(insert(Event), [{
        "company_id": 8,
        "user_id": "out",
        "event_type": "click",
        "payload": {},
        "created_at": datetime(2026, 3, 16, 0, 0, 1, tzinfo=timezone.utc),
    }])
    await db_session.commit()

    result = await get_summary(db_session, 8, date(2026, 3, 1), date(2026, 3, 15))
    assert result["total_events"] == 0


@pytest.mark.asyncio
async def test_cache_service_direct(test_redis, db_session: AsyncSession):
    from src.analytics.service import get_cached_summary
    from datetime import date, datetime, timezone

    await db_session.execute(insert(Event), [{
        "company_id": 99, "user_id": "cache-test", "event_type": "view", "payload": {},
        "created_at": datetime(2025, 6, 15, tzinfo=timezone.utc),
    }])
    await db_session.commit()

    result = await get_cached_summary(test_redis, db_session, 99, date(2025, 1, 1), date(2025, 12, 31))
    assert result["total_events"] == 1

    cached = await test_redis.get("cache:analytics:99:2025-01-01:2025-12-31")
    assert cached is not None

    result2 = await get_cached_summary(test_redis, db_session, 99, date(2025, 1, 1), date(2025, 12, 31))
    assert result2["total_events"] == 1


@pytest.mark.asyncio
async def test_summary_today_range_not_cached(test_redis, db_session: AsyncSession):
    """Ranges that reach today must not be cached (data is still changing)."""
    from src.analytics.service import get_cached_summary
    from datetime import date, datetime, timezone

    await test_redis.flushdb()
    await db_session.execute(insert(Event), [{
        "company_id": 123, "user_id": "live", "event_type": "view", "payload": {},
    }])
    await db_session.commit()

    today = datetime.now(timezone.utc).date()
    await get_cached_summary(test_redis, db_session, 123, date(today.year, 1, 1), today)

    keys = await test_redis.keys("cache:analytics:123:*")
    assert keys == []
