"""认证提供者接口（M3.2 认证可插拔）

AuthProvider 抽象密码验证策略，支持本地密码门和未来 OIDC/OAuth。
Token 管理和限速逻辑保留在 AuthService 中（与 provider 无关）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class AuthProvider(ABC):
    """认证提供者接口——抽象密码验证策略。"""

    @abstractmethod
    def verify_password(self, password: str) -> bool:
        """验证密码"""
        ...

    @abstractmethod
    def set_password(self, password: str) -> None:
        """设置密码"""
        ...

    @abstractmethod
    def clear_password(self) -> None:
        """清除密码"""
        ...

    @abstractmethod
    def enabled(self) -> bool:
        """认证门是否开启"""
        ...


class LocalAuthProvider(AuthProvider):
    """本地 bcrypt 密码门（当前实现）。

    密码哈希通过 ConfigService.env() 读取（底层 .env + os.environ），
    写入走 update_env_file 原子更新。
    """

    _KEY = "AUTH_PASSWORD_HASH"

    def __init__(self, config, env_path: Path | None = None):
        self._config = config
        if env_path is not None:
            self._env_path = env_path
        else:
            from .config_service import ENV_PATH
            self._env_path = ENV_PATH
        if not self._env_path.exists():
            raise FileNotFoundError(
                f"环境变量文件不存在: {self._env_path}")

    def _hash(self) -> str:
        """从 config.env 获取当前哈希值。"""
        return self._config.env(self._KEY) or ""

    def verify_password(self, password: str) -> bool:
        hashed = self._hash()
        if not hashed or not password:
            return False
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode("utf-8"),
                                  hashed.encode("utf-8"))
        except Exception as e:
            from .observer import get_observer
            get_observer(self._config).log_tool(
                "auth_verify", False, repr(e)[:200])
            return False

    def set_password(self, password: str) -> None:
        import bcrypt
        hashed = bcrypt.hashpw(password.encode("utf-8"),
                               bcrypt.gensalt()).decode("utf-8")
        from .config_writer import update_env_file
        update_env_file(self._env_path, {self._KEY: hashed})

    def clear_password(self) -> None:
        import os
        from .config_writer import update_env_file
        update_env_file(self._env_path, {self._KEY: ""})
        os.environ.pop(self._KEY, None)

    def enabled(self) -> bool:
        return bool(self._hash())
