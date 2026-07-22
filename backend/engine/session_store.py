"""SessionContext 持久化（study-web/runtime/session.json），与 docx 学习状态分离。"""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.models import SessionContext
from ..services.backup_service import atomic_write
from ..services.config_service import WEB_ROOT

RUNTIME_DIR = WEB_ROOT / "runtime"
SESSION_PATH = RUNTIME_DIR / "session.json"


class SessionStore:
    def __init__(self, path: Path = SESSION_PATH):
        self._path = path

    def load(self) -> SessionContext:
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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path,
                     json.dumps(session.to_dict(), ensure_ascii=False, indent=2))
