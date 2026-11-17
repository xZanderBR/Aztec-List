"""
Rate limiter instance for the application.

This module provides a centralized rate limiter instance that can be imported
and used as a decorator in route handlers throughout the application.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.settings import settings

# Fly.io's edge proxy sets this to the real client address and overwrites any value the
# client sent, so it is safe to trust. Behind any proxy, the socket address is the proxy's,
# which would put every visitor in one shared rate-limit bucket.
_CLIENT_IP_HEADER = "fly-client-ip"


def client_ip(request: Request) -> str:
    """Rate-limit key: the real client IP behind Fly's proxy, else the socket address."""
    return request.headers.get(_CLIENT_IP_HEADER) or get_remote_address(request)


# Create a single limiter instance to be shared across the application
# The enabled flag can be toggled via RATE_LIMIT__ENABLED environment variable
limiter = Limiter(
    key_func=client_ip,
    default_limits=["1000/hour"],
    enabled=settings.rate_limit.enabled,
)
