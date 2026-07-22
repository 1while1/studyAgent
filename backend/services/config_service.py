"""settings.toml 加载与热重载。

单一职责：把 config/settings.toml + .env 暴露为只读配置对象。
其余模块一律通过 ConfigService 取配置，禁止直接读文件。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

# study-web 根目录（本文件位于 backend/services/ 下）
WEB_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = WEB_ROOT / "config" / "settings.toml"
ENV_PATH = WEB_ROOT / ".env"

# 内置资源（行为单源）：SOP 卡 / 校验脚本 / 初始化模板 / 生成提示词
RESOURCES_DIR = WEB_ROOT / "resources"
SOP_DIR = RESOURCES_DIR / "sop"
HOOKS_DIR = RESOURCES_DIR / "hooks"
TEMPLATES_DIR = RESOURCES_DIR / "templates"
PROMPTS_DIR = RESOURCES_DIR / "prompts"
PRESETS_DIR = RESOURCES_DIR / "presets"


def _load_env_file(path: Path) -> None:
    """轻量 .env 加载（不依赖 python-dotenv）：仅填充未存在的环境变量。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


class ConfigService:
    def __init__(self, settings_path: Path = SETTINGS_PATH):
        self._path = settings_path
        self._mtime: float = 0.0
        self._data: dict = {}
        self.reload()

    def reload(self) -> None:
        with open(self._path, "rb") as f:
            self._data = tomllib.load(f)
        self._mtime = self._path.stat().st_mtime

    def reload_if_changed(self) -> bool:
        """热重载：mtime 变化才重新解析。返回是否发生了重载。"""
        mtime = self._path.stat().st_mtime
        if mtime != self._mtime:
            self.reload()
            return True
        return False

    # ---- 基础取值 ----

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    @property
    def data(self) -> dict:
        return self._data

    # ---- 工作区 ----

    def workspaces(self) -> list:
        from ..domain.workspace import Workspace
        raw = self._data.get("workspaces") or []
        if raw:
            return [Workspace.from_dict(w, WEB_ROOT) for w in raw]
        # 旧配置兼容：由顶层键合成默认工作区
        return [Workspace.from_dict({
            "slug": "default",
            "title": self._data.get("app_title", "学习助手"),
            "goal": self._data.get("app_goal", ""),
            "docx_dir": self._data.get("docx_dir", "workspaces/default/docx"),
            "project_dir": self._data.get("project_dir", "."),
            "session_path": "runtime/session.json",
            "total_days": self._data.get("total_days", 25),
            "replica_name": self._data.get("replica_name", "replica"),
        }, WEB_ROOT)]

    @property
    def workspace(self):
        """当前激活工作区。"""
        slug = self._data.get("active_workspace")
        all_ws = self.workspaces()
        if slug:
            for w in all_ws:
                if w.slug == slug:
                    return w
        return all_ws[0]

    # ---- 常用类型化访问 ----

    @property
    def docx_dir(self) -> Path:
        return self.workspace.docx_dir

    @property
    def stages(self) -> list[dict]:
        """当前工作区的阶段机定义。

        工作区配了 preset（resources/presets/<name>.toml）时用预设的
        [[stages]]，文件缺失/解析失败回退全局 settings.toml。
        """
        preset = getattr(self.workspace, "preset", "")
        if preset:
            path = PRESETS_DIR / f"{preset}.toml"
            if path.is_file():
                try:
                    import tomllib
                    with open(path, "rb") as f:
                        stages = tomllib.load(f).get("stages", [])
                    if stages:
                        return stages
                except Exception:
                    pass
        return self._data.get("stages", [])

    def stage_names(self) -> list[str]:
        return [s["name"] for s in self.stages]

    def stage(self, name: str) -> dict | None:
        for s in self.stages:
            if s["name"] == name:
                return s
        return None

    @property
    def commands(self) -> dict[str, dict]:
        return self._data.get("commands", {})

    @property
    def code_roots(self) -> list[dict]:
        """代码浏览器项目根（[[code_roots]] 持久化配置），按当前工作区过滤。

        无 workspace 字段的根归第一个工作区（旧配置兼容）。
        """
        all_ws = self.workspaces()
        default_slug = all_ws[0].slug
        active = self.workspace.slug
        return [r for r in self._data.get("code_roots", [])
                if r.get("workspace", default_slug) == active]

    @property
    def llm_config(self) -> dict:
        return self._data.get("llm", {})

    def env(self, key: str, default: str = "") -> str:
        return os.environ.get(key, default)


_config: ConfigService | None = None


def get_config() -> ConfigService:
    """进程级单例。测试可通过重置全局实例注入临时配置。"""
    global _config
    if _config is None:
        _load_env_file(ENV_PATH)
        _config = ConfigService()
    else:
        _config.reload_if_changed()
    return _config


def reset_config() -> None:
    global _config
    _config = None
