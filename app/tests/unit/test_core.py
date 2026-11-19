from datetime import UTC, datetime

import pytest

from app.core.clock import FakeClock
from app.core.config import Settings
from app.core.exceptions import (
    TokenExpiredError,
    TokenInvalidError,
    ValidationError,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_policy,
    verify_password,
)


def test_fake_clock_operations() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    clock = FakeClock(now)
    assert clock.now() == now

    clock.advance(minutes=15)
    assert clock.now() == datetime(2026, 1, 1, 12, 15, 0, tzinfo=UTC)

    new_time = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    clock.set_time(new_time)
    assert clock.now() == new_time


def test_password_policy_validation() -> None:
    # Too short (< 12 chars)
    with pytest.raises(ValidationError, match="entre 12 et 128 caractères"):
        validate_password_policy("Short1!")

    # Common password
    with pytest.raises(ValidationError, match="trop courant"):
        validate_password_policy("password12345")

    # Contains email local part
    with pytest.raises(ValidationError, match="partie locale"):
        validate_password_policy("superrobertpass123", email="robert@example.com")

    # Valid password
    validate_password_policy("SecureCorrectHorseBatteryStaple2026!", email="user@example.com")


def test_password_hash_and_verify() -> None:
    pw = "SuperSecurePassword123!"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_token_generation_and_hashing() -> None:
    token1 = generate_secure_token()
    token2 = generate_secure_token()
    assert token1 != token2
    assert len(token1) >= 48

    hash1 = hash_token(token1)
    hash2 = hash_token(token1)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex


def test_jwt_create_and_decode(fake_clock: FakeClock) -> None:
    user_id = "user-uuid-1234"
    family_id = "family-uuid-5678"

    token = create_access_token(user_id=user_id, family_id=family_id)
    payload = decode_access_token(token)

    assert payload["sub"] == user_id
    assert payload["sid"] == family_id
    assert payload["type"] == "access"
    assert "jti" in payload


def test_jwt_expired(fake_clock: FakeClock) -> None:
    user_id = "user-uuid-1234"
    family_id = "family-uuid-5678"

    token = create_access_token(user_id=user_id, family_id=family_id)

    # Advance beyond access token TTL (15 min)
    fake_clock.advance(minutes=16)

    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_jwt_invalid_signature() -> None:
    user_id = "user-uuid-1234"
    family_id = "family-uuid-5678"

    token = create_access_token(user_id=user_id, family_id=family_id)
    tampered_token = token[:-5] + "abcde"

    with pytest.raises(TokenInvalidError):
        decode_access_token(tampered_token)


def test_production_settings_validation() -> None:
    # Prod with short secret should raise
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(ENVIRONMENT="prod", JWT_SECRET="short-secret")

    # Prod with example secret should raise
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(
            ENVIRONMENT="prod",
            JWT_SECRET="default-dev-secret-change-in-production-minimum-32-chars",
        )
