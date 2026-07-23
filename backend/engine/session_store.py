"""SessionContext 持久化（study-web/runtime/session.json），与 docx 学习状态分离。

并发（架构审计修复 R4/R2）：两级锁——
- 短锁 `_lock_for`（RLock）：load/save 单次调用的原子性（防共享 tmp 互踩
  写坏文件；同一调用必在同一线程完成）。
- 流程锁 `locked()`（threading.Lock，**非线程绑定**）：chat/command 流全程、
  /api/session/mode、/api/session/reset 的 load→改→save 互斥。SSE 同步
  生成器在 anyio 线程池会跨线程执行 next()（DevLog M2 已踩 ContextVar 同款），
  RLock 跨线程 release 会炸——threading.Lock 允许异线程 release，
  客户端断连时生成器 close 也能在任意线程安全释放锁。
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path

from ..domain.models import SessionContext
from ..services.backup_service import atomic_write
from ..services.config_service import WEB_ROOT

RUNTIME_DIR = WEB_ROOT / "runtime"
SESSION_PATH = RUNTIME_DIR / "session.json"

_RLOCKS: dict[str, threading.RLock] = {}
_FLOW_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _RLOCKS.setdefault(key, threading.RLock())


def _flow_lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _FLOW_LOCKS.setdefault(key, threading.Lock())


class SessionStore:
    def __init__(self, path: Path = SESSION_PATH):
        self._path = path

    @contextmanager
    def locked(self):
        """流程级互斥（load→改→save 全程）。threading.Lock 非线程绑定，
        跨线程释放安全（SSE 生成器跨线程/断连 close 场景）。
        """
        lock = _flow_lock_for(self._path)
        lock.acquire()
        try:
            yield self
        finally:
            lock.release()

    def load(self) -> SessionContext:
        with _lock_for(self._path):
            return self._load_unlocked()

    def _load_unlocked(self) -> SessionContext:
        if not self._path.exists():
            return SessionContext()
        try:
            return SessionContext.from_dict(
                json.loads(self._path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            # 损坏文件先备份再重置，避免无声丢历史
            import shutil
            shutil.copy2(self._path, self._path.with_suffix(".corrupt.bak"))
            return SessionContext()

    def save(self, session: SessionContext) -> None:
        with _lock_for(self._path):
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self._path,
                         json.dumps(session.to_dict(),
                                    ensure_ascii=False, indent=2))
