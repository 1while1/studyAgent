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
PEDAGOGY_DIR = RESOURCES_DIR / "pedagogy"


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
        self._local_path = settings_path.parent / "settings.local.toml"
        self._mtime: float = 0.0
        self._local_mtime: float = 0.0
        self._data: dict = {}
        self.reload()
        self._last_bad_mtime: float = 0.0

    @property
    def path(self) -> Path:
        """本实例的配置文件路径（测试可注入临时 settings）。"""
        return self._path

    def reload(self) -> None:
        with open(self._path, "rb") as f:
            self._data = tomllib.load(f)
        self._mtime = self._path.stat().st_mtime
        # M3.4: 加载 settings.local.toml 并深度合并
        if self._local_path.exists():
            with open(self._local_path, "rb") as f:
                local_data = tomllib.load(f)
            self._data = self._deep_merge(self._data, local_data)
            self._local_mtime = self._local_path.stat().st_mtime

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并配置：标量/列表覆盖，字典递归合并。"""
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigService._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def reload_if_changed(self) -> bool:
        """热重载：mtime 变化才重新解析。返回是否发生了重载。"""
        try:
            mtime = self._path.stat().st_mtime
            local_mtime = (self._local_path.stat().st_mtime
                           if self._local_path.exists() else 0.0)
        except OSError:
            return False
        if mtime != self._mtime or local_mtime != self._local_mtime:
            try:
                self.reload()
                self._last_bad_mtime = 0.0
                return True
            except (OSError, tomllib.TOMLDecodeError) as e:
                if mtime != self._last_bad_mtime:
                    self._last_bad_mtime = mtime
                    import sys
                    print(f"[config] settings.toml 热重载失败: {e}",
                          file=sys.stderr)
                return False
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

    # ---- 代码根操作 ----

    def add_code_root(self, name: str, raw_path: str) -> dict:
        """添加代码根：校验 → 查重 → 路径验证 → 写盘 → 重载。

        返回 {"ok": True/False, ...} 响应体。
        """
        import re
        from pathlib import Path as _P
        from .config_writer import update_code_roots

        if not name or not raw_path:
            return {"ok": False, "error": "name 和 path 不能为空"}
        # C3：名称白名单（XSS 防线）
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            return {"ok": False,
                    "error": "项目根名称仅限字母/数字/_/-（≤40 字符）"}
        # 查重
        all_roots = list(self._data.get("code_roots", []))
        if any(r["name"] == name for r in all_roots
               if r.get("workspace", self.workspaces()[0].slug) == self.workspace.slug):
            return {"ok": False, "error": f"项目根已存在: {name}"}
        # 路径验证
        p = _P(raw_path) if _P(raw_path).is_absolute() else (WEB_ROOT / raw_path).resolve()
        if not p.is_dir():
            return {"ok": False, "error": f"目录不存在: {raw_path}"}
        # 写盘
        new_roots = all_roots + [{"name": name, "path": raw_path,
                                  "workspace": self.workspace.slug}]
        try:
            update_code_roots(self.path, new_roots)
            self.reload()
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
        return {"ok": True}

    def delete_code_root(self, name: str) -> dict:
        """删除代码根：过滤 → 写盘 → 重载。返回响应体。"""
        from .config_writer import update_code_roots

        all_roots = list(self._data.get("code_roots", []))
        slug = self.workspace.slug
        new_roots = [r for r in all_roots
                     if not (r["name"] == name and r.get("workspace", slug) == slug)]
        if len(new_roots) == len(all_roots):
            return {"ok": False, "error": f"项目根不存在: {name}"}
        try:
            update_code_roots(self.path, new_roots)
            self.reload()
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
        return {"ok": True}


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


def runtime_dir(config: ConfigService) -> Path:
    """运行时目录（agent.log/auth_secret 等可 gitignore 产物）。

    settings 在 config/ 下时取其上级（study-web/config/settings.toml →
    study-web/runtime）；测试临时 settings（直接放 tmp 根）→ tmp/runtime 隔离。
    """
    base = (config.path.parent.parent
            if config.path.parent.name == "config"
            else config.path.parent)
    return (base / "runtime").resolve()


def reset_config() -> None:
    global _config
    _config = None
