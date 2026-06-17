import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_event(client: AsyncClient, auth_headers: dict, test_redis):
    resp = await client.post(
        "/api/v1/events/",
        headers=auth_headers,
        json={
            "company_id": 1,
            "user_id": "user-123",
            "event_type": "page_view",
            "payload": {"url": "/pricing", "browser": "Chrome"},
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    # The server returns the idempotency key it assigned.
    import uuid
    uuid.UUID(body["event_id"])

    queue_len = await test_redis.llen("queue:events")
    assert queue_len >= 1


@pytest.mark.asyncio
async def test_create_event_unauthorized(client: AsyncClient):
    resp = await client.post(
        "/api/v1/events/",
        json={
            "company_id": 1,
            "user_id": "user-123",
            "event_type": "page_view",
            "payload": {},
        },
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_event_missing_fields(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/v1/events/",
        headers=auth_headers,
        json={"event_type": "click"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_event_long_user_id(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/v1/events/",
        headers=auth_headers,
        json={
            "user_id": "x" * 256,
            "event_type": "click",
            "payload": {},
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_event_company_from_jwt(client: AsyncClient, auth_headers: dict, test_redis):
    resp = await client.post(
        "/api/v1/events/",
        headers=auth_headers,
        json={
            "company_id": 999,
            "user_id": "user-1",
            "event_type": "click",
            "payload": {},
        },
    )
    assert resp.status_code == 202

    raw = await test_redis.lindex("queue:events", -1)
    data = json.loads(raw)
    assert data["company_id"] == 1
    assert data["company_id"] != 999


@pytest.mark.asyncio
async def test_create_event_with_custom_created_at(client: AsyncClient, auth_headers: dict, test_redis):
    resp = await client.post(
        "/api/v1/events/",
        headers=auth_headers,
        json={
            "user_id": "user-1",
            "event_type": "click",
            "payload": {},
            "created_at": "2025-06-15T12:00:00",
        },
    )
    assert resp.status_code == 202

    raw = await test_redis.lindex("queue:events", -1)
    data = json.loads(raw)
    assert "2025-06-15" in data["created_at"]
