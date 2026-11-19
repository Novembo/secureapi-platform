from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.v1 import api_v1_router
from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import get_correlation_id, logger, setup_logging
from app.core.rate_limit import limiter
from app.db.session import check_database_health
from app.middleware.body_limit import BodyLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info("Starting SecureAPI Platform", extra={"environment": settings.ENVIRONMENT})
    yield
    logger.info("Shutting down SecureAPI Platform")


app = FastAPI(
    title="SecureAPI Platform",
    description="Multi-tenant RBAC platform API with immutable audit logs",
    version="1.0.0",
    docs_url="/docs" if settings.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Attach rate limiter state
app.state.limiter = limiter

# Middlewares
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials="*" not in settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Exception Handlers
@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    content: dict[str, Any] = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": get_correlation_id(),
            "details": exc.details,
        }
    }
    return JSONResponse(
        status_code=exc.http_status,
        content=content,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Sanitize validation details (remove sensitive input values like passwords)
    sanitized_errors = []
    for err in exc.errors():
        field_loc = [str(loc) for loc in err.get("loc", []) if str(loc) != "body"]
        sanitized_errors.append(
            {
                "field": ".".join(field_loc) if field_loc else "body",
                "message": err.get("msg", "Valeur invalide"),
                "type": err.get("type", "validation_error"),
            }
        )

    content = {
        "error": {
            "code": "validation_error",
            "message": "Erreur de validation des données fournies.",
            "request_id": get_correlation_id(),
            "details": sanitized_errors,
        }
    }
    return JSONResponse(status_code=422, content=content)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = getattr(exc, "retry_after", 60)
    content = {
        "error": {
            "code": "rate_limited",
            "message": "Trop de requêtes. Veuillez patienter avant de réessayer.",
            "request_id": get_correlation_id(),
            "details": None,
        }
    }
    return JSONResponse(
        status_code=429,
        content=content,
        headers={"Retry-After": str(retry_after)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server exception: %s", str(exc))
    content = {
        "error": {
            "code": "internal_error",
            "message": "Une erreur interne est survenue.",
            "request_id": get_correlation_id(),
            "details": None,
        }
    }
    return JSONResponse(status_code=500, content=content)


# System Endpoints (SYS-01 & SYS-02)
@app.get("/health", tags=["system"], summary="Liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"], summary="Readiness probe")
def ready() -> JSONResponse:
    if not check_database_health():
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "service_unavailable",
                    "message": "La base de données est injoignable.",
                    "request_id": get_correlation_id(),
                    "details": None,
                }
            },
        )
    return JSONResponse(status_code=200, content={"status": "ready"})


# API routers
app.include_router(api_v1_router)
