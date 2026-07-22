"""工作区值对象：一个学习工作区的全部派生值的唯一来源。

新增工作区字段只需在此与 settings.toml 增加键，各 Store/Engine 无需改动。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    slug: str                # 标识/目录名（workspaces/<slug>/）
    title: str               # 品牌名（前端标题、prompt 角色行）
    goal: str                # 学习目标描述（prompt 用）
    docx_dir: Path           # 学习数据目录（StudyState.json 等所在）
    project_dir: Path        # 目标项目目录（仓库校验/扫描用）
    session_path: Path       # 聊天会话文件
    total_days: int = 25     # 学习计划总天数
    replica_name: str = "replica"  # 复现项目名（编码目标/StudyMemory 小节前缀）
    preset: str = ""         # 学习模式预设（resources/presets/<name>.toml），空=全局 stages

    @classmethod
    def from_dict(cls, data: dict, web_root: Path) -> "Workspace":
        def _path(key: str, default: str) -> Path:
            raw = str(data.get(key) or default)
            p = Path(raw)
            return p if p.is_absolute() else (web_root / raw).resolve()

        slug = data["slug"]
        return cls(
            slug=slug,
            title=data.get("title") or slug,
            goal=data.get("goal") or "",
            docx_dir=_path("docx_dir", f"workspaces/{slug}/docx"),
            project_dir=_path("project_dir", "."),
            session_path=_path("session_path", f"workspaces/{slug}/session.json"),
            total_days=int(data.get("total_days", 25)),
            replica_name=data.get("replica_name") or "replica",
            preset=data.get("preset") or "",
        )
