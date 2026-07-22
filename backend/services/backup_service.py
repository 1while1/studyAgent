"""规则 14 落盘编排：备份 → 写入 → 校验 → 失败回滚。

validator 由上层（engine hooks）注入，services 层不反向依赖 engine。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .config_service import ConfigService


class PersistError(Exception):
    """校验失败且已回滚时抛出，携带校验输出。"""


class BackupService:
    def __init__(self, config: ConfigService):
        self.backup_dir: Path = config.docx_dir / "hooks" / "backup"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _backup_path(self, target: Path) -> Path:
        return self.backup_dir / (target.name + ".bak")

    def backup(self, *targets: Path) -> None:
        for t in targets:
            if t.exists():
                shutil.copy2(t, self._backup_path(t))

    def restore(self, *targets: Path) -> None:
        for t in targets:
            bak = self._backup_path(t)
            if bak.exists():
                shutil.copy2(bak, t)

    def atomic_persist(
        self,
        files: dict[Path, str],
        validator: Callable[[], tuple[bool, str]] | None = None,
    ) -> None:
        """备份 → 写入 → 校验 → 失败回滚。

        files: {目标路径: 新文本内容}
        validator: 返回 (是否通过, 输出信息)；None 表示跳过校验。
        校验失败时恢复全部文件并抛 PersistError。
        """
        targets = list(files.keys())
        self.backup(*targets)
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        if validator is not None:
            ok, output = validator()
            if not ok:
                self.restore(*targets)
                raise PersistError(output)
