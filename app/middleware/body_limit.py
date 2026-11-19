from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import get_correlation_id


class BodyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > settings.MAX_BODY_BYTES:
                    msg = (
                        f"Taille du corps supérieure à la limite autorisée "
                        f"({settings.MAX_BODY_BYTES} octets)."
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "payload_too_large",
                                "message": msg,
                                "request_id": get_correlation_id(),
                                "details": None,
                            }
                        },
                    )
            except ValueError:
                pass

        return await call_next(request)
