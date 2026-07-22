"""SessionContext 持久化（study-web/runtime/session.json），与 docx 学习状态分离。"""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.models import SessionContext
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
            return SessionContext()

    def save(self, session: SessionContext) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")
