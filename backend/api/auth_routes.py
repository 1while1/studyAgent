"""认证路由：/api/auth/*。"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..services.auth_service import AUTH_COOKIE, get_auth

auth_router = APIRouter(tags=["认证"])


def _deps():
    from . import routes
    return routes._deps


def _set_auth_cookie(auth, response: Response) -> None:
    cfg = _deps().config
    days = float(cfg.get("auth_session_days", 7))
    secure = bool(cfg.get("auth_cookie_secure", False))
    response.set_cookie(AUTH_COOKIE, auth.make_token(),
                        max_age=int(days * 86400),
                        httponly=True, samesite="lax", secure=secure)


@auth_router.get("/api/auth/status")
def auth_status(request: Request):
    auth = get_auth(_deps().config)
    return {"gate": auth.enabled(),
            "authed": auth.enabled() and auth.verify_token(
                request.cookies.get(AUTH_COOKIE, ""))}


class _PasswordIn(BaseModel):
    password: str


@auth_router.post("/api/auth/setup")
def auth_setup(body: _PasswordIn, response: Response):
    auth = get_auth(_deps().config)
    if auth.enabled():
        return {"ok": False, "error": "密码已设置，请直接登录"}
    pw = body.password.strip()
    if len(pw) < 6:
        return {"ok": False, "error": "密码至少 6 位"}
    auth.set_password(pw)
    _set_auth_cookie(auth, response)
    return {"ok": True}


@auth_router.post("/api/auth/login")
def auth_login(body: _PasswordIn, request: Request, response: Response):
    auth = get_auth(_deps().config)
    ip = request.client.host if request.client else "unknown"
    if auth.rate_limited(ip):
        return {"ok": False, "error": "尝试次数过多，请稍后再试"}
    if not auth.enabled():
        return {"ok": True, "gate": False}
    if not auth.verify_password(body.password):
        auth.record_fail(ip)
        return {"ok": False, "error": "密码错误"}
    auth.record_success(ip)
    _set_auth_cookie(auth, response)
    return {"ok": True}


@auth_router.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(AUTH_COOKIE)
    return {"ok": True}


@auth_router.delete("/api/auth/password")
def auth_clear():
    """删除密码（还原为开放模式）。中间件已保证门开时此请求已认证。"""
    auth = get_auth(_deps().config)
    if not auth.enabled():
        return {"ok": False, "error": "未设置密码"}
    auth.clear_password()
    return {"ok": True}
