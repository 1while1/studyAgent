"""访问密码门（M2 / M3.2）：单用户密码 + 签名 session token + 登录限速。

- 密码验证策略委托给 AuthProvider（默认 LocalAuthProvider，bcrypt 哈希
  存 `.env` 的 `AUTH_PASSWORD_HASH`，未设置 = 门关闭，开放模式）。
- token = ``{expiry_ts}.{hmac_sha256_hex(secret, ts)}``；签名密钥
  `runtime/auth_secret` 首次生成（gitignored）；有效期 `auth_session_days`（默认 7）
- 限速：每 IP 滑窗 `auth_login_max_attempts`（默认 10）次失败 /
  `auth_login_window_s`（默认 300s）锁定
- 多用户预留：中间件"解析 token → 注入 request.state.user"，v1 固定 "local"
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path

from .auth_provider import AuthProvider, LocalAuthProvider
from .config_service import ConfigService, ENV_PATH, runtime_dir

AUTH_COOKIE = "study_auth"


class AuthService:
    def __init__(self, config: ConfigService, env_path: Path | None = None,
                 provider: AuthProvider | None = None):
        self._config = config
        self._env_path = env_path or ENV_PATH  # 测试可注入临时 .env
        self._secret_path = runtime_dir(config) / "auth_secret"
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        # M3.2：密码验证委托给 provider（默认 LocalAuthProvider）
        self._provider = provider or LocalAuthProvider(config, self._env_path)

    # ---- 密码（委托给 AuthProvider） ----

    def enabled(self) -> bool:
        return self._provider.enabled()

    def verify_password(self, password: str) -> bool:
        return self._provider.verify_password(password)

    def set_password(self, password: str) -> None:
        self._provider.set_password(password)

    def clear_password(self) -> None:
        self._provider.clear_password()

    # ---- session token ----

    def _secret(self) -> bytes:
        # 尝试读取已有文件
        try:
            existing = self._secret_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing.encode()
        except Exception:
            pass

        # 生成新密钥并写入
        secret = secrets.token_hex(32)
        try:
            self._secret_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._secret_path.with_suffix(".tmp")
            tmp.write_text(secret, encoding="utf-8")
            tmp.replace(self._secret_path)
            return secret.encode()
        except Exception as e:
            raise RuntimeError(
                f"auth_secret 不可用且无法写入新密钥: {e}"
            ) from e

    def make_token(self) -> str:
        days = float(self._config.get("auth_session_days", 7))
        exp = str(int(time.time() + days * 86400))
        sig = hmac.new(self._secret(), exp.encode(),
                       hashlib.sha256).hexdigest()
        return f"{exp}.{sig}"

    def verify_token(self, token: str) -> bool:
        if not token or "." not in token:
            return False
        exp, _, sig = token.partition(".")
        expect = hmac.new(self._secret(), exp.encode(),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return False
        try:
            return int(exp) > time.time()
        except ValueError:
            return False

    # ---- 限速（内存滑窗） ----

    def rate_limited(self, ip: str) -> bool:
        window = int(self._config.get("auth_login_window_s", 300))
        max_attempts = int(self._config.get("auth_login_max_attempts", 10))
        now = time.time()
        with self._lock:
            fails = [t for t in self._fails.get(ip, []) if now - t < window]
            self._fails[ip] = fails
            return len(fails) >= max_attempts

    def record_fail(self, ip: str) -> None:
        with self._lock:
            self._fails.setdefault(ip, []).append(time.time())

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


_AUTH: dict[str, AuthService] = {}


def get_auth(config: ConfigService) -> AuthService:
    key = str(config.path)
    if key not in _AUTH:
        _AUTH[key] = AuthService(config)
    return _AUTH[key]
