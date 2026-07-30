"""安全响应头中间件（M3.3 安全加固）

通过配置项 security_headers_enabled 控制开关（默认开启）。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'strict-dynamic'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self';",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件。enabled=False 时空转（不注入任何头）。"""

    def __init__(self, app, enabled: bool = True):  # noqa: ANN001
        super().__init__(app)
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if self._enabled:
            for header, value in SECURITY_HEADERS.items():
                response.headers[header] = value
        return response
