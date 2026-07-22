"""HTTP 中间件：访问密码门（从 app.py 抽出为工厂，便于单测）。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from ..services.auth_service import AUTH_COOKIE, get_auth
from ..services.config_service import ConfigService

_EXEMPT = {"/api/auth/status", "/api/auth/setup", "/api/auth/login"}


def make_auth_gate(config: ConfigService):
    """门开时 /api/*（除登录类端点）无有效 cookie 一律 401。

    多用户预留注入点：解析 token → request.state.user（v1 固定单用户）。
    """

    async def auth_gate(request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in _EXEMPT:
            auth = get_auth(config)
            if auth.enabled() and not auth.verify_token(
                    request.cookies.get(AUTH_COOKIE, "")):
                return JSONResponse({"detail": "未登录或会话已过期"},
                                    status_code=401)
            request.state.user = "local"
        return await call_next(request)

    return auth_gate
