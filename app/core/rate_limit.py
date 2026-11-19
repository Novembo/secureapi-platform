import ipaddress

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def get_real_client_ip(request: Request) -> str:
    """Extracts the client IP address.

    Only respects X-Forwarded-For if the direct peer IP is in TRUSTED_PROXIES.
    """
    direct_ip = get_remote_address(request) or "127.0.0.1"

    if not settings.TRUSTED_PROXIES:
        return direct_ip

    # Check if direct_ip is trusted
    try:
        direct_addr = ipaddress.ip_address(direct_ip)
        is_trusted = False
        for trusted in settings.TRUSTED_PROXIES:
            try:
                if "/" in trusted:
                    if direct_addr in ipaddress.ip_network(trusted, strict=False):
                        is_trusted = True
                        break
                elif direct_addr == ipaddress.ip_address(trusted):
                    is_trusted = True
                    break
            except ValueError:
                continue

        if not is_trusted:
            return direct_ip
    except ValueError:
        return direct_ip

    # Parse X-Forwarded-For: leftmost IP is the original client
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",")]
        if parts and parts[0]:
            return parts[0]

    return direct_ip


limiter = Limiter(
    key_func=get_real_client_ip,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
)
