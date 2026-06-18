import pytest
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from src.config import settings
from src.auth.service import create_access_token


def test_create_and_decode_token():
    token = create_access_token(data={"sub": "user-42"})
    payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "user-42"
    assert "exp" in payload


def test_token_with_custom_expiry():
    token = create_access_token(data={"sub": "u1"}, expires_delta=timedelta(hours=2))
    payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "u1"


def test_invalid_token_rejected():
    with pytest.raises(pyjwt.exceptions.DecodeError):
        pyjwt.decode("invalid.token.here", settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def test_token_with_wrong_secret_rejected():
    token = create_access_token(data={"sub": "user-1"})
    with pytest.raises(pyjwt.exceptions.InvalidSignatureError):
        pyjwt.decode(token, "wrong-secret", algorithms=[settings.JWT_ALGORITHM])


def test_missing_sub_claim():
    now = datetime.now(timezone.utc) + timedelta(minutes=5)
    token = pyjwt.encode({"exp": now}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload.get("sub") is None
