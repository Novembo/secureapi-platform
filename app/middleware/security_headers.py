from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Standard secure headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"

        # HSTS (outside of dev environment)
        if settings.ENVIRONMENT != "dev":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Cache-Control: no-store on /auth/*
        if request.url.path.startswith("/api/v1/auth") or request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"

        return response
