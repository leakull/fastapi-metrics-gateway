from datetime import timedelta

from src.auth.service import create_access_token, get_password_hash, verify_password


def test_password_hash_and_verify():
    password = "my_secret_password"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_create_access_token():
    token = create_access_token(data={"sub": "user-123"})
    import jwt
    from src.config import settings
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "user-123"
    assert "exp" in payload


def test_create_access_token_custom_expiry():
    token = create_access_token(data={"sub": "u1"}, expires_delta=timedelta(minutes=5))
    import jwt
    from src.config import settings
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "u1"


def test_settings_defaults():
    from src.config import Settings
    s = Settings(
        DATABASE_URL="sqlite+aiosqlite://",
        REDIS_URL="redis://localhost:6379/0",
        JWT_SECRET="test-secret",
    )
    assert s.JWT_ALGORITHM == "HS256"
    assert s.JWT_EXPIRE_MINUTES == 15
    assert s.BATCH_INTERVAL == 5
    assert s.BATCH_SIZE == 1000


def test_settings_default_secret_warning(caplog):
    import logging
    from src.config import Settings

    with caplog.at_level(logging.WARNING, logger="src.config"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite://",
            REDIS_URL="redis://localhost:6379/0",
            JWT_SECRET="super-secret-key-change-in-production",
        )
    assert "JWT_SECRET is the default value" in caplog.text
