import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_app_exception_handler(client: AsyncClient):
    from src.exceptions import AppException
    from src.main import app
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get("/test-error")
    async def raise_error():
        raise AppException(status_code=418, message="I'm a teapot")

    resp = await client.get("/test-error")
    assert resp.status_code == 418
    assert resp.json() == {"detail": "I'm a teapot"}
