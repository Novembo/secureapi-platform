import json
import logging
from unittest.mock import MagicMock

from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from app.core.config import settings
from app.core.exceptions import (
    AlreadyMemberError,
    DomainError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvitationInvalidError,
    LastOwnerError,
    NotFoundError,
    OrganizationInactiveError,
    PermissionDeniedError,
    PrivilegeEscalationError,
    RateLimitedError,
    RoleInUseError,
    RoleNameTakenError,
    ServiceUnavailableError,
    SlugTakenError,
    SystemRoleImmutableError,
    TokenExpiredError,
    TokenInvalid400Error,
    TokenInvalidError,
    ValidationError,
)
from app.core.logging import JSONFormatter, set_correlation_id, setup_logging
from app.core.rate_limit import get_real_client_ip
from app.core.security import verify_dummy_password
from app.main import app

aux_router = APIRouter()


class SampleModel(BaseModel):
    name: str


@aux_router.post("/test-validation")
def route_validation(payload: SampleModel) -> dict[str, str]:
    return {"name": payload.name}


@aux_router.get("/test-domain-error")
def route_domain_error() -> None:
    raise PermissionDeniedError("Custom denied message")


@aux_router.get("/test-unhandled-error")
def route_unhandled_error() -> None:
    raise RuntimeError("Unexpected failure")


@aux_router.get("/test-rate-limit-exceeded")
def route_rate_limit() -> None:
    raise RateLimitExceeded(MagicMock())


app.include_router(aux_router, prefix="/api/v1")


def test_body_limit_middleware(client: TestClient) -> None:
    # Set Content-Length header exceeding MAX_BODY_BYTES
    large_size = settings.MAX_BODY_BYTES + 100
    response = client.post(
        "/api/v1/test-validation",
        headers={"Content-Length": str(large_size)},
        content=b"x",
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_validation_error_handler(client: TestClient) -> None:
    response = client.post("/api/v1/test-validation", json={})
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "validation_error"
    assert len(data["error"]["details"]) > 0


def test_domain_error_handler(client: TestClient) -> None:
    response = client.get("/api/v1/test-domain-error")
    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "permission_denied"
    assert data["error"]["message"] == "Custom denied message"


def test_unhandled_exception_handler() -> None:
    unhandled_client = TestClient(app, raise_server_exceptions=False)
    response = unhandled_client.get("/api/v1/test-unhandled-error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"]["code"] == "internal_error"


def test_rate_limit_handler(client: TestClient) -> None:
    response = client.get("/api/v1/test-rate-limit-exceeded")
    assert response.status_code == 429
    assert response.headers.get("Retry-After") is not None
    data = response.json()
    assert data["error"]["code"] == "rate_limited"


def test_security_headers_prod_mode(client: TestClient) -> None:
    original_env = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "prod"
        response = client.get("/health")
        assert "Strict-Transport-Security" in response.headers
    finally:
        settings.ENVIRONMENT = original_env


def test_json_formatter() -> None:
    set_correlation_id("test-req-id-1234")
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test log message",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    parsed = json.loads(formatted)
    assert parsed["message"] == "Test log message"
    assert parsed["request_id"] == "test-req-id-1234"
    assert parsed["level"] == "INFO"


def test_get_real_client_ip() -> None:
    scope = {
        "type": "http",
        "client": ("10.0.0.1", 12345),
        "headers": [(b"x-forwarded-for", b"203.0.113.195, 70.41.3.18")],
    }
    request = Request(scope)

    # Without trusted proxies, direct client IP is returned
    settings.TRUSTED_PROXIES = []
    assert get_real_client_ip(request) == "10.0.0.1"

    # With trusted proxies, leftmost IP from X-Forwarded-For is returned
    settings.TRUSTED_PROXIES = ["10.0.0.0/8"]
    assert get_real_client_ip(request) == "203.0.113.195"

    settings.TRUSTED_PROXIES = []


def test_domain_error_classes() -> None:
    # Instantiate each domain error to verify properties
    errs = [
        InvitationInvalidError(),
        TokenInvalid400Error(),
        InvalidCredentialsError(),
        TokenInvalidError(),
        TokenExpiredError(),
        PermissionDeniedError(),
        PrivilegeEscalationError(),
        EmailNotVerifiedError(),
        OrganizationInactiveError(),
        NotFoundError(),
        SlugTakenError(),
        RoleNameTakenError(),
        AlreadyMemberError(),
        LastOwnerError(),
        SystemRoleImmutableError(),
        RoleInUseError(),
        ValidationError(),
        RateLimitedError(),
        ServiceUnavailableError(),
    ]
    for err in errs:
        assert isinstance(err, DomainError)
        assert err.code is not None
        assert err.http_status in {400, 401, 403, 404, 409, 422, 429, 503}


def test_verify_dummy_password() -> None:
    verify_dummy_password("some_password")


def test_setup_logging() -> None:
    setup_logging("DEBUG")
