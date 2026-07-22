"""工作区编排：列表 / 创建 / 切换 / 删除 / 导出 / 重新扫描。

只做编排——扫描委托 repo_scanner，文档生成委托 doc_initializer，
settings 持久化委托 config_writer。
"""

from __future__ import annotations

import re
import shutil

from ..domain.workspace import Workspace
from .config_service import WEB_ROOT, ConfigService
from .config_writer import update_code_roots, update_workspaces
from .doc_initializer import DEFAULT_INIT_MAX_TOKENS, DocInitializer
from .repo_scanner import scan

SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class WorkspaceError(Exception):
    pass


class WorkspaceService:
    def __init__(self, config: ConfigService, llm=None):
        self._config = config
        self._llm = llm

    # ---- 查询 ----

    def list(self) -> dict:
        active = self._config.workspace.slug
        return {
            "active": active,
            "workspaces": [
                {"slug": w.slug, "title": w.title, "goal": w.goal,
                 "project_dir": str(w.project_dir), "total_days": w.total_days,
                 "active": w.slug == active}
                for w in self._config.workspaces()
            ],
        }

    def _settings_workspaces(self) -> list[dict]:
        return [dict(w) for w in self._config.data.get("workspaces", [])]

    # ---- 创建（扫描 → LLM 生成 → 验证 → 注册 → 切换） ----

    def create(self, spec: dict) -> Workspace:
        if self._llm is None:
            raise WorkspaceError("LLM 未配置，无法生成初始化文档")
        slug = (spec.get("slug") or "").strip()
        if not slug or not SLUG_RE.match(slug):
            raise WorkspaceError("工作区标识只能包含字母、数字、-、_")
        if any(w.slug == slug for w in self._config.workspaces()):
            raise WorkspaceError(f"工作区已存在: {slug}")

        ws = Workspace.from_dict({
            "slug": slug,
            "title": spec.get("title") or slug,
            "goal": spec.get("goal") or "",
            "docx_dir": f"workspaces/{slug}/docx",
            "project_dir": spec["project_dir"],
            "session_path": f"workspaces/{slug}/session.json",
            "total_days": int(spec.get("total_days", 25)),
            "replica_name": spec.get("replica_name") or f"{slug}-replica",
            "preset": spec.get("preset") or "",
        }, WEB_ROOT)
        if not ws.project_dir.is_dir():
            raise WorkspaceError(f"项目目录不存在: {ws.project_dir}")

        profile = scan(ws.project_dir)
        self._initializer().initialize(ws, profile)

        # 注册：workspaces 条目 + 目标项目登记为该工作区 code_root + 设为激活
        all_ws = self._settings_workspaces()
        all_ws.append({
            "slug": ws.slug, "title": ws.title, "goal": ws.goal,
            "docx_dir": f"workspaces/{slug}/docx",
            "project_dir": spec["project_dir"],
            "session_path": f"workspaces/{slug}/session.json",
            "total_days": ws.total_days, "replica_name": ws.replica_name,
            **({"preset": ws.preset} if ws.preset else {}),
        })
        update_workspaces(self._config.path, all_ws, active=slug)
        roots = [dict(r) for r in self._config.data.get("code_roots", [])]
        roots.append({"name": ws.project_dir.name or slug,
                      "path": spec["project_dir"], "workspace": slug})
        update_code_roots(self._config.path, roots)
        self._config.reload()
        return ws

    # ---- 切换 ----

    def switch(self, slug: str) -> Workspace:
        if not any(w.slug == slug for w in self._config.workspaces()):
            raise WorkspaceError(f"工作区不存在: {slug}")
        update_workspaces(self._config.path, self._settings_workspaces(), active=slug)
        self._config.reload()
        return self._config.workspace

    # ---- 删除 / 导出 ----

    def delete(self, slug: str, delete_data: bool = False) -> None:
        if slug == self._config.workspace.slug:
            raise WorkspaceError("不能删除当前激活的工作区，请先切换到其他工作区")
        all_ws = self._settings_workspaces()
        target = next((w for w in all_ws if w.get("slug") == slug), None)
        if not target:
            raise WorkspaceError(f"工作区不存在: {slug}")
        if delete_data:
            # 只允许删除 study-web/workspaces/<slug> 目录本身，外部 docx_dir 永不删
            ws = Workspace.from_dict(target, WEB_ROOT)
            safe_root = (WEB_ROOT / "workspaces").resolve()
            target_dir = ws.docx_dir.parent.resolve()
            if (target_dir != safe_root
                    and safe_root in target_dir.parents
                    and target_dir.name == slug):
                shutil.rmtree(target_dir)
            else:
                raise WorkspaceError(
                    f"学习数据目录 {target_dir} 不在 study-web/workspaces/{slug} 下，"
                    "为防误删已中止（数据未动，工作区条目仍可删除）")
        update_workspaces(self._config.path,
                          [w for w in all_ws if w.get("slug") != slug],
                          active=self._config.workspace.slug)
        roots = [dict(r) for r in self._config.data.get("code_roots", [])
                 if r.get("workspace") != slug]
        update_code_roots(self._config.path, roots)
        self._config.reload()

    def export_zip(self, slug: str) -> bytes:
        import io
        import zipfile
        ws = next((w for w in self._config.workspaces() if w.slug == slug), None)
        if not ws:
            raise WorkspaceError(f"工作区不存在: {slug}")
        if not ws.docx_dir.is_dir():
            raise WorkspaceError(f"学习数据目录不存在: {ws.docx_dir}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(ws.docx_dir.rglob("*")):
                if f.is_file() and "backup" not in f.parts:
                    zf.write(f, f.relative_to(ws.docx_dir))
        return buf.getvalue()

    # ---- 手动刷新 Project.md ----

    def rescan(self) -> None:
        ws = self._config.workspace
        if not ws.project_dir.is_dir():
            raise WorkspaceError(f"项目目录不存在: {ws.project_dir}")
        self._initializer().refresh_project_md(ws, scan(ws.project_dir))

    def _initializer(self) -> DocInitializer:
        if self._llm is None:
            raise WorkspaceError("LLM 未配置，无法生成文档")
        return DocInitializer(
            self._llm,
            max_tokens=self._config.get("init_max_tokens",
                                        DEFAULT_INIT_MAX_TOKENS),
            detail_days=int(self._config.get("init_detail_days", 3)))
