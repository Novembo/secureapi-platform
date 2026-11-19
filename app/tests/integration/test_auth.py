"""Integration tests for Phase 2: Authentication (AUTH-01 to AUTH-09) and acceptance tests.

Covers:
- ACC-02: Refresh token reuse revokes entire family
- ACC-03: Logout, logout-all, reset-password invalidate access tokens immediately
- ACC-11: Uniform responses for register, forgot-password, login
- ACC-12: JWT validation edge cases (signature, alg=none, aud, iss, exp, type)
- ACC-13: Account lockout after failed attempts and rate limiting
"""

import uuid
from datetime import timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import hash_password, hash_token
from app.models.email_token import EmailToken
from app.models.user import User

VALID_PASSWORD = "StrongP@ssw0rd!2026"


def create_user(
    db: Session,
    email: str = "testuser@example.com",
    password: str = VALID_PASSWORD,
    full_name: str = "Test User",
    is_verified: bool = True,
    is_active: bool = True,
    is_platform_admin: bool = False,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
        is_verified=is_verified,
        is_active=is_active,
        is_platform_admin=is_platform_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ==============================================================================
# ACC-02: Refresh token reuse revokes entire family
# ==============================================================================


def test_ACC_02_refresh_reuse_revokes_family(client: TestClient, db_session: Session) -> None:
    """When an already-replaced refresh token is replayed, 401 is returned and

    the entire token family is revoked (the newer token also fails).
    """
    create_user(db_session, email="alice@example.com", is_verified=True)

    # 1. Login to get initial token pair
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": VALID_PASSWORD},
    )
    assert login_res.status_code == 200
    token_1 = login_res.json()["refresh_token"]

    # 2. First refresh: token_1 -> token_2
    refresh_res_1 = client.post("/api/v1/auth/refresh", json={"refresh_token": token_1})
    assert refresh_res_1.status_code == 200
    token_2 = refresh_res_1.json()["refresh_token"]
    assert token_2 != token_1

    # 3. Second refresh using token_2: token_2 -> token_3
    refresh_res_2 = client.post("/api/v1/auth/refresh", json={"refresh_token": token_2})
    assert refresh_res_2.status_code == 200
    token_3 = refresh_res_2.json()["refresh_token"]

    # 4. Replay token_1 (already replaced by token_2) -> reuse detected!
    replay_res = client.post("/api/v1/auth/refresh", json={"refresh_token": token_1})
    assert replay_res.status_code == 401

    # 5. Verify entire family is revoked: even token_3 (the latest valid one) must now fail!
    token_3_res = client.post("/api/v1/auth/refresh", json={"refresh_token": token_3})
    assert token_3_res.status_code == 401


# ==============================================================================
# ACC-03: Session invalidation (logout, logout-all, reset-password)
# ==============================================================================


def test_ACC_03_logout_invalidates_access_token(client: TestClient, db_session: Session) -> None:
    """After logout, the access token issued before is rejected immediately."""
    create_user(db_session, email="bob@example.com", is_verified=True)

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": VALID_PASSWORD},
    )
    assert login_res.status_code == 200
    access_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # Verify access token works on /auth/me
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "bob@example.com"

    # Logout
    logout_res = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_res.status_code == 204

    # Access token must now be rejected
    me_after_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_after_res.status_code == 401


def test_ACC_03_logout_all_invalidates_access_token(
    client: TestClient, db_session: Session
) -> None:
    """After logout-all, all access tokens issued for that user are rejected."""
    create_user(db_session, email="charlie@example.com", is_verified=True)

    # Session 1
    login_1 = client.post(
        "/api/v1/auth/login",
        json={"email": "charlie@example.com", "password": VALID_PASSWORD},
    )
    token_1 = login_1.json()["access_token"]

    # Session 2
    login_2 = client.post(
        "/api/v1/auth/login",
        json={"email": "charlie@example.com", "password": VALID_PASSWORD},
    )
    token_2 = login_2.json()["access_token"]

    # Both valid
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_1}"}).status_code
        == 200
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_2}"}).status_code
        == 200
    )

    # Logout all from session 1
    logout_all_res = client.post(
        "/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {token_1}"}
    )
    assert logout_all_res.status_code == 204

    # Both tokens must now be rejected
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_1}"}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_2}"}).status_code
        == 401
    )


def test_ACC_03_reset_password_invalidates_sessions(
    client: TestClient, db_session: Session, fake_clock: FakeClock
) -> None:
    """After password reset, all active sessions and access tokens are invalidated."""
    user = create_user(db_session, email="david@example.com", is_verified=True)

    # Login to obtain an access token
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "david@example.com", "password": VALID_PASSWORD},
    )
    token = login_res.json()["access_token"]
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 200
    )

    # Create a valid password reset token
    raw_token = "secret-reset-token-48-chars-random-string-abc123"
    email_tok = EmailToken(
        id=uuid.uuid4(),
        user_id=user.id,
        purpose="reset_password",
        token_hash=hash_token(raw_token),
        expires_at=fake_clock.now() + timedelta(hours=1),
    )
    db_session.add(email_tok)
    db_session.commit()

    # Reset password
    new_password = "NewStrongP@ssw0rd!2026"
    reset_res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": new_password},
    )
    assert reset_res.status_code == 204

    # Old access token must be invalidated
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )

    # Login with new password must succeed
    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": "david@example.com", "password": new_password},
    )
    assert new_login.status_code == 200


# ==============================================================================
# ACC-11: Uniform responses for register, forgot-password, login
# ==============================================================================


def test_ACC_11_register_uniform_response(client: TestClient, db_session: Session) -> None:
    """Register returns identical 202 status and body whether email exists or not."""
    create_user(db_session, email="existing@example.com", is_verified=True)

    res_existing = client.post(
        "/api/v1/auth/register",
        json={
            "email": "existing@example.com",
            "password": VALID_PASSWORD,
            "full_name": "Existing User",
        },
    )
    res_new = client.post(
        "/api/v1/auth/register",
        json={
            "email": "brandnew@example.com",
            "password": VALID_PASSWORD,
            "full_name": "New User",
        },
    )

    assert res_existing.status_code == 202
    assert res_new.status_code == 202
    assert res_existing.json() == res_new.json()


def test_ACC_11_forgot_password_uniform_response(client: TestClient, db_session: Session) -> None:
    """Forgot-password returns identical 202 status and body whether email exists or not."""
    create_user(db_session, email="known@example.com", is_verified=True)

    res_known = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "known@example.com"},
    )
    res_unknown = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "unknown@example.com"},
    )

    assert res_known.status_code == 202
    assert res_unknown.status_code == 202
    assert res_known.json() == res_unknown.json()


def test_ACC_11_login_uniform_response(client: TestClient, db_session: Session) -> None:
    """Login returns identical 401 error message for bad password, unknown user, locked user."""
    create_user(db_session, email="user1@example.com", is_verified=True)

    # 1. Unknown user
    res_unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": VALID_PASSWORD},
    )
    # 2. Wrong password
    res_wrong_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "user1@example.com", "password": "WrongPassword123!"},
    )

    assert res_unknown.status_code == 401
    assert res_wrong_pw.status_code == 401
    assert res_unknown.json()["error"]["code"] == "invalid_credentials"
    assert res_wrong_pw.json()["error"]["code"] == "invalid_credentials"
    assert res_unknown.json()["error"]["message"] == res_wrong_pw.json()["error"]["message"]


# ==============================================================================
# ACC-12: JWT validation edge cases
# ==============================================================================


def test_ACC_12_jwt_edge_cases(
    client: TestClient, db_session: Session, fake_clock: FakeClock
) -> None:
    """Tests JWT rejection for bad signature, alg=none, bad aud, bad iss, expired, bad type."""
    user = create_user(db_session, email="jwtuser@example.com", is_verified=True)

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "jwtuser@example.com", "password": VALID_PASSWORD},
    )
    real_token = login_res.json()["access_token"]
    now_ts = int(fake_clock.now().timestamp())

    # 1. Falsified signature
    tampered = real_token[:-4] + "fake"
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"}).status_code
        == 401
    )

    # 2. alg = none
    token_none = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(uuid.uuid4()),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": now_ts,
            "exp": now_ts + 900,
            "jti": str(uuid.uuid4()),
            "type": "access",
        },
        key="",
        algorithm="none",
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_none}"}).status_code
        == 401
    )

    # 3. Wrong audience
    token_bad_aud = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(uuid.uuid4()),
            "iss": settings.JWT_ISSUER,
            "aud": "wrong-audience",
            "iat": now_ts,
            "exp": now_ts + 900,
            "jti": str(uuid.uuid4()),
            "type": "access",
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_bad_aud}"}
        ).status_code
        == 401
    )

    # 4. Wrong issuer
    token_bad_iss = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(uuid.uuid4()),
            "iss": "rogue-issuer",
            "aud": settings.JWT_AUDIENCE,
            "iat": now_ts,
            "exp": now_ts + 900,
            "jti": str(uuid.uuid4()),
            "type": "access",
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_bad_iss}"}
        ).status_code
        == 401
    )

    # 5. Expired token
    token_expired = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(uuid.uuid4()),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": now_ts - 1000,
            "exp": now_ts - 100,
            "jti": str(uuid.uuid4()),
            "type": "access",
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_expired}"}
        ).status_code
        == 401
    )

    # 6. Wrong token type (e.g. refresh instead of access)
    token_bad_type = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(uuid.uuid4()),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": now_ts,
            "exp": now_ts + 900,
            "jti": str(uuid.uuid4()),
            "type": "refresh",
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_bad_type}"}
        ).status_code
        == 401
    )


# ==============================================================================
# ACC-13: Account lockout after failed attempts and rate limiting
# ==============================================================================


def test_ACC_13_rate_limiting_login(client: TestClient, db_session: Session) -> None:
    """Rate limiting triggers 429 with Retry-After header after exceeding limit."""
    limiter.reset()
    create_user(db_session, email="ratelimit@example.com", is_verified=True)

    # 5 attempts allowed by RATE_LIMIT_LOGIN = 5/minute
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit@example.com", "password": "WrongPassword123!"},
        )

    # 6th attempt must trigger 429
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit@example.com", "password": "WrongPassword123!"},
    )
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in res.headers
    limiter.reset()


def test_ACC_13_lockout_after_max_attempts(
    client: TestClient, db_session: Session, fake_clock: FakeClock
) -> None:
    """Account is locked after LOGIN_MAX_ATTEMPTS failed logins."""
    limiter.reset()
    user = create_user(db_session, email="lockout@example.com", is_verified=True)

    # Fail LOGIN_MAX_ATTEMPTS times, resetting limiter each time so we isolate lockout logic
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        limiter.reset()
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "lockout@example.com", "password": "WrongPassword123!"},
        )
        assert res.status_code == 401

    limiter.reset()
    # Now account must be locked: even the correct password is rejected with 401
    locked_res = client.post(
        "/api/v1/auth/login",
        json={"email": "lockout@example.com", "password": VALID_PASSWORD},
    )
    assert locked_res.status_code == 401
    assert locked_res.json()["error"]["code"] == "invalid_credentials"

    # Fast forward past lockout duration
    fake_clock.advance(minutes=settings.LOGIN_LOCK_MINUTES + 1)
    limiter.reset()

    # Now login with correct password succeeds and resets the lock
    unlock_res = client.post(
        "/api/v1/auth/login",
        json={"email": "lockout@example.com", "password": VALID_PASSWORD},
    )
    assert unlock_res.status_code == 200

    # User's failed_login_attempts in DB should be reset to 0
    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_ACC_13_email_not_verified_error(client: TestClient, db_session: Session) -> None:
    """If user enters correct password, but email is not verified: 403 email_not_verified."""
    create_user(db_session, email="unverified@example.com", is_verified=False)

    # Wrong password -> 401 (not revealing unverified status)
    wrong_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "unverified@example.com", "password": "WrongPassword123!"},
    )
    assert wrong_pw.status_code == 401

    # Correct password -> 403 email_not_verified
    correct_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "unverified@example.com", "password": VALID_PASSWORD},
    )
    assert correct_pw.status_code == 403
    assert correct_pw.json()["error"]["code"] == "email_not_verified"


def test_verify_email_success_and_invalid_token(
    client: TestClient, db_session: Session, fake_clock: FakeClock
) -> None:
    """Tests verify-email endpoint with valid and invalid tokens."""
    user = create_user(db_session, email="toverify@example.com", is_verified=False)
    raw_token = "verify-email-token-1234567890123456789012345678"
    tok = EmailToken(
        id=uuid.uuid4(),
        user_id=user.id,
        purpose="verify_email",
        token_hash=hash_token(raw_token),
        expires_at=fake_clock.now() + timedelta(hours=24),
    )
    db_session.add(tok)
    db_session.commit()

    # Invalid token -> 400
    res_bad = client.post("/api/v1/auth/verify-email", json={"token": "invalid-token"})
    assert res_bad.status_code == 400

    # Valid token -> 204
    res_good = client.post("/api/v1/auth/verify-email", json={"token": raw_token})
    assert res_good.status_code == 204

    db_session.refresh(user)
    assert user.is_verified is True

    # Re-using already consumed token -> 400
    res_reused = client.post("/api/v1/auth/verify-email", json={"token": raw_token})
    assert res_reused.status_code == 400
