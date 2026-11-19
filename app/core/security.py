import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.clock import get_clock
from app.core.common_passwords import is_common_password
from app.core.config import settings
from app.core.exceptions import TokenExpiredError, TokenInvalidError, ValidationError


def get_password_hasher() -> PasswordHasher:
    """Returns a PasswordHasher configured from settings."""
    if settings.ENVIRONMENT == "test":
        # Lightweight parameters for fast test runs
        return PasswordHasher(
            time_cost=1,
            memory_cost=1024,
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )
    return PasswordHasher(
        time_cost=settings.ARGON2_TIME_COST,
        memory_cost=settings.ARGON2_MEMORY_KIB,
        parallelism=settings.ARGON2_PARALLELISM,
        hash_len=32,
        salt_len=16,
    )


# Precomputed dummy hash for constant-time execution on failed login when user doesn't exist
_DUMMY_HASHER = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
_DUMMY_HASH = _DUMMY_HASHER.hash("dummy-non-existent-user-password-constant-time")


def hash_password(password: str) -> str:
    hasher = get_password_hasher()
    return hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    hasher = get_password_hasher()
    try:
        return hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, Exception):
        return False


def verify_dummy_password(plain_password: str) -> None:
    """Consumes comparable Argon2 CPU time when user is not found."""
    try:
        hasher = get_password_hasher()
        hasher.hash(plain_password)
    except Exception:  # noqa: S110
        pass


def validate_password_policy(password: str, email: str | None = None) -> None:
    """Validates password length (12-128 chars), common passwords, and local part of email."""
    if len(password) < 12 or len(password) > 128:
        raise ValidationError("Le mot de passe doit contenir entre 12 et 128 caractères.")

    if is_common_password(password):
        raise ValidationError(
            "Ce mot de passe est trop courant. Veuillez en choisir un plus robuste."
        )

    if email and "@" in email:
        local_part = email.split("@")[0].lower()
        if len(local_part) >= 3 and local_part in password.lower():
            raise ValidationError(
                "Le mot de passe ne doit pas contenir la partie locale de votre adresse email."
            )


def generate_secure_token() -> str:
    """Generates a high-entropy URL-safe token (48 bytes entropy)."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Computes SHA-256 hex digest of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    user_id: str,
    family_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    clock = get_clock()
    now = clock.now()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)

    payload: dict[str, Any] = {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "sub": user_id,
        "sid": family_id,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodes and strictly validates the JWT access token using the injectable clock."""
    clock = get_clock()
    now_ts = int(clock.now().timestamp())
    try:
        unverified_headers = jwt.get_unverified_header(token)
        if unverified_headers.get("alg") != "HS256":
            raise TokenInvalidError("Algorithme de signature non autorisé.")

        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub", "sid", "jti", "type"],
                "verify_exp": False,  # Validated explicitly with injectable clock below
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
        if payload.get("type") != "access":
            raise TokenInvalidError("Type de jeton invalide.")

        if payload.get("exp", 0) <= now_ts:
            raise TokenExpiredError("Le jeton d'accès a expiré.")

        return payload
    except (TokenExpiredError, TokenInvalidError):
        raise
    except (jwt.InvalidTokenError, Exception) as e:
        raise TokenInvalidError("Jeton d'accès invalide.") from e
