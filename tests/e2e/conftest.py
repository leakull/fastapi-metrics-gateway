from collections.abc import AsyncGenerator

import pytest_asyncio
import httpx
from httpx import AsyncClient

BASE_URL = "http://localhost:8080"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def reset_db():
    import asyncio
    await asyncio.sleep(1)

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.get("/health")
        if resp.status_code != 200:
            pytest.skip("API is not running")


@pytest_asyncio.fixture
async def api() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client
