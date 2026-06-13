import asyncio
import time

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.e2e


async def register_and_login(api: AsyncClient, email: str, password: str = "secret123", company_id: int = 1) -> str:
    await api.post("/api/v1/auth/register/", json={"email": email, "password": password, "company_id": company_id})
    resp = await api.post("/api/v1/auth/login/", json={"email": email, "password": password})
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_full_analytics_flow(api: AsyncClient):
    token = await register_and_login(api, "e2e_flow@test.com", company_id=10)
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(5):
        resp = await api.post("/api/v1/events/", headers=headers, json={
            "user_id": f"u{i}",
            "event_type": "page_view",
            "payload": {"url": f"/page{i}"},
        })
        assert resp.status_code == 202

    await asyncio.sleep(7)

    resp = await api.get("/api/v1/analytics/summary/", headers=headers, params={
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["company_id"] == 10
    assert data["total_events"] == 5
    assert data["total_users"] == 5


@pytest.mark.asyncio
async def test_multi_user_flow(api: AsyncClient):
    token_a = await register_and_login(api, "multi_a@test.com", company_id=100)
    token_b = await register_and_login(api, "multi_b@test.com", company_id=200)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    await api.post("/api/v1/events/", headers=headers_a, json={
        "user_id": "a1", "event_type": "click", "payload": {},
    })
    await api.post("/api/v1/events/", headers=headers_b, json={
        "user_id": "b1", "event_type": "click", "payload": {},
    })

    await asyncio.sleep(7)

    resp_a = await api.get("/api/v1/analytics/summary/", headers=headers_a, params={
        "start_date": "2026-01-01", "end_date": "2026-12-31",
    })
    resp_b = await api.get("/api/v1/analytics/summary/", headers=headers_b, params={
        "start_date": "2026-01-01", "end_date": "2026-12-31",
    })

    data_a = resp_a.json()
    data_b = resp_b.json()
    assert data_a["company_id"] == 100
    assert data_b["company_id"] == 200
    assert data_a["total_events"] == 1
    assert data_b["total_events"] == 1


@pytest.mark.asyncio
async def test_concurrent_events(api: AsyncClient):
    token = await register_and_login(api, "concurrent@test.com", company_id=300)
    headers = {"Authorization": f"Bearer {token}"}

    async def send_event(i: int):
        return await api.post("/api/v1/events/", headers=headers, json={
            "user_id": f"conc-{i}", "event_type": "click", "payload": {},
        })

    results = await asyncio.gather(*[send_event(i) for i in range(20)])
    assert all(r.status_code == 202 for r in results)

    await asyncio.sleep(7)

    resp = await api.get("/api/v1/analytics/summary/", headers=headers, params={
        "start_date": "2026-01-01", "end_date": "2026-12-31",
    })
    assert resp.status_code == 200
    assert resp.json()["total_events"] == 20
    assert resp.json()["total_users"] == 20


@pytest.mark.asyncio
async def test_event_idempotency(api: AsyncClient):
    token = await register_and_login(api, "idempotent@test.com", company_id=400)
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(3):
        await api.post("/api/v1/events/", headers=headers, json={
            "user_id": "same", "event_type": "dup", "payload": {},
        })

    await asyncio.sleep(7)

    resp = await api.get("/api/v1/analytics/summary/", headers=headers, params={
        "start_date": "2026-01-01", "end_date": "2026-12-31",
    })
    data = resp.json()
    assert data["total_events"] == 3
    assert data["total_users"] == 1
