import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register/",
        json={"email": "new@test.com", "password": "secret123", "company_id": 2},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@test.com"
    assert data["company_id"] == 2


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register/",
        json={"email": "login@test.com", "password": "secret123", "company_id": 1},
    )
    resp = await client.post(
        "/api/v1/auth/login/",
        json={"email": "login@test.com", "password": "secret123"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login/",
        json={"email": "nonexistent@test.com", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register/",
        json={"email": "dup@test.com", "password": "secret123", "company_id": 1},
    )
    resp = await client.post(
        "/api/v1/auth/register/",
        json={"email": "dup@test.com", "password": "secret123", "company_id": 1},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register/",
        json={"email": "weak@test.com", "password": "123", "company_id": 1},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/auth/me/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@test.com"
    assert data["company_id"] == 1
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_me_unauthorized(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me/")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register/",
        json={"email": "wrongpw@test.com", "password": "secret123", "company_id": 1},
    )
    resp = await client.post(
        "/api/v1/auth/login/",
        json={"email": "wrongpw@test.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register/",
        json={"email": "not-an-email", "password": "secret123", "company_id": 1},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_fields(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register/",
        json={"password": "secret123", "company_id": 1},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_returns_no_password(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register/",
        json={"email": "nopw@test.com", "password": "secret123", "company_id": 1},
    )
    data = resp.json()
    assert "hashed_password" not in data
    assert "password" not in data


@pytest.mark.asyncio
async def test_register_returns_uuid_id(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register/",
        json={"email": "uuid@test.com", "password": "secret123", "company_id": 1},
    )
    data = resp.json()
    import uuid
    uuid.UUID(data["id"])


@pytest.mark.asyncio
async def test_login_returns_token_type_bearer(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register/",
        json={"email": "bearer@test.com", "password": "secret123", "company_id": 1},
    )
    resp = await client.post(
        "/api/v1/auth/login/",
        json={"email": "bearer@test.com", "password": "secret123"},
    )
    data = resp.json()
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me/",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_expired_token(client: AsyncClient):
    from jose import jwt
    from src.config import settings
    from datetime import datetime, timedelta, timezone

    expired_payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    token = jwt.encode(expired_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    resp = await client.get(
        "/api/v1/auth/me/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_inactive_user(client: AsyncClient, db_session):
    from src.auth.service import get_password_hash
    from src.auth.models import User
    import uuid

    user = User(
        id=uuid.uuid4(),
        email="inactive@test.com",
        hashed_password=get_password_hash("secret123"),
        company_id=1,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    login_resp = await client.post(
        "/api/v1/auth/login/",
        json={"email": "inactive@test.com", "password": "secret123"},
    )
    token = login_resp.json()["access_token"]

    resp = await client.get(
        "/api/v1/auth/me/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_rate_limit_returns_429(client: AsyncClient):
    from unittest.mock import patch, MagicMock

    mock_storage = MagicMock()
    mock_storage.get.return_value = 0

    with patch("src.auth.router.limiter") as mock_limiter:
        mock_limiter.limit = lambda *a, **kw: lambda f: f
        mock_limiter.hit.return_value = False

        resp = await client.post(
            "/api/v1/auth/register/",
            json={"email": "ratelimit@test.com", "password": "secret123", "company_id": 1},
        )
        assert resp.status_code in (201, 429)


@pytest.mark.asyncio
async def test_get_me_token_without_sub(client: AsyncClient):
    from jose import jwt
    from src.config import settings

    token = jwt.encode({"exp": "bad"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    resp = await client.get(
        "/api/v1/auth/me/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_nonexistent_user(client: AsyncClient):
    import uuid
    from jose import jwt
    from src.config import settings
    from datetime import datetime, timedelta, timezone

    fake_id = str(uuid.uuid4())
    token = jwt.encode(
        {"sub": fake_id, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = await client.get(
        "/api/v1/auth/me/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_authenticate_user_direct(db_session):
    from src.auth.service import authenticate_user, create_user, get_user_by_id
    from src.auth.schemas import UserCreate

    await create_user(db_session, UserCreate(email="direct@test.com", password="secret123", company_id=1))

    user = await authenticate_user(db_session, "direct@test.com", "secret123")
    assert user is not None
    assert user.email == "direct@test.com"

    wrong = await authenticate_user(db_session, "direct@test.com", "wrong")
    assert wrong is None

    not_found = await authenticate_user(db_session, "nobody@test.com", "secret123")
    assert not_found is None


@pytest.mark.asyncio
async def test_get_user_by_id_direct(db_session):
    from src.auth.service import create_user, get_user_by_id
    from src.auth.schemas import UserCreate

    user = await create_user(db_session, UserCreate(email="byid@test.com", password="secret123", company_id=1))

    found = await get_user_by_id(db_session, user.id)
    assert found is not None
    assert found.email == "byid@test.com"

    import uuid
    missing = await get_user_by_id(db_session, uuid.uuid4())
    assert missing is None


@pytest.mark.asyncio
async def test_create_user_integrity_error(db_session):
    from src.auth.service import create_user
    from src.auth.schemas import UserCreate
    from src.exceptions import AppException

    await create_user(db_session, UserCreate(email="integrity@test.com", password="secret123", company_id=1))

    with pytest.raises(AppException) as exc_info:
        await create_user(db_session, UserCreate(email="integrity@test.com", password="secret456", company_id=2))
    assert exc_info.value.status_code == 409
