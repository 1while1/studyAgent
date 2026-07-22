"""访问密码门（M2）：单用户密码 + 签名 session token + 登录限速。

- 密码 bcrypt 哈希存 `.env` 的 `AUTH_PASSWORD_HASH`（未设置 = 门关闭，
  开放模式，本地开发友好）。设计原文"哈希存 settings（不入库不入 git）"，
  但 settings.toml 是本仓 git 跟踪文件，.env 才符合"不入 git"意图与
  密钥边界铁律——有意偏离，已记录 DevLog。
- token = ``{expiry_ts}.{hmac_sha256_hex(secret, ts)}``；签名密钥
  `runtime/auth_secret` 首次生成（gitignored）；有效期 `auth_session_days`（默认 7）
- 限速：每 IP 滑窗 `auth_login_max_attempts`（默认 10）次失败 /
  `auth_login_window_s`（默认 300s）锁定
- 多用户预留：中间件"解析 token → 注入 request.state.user"，v1 固定 "local"
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

from .backup_service import atomic_write
from .config_service import ConfigService, ENV_PATH, runtime_dir
from .config_writer import update_env_file

AUTH_COOKIE = "study_auth"
_KEY = "AUTH_PASSWORD_HASH"


class AuthService:
    def __init__(self, config: ConfigService, env_path: Path | None = None):
        self._config = config
        self._env_path = env_path or ENV_PATH  # 测试可注入临时 .env
        self._secret_path = runtime_dir(config) / "auth_secret"
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    # ---- 密码 ----

    def enabled(self) -> bool:
        return bool(self._config.env(_KEY))

    def verify_password(self, password: str) -> bool:
        hashed = self._config.env(_KEY)
        if not hashed or not password:
            return False
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode("utf-8"),
                                  hashed.encode("utf-8"))
        except Exception:
            return False

    def set_password(self, password: str) -> None:
        import bcrypt
        hashed = bcrypt.hashpw(password.encode("utf-8"),
                               bcrypt.gensalt()).decode("utf-8")
        update_env_file(self._env_path, {_KEY: hashed})

    def clear_password(self) -> None:
        update_env_file(self._env_path, {_KEY: ""})
        os.environ.pop(_KEY, None)

    # ---- session token ----

    def _secret(self) -> bytes:
        try:
            return self._secret_path.read_text(encoding="utf-8").strip().encode()
        except Exception:
            pass
        secret = secrets.token_hex(32)
        try:
            self._secret_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self._secret_path, secret)
        except Exception:
            pass
        return secret.encode()

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
