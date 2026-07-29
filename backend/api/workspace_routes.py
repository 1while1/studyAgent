"""工作区 + 会话 + 配置路由：/api/workspaces/* /api/session/* /api/config/*。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.doc_initializer import InitError
from ..services.repo_scanner import scan as repo_scan
from ..services.workspace_service import WorkspaceError, WorkspaceService

workspace_router = APIRouter(tags=["工作区", "会话"])


def _deps():
    from . import routes
    return routes._deps


def _rebind():
    from . import routes
    return routes._rebind


class WorkspaceCreateIn(BaseModel):
    slug: str
    project_dir: str
    title: str = ""
    goal: str = ""
    total_days: int = 25
    replica_name: str = ""
    preset: str = ""


class WorkspaceSwitchIn(BaseModel):
    slug: str


class WorkspaceDeleteIn(BaseModel):
    slug: str
    delete_data: bool = False


# ---------- 工作区 ----------

@workspace_router.get("/api/workspaces")
def workspaces_list():
    return WorkspaceService(_deps().config).list()


@workspace_router.get("/api/workspaces/presets")
def workspaces_presets():
    """可选学习模式预设（resources/presets/*.toml）。"""
    import tomllib
    from ..services.config_service import PRESETS_DIR
    out = [{"name": "", "description": "标准（跟随全局 stages 配置）"}]
    for f in sorted(PRESETS_DIR.glob("*.toml")):
        try:
            desc = tomllib.load(open(f, "rb")).get("description", "")
        except Exception:
            desc = ""
        out.append({"name": f.stem, "description": desc or f.stem})
    return {"presets": out}


@workspace_router.get("/api/workspaces/scan-preview")
def workspaces_scan_preview(path: str):
    try:
        return {"ok": True, "profile": repo_scan(path)}
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}


@workspace_router.post("/api/workspaces/create")
def workspaces_create(body: WorkspaceCreateIn):
    deps = _deps()
    try:
        ws = WorkspaceService(deps.config, deps.llm).create(body.model_dump())
    except (WorkspaceError, InitError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    rb = _rebind()
    if rb:
        rb()
    return {"ok": True, "slug": ws.slug, "title": ws.title}


@workspace_router.post("/api/workspaces/switch")
def workspaces_switch(body: WorkspaceSwitchIn):
    deps = _deps()
    try:
        ws = WorkspaceService(deps.config).switch(body.slug)
    except WorkspaceError as e:
        return {"ok": False, "error": str(e)}
    rb = _rebind()
    if rb:
        rb()
    return {"ok": True, "slug": ws.slug, "title": ws.title}


@workspace_router.post("/api/workspaces/delete")
def workspaces_delete(body: WorkspaceDeleteIn):
    try:
        WorkspaceService(_deps().config).delete(body.slug, body.delete_data)
    except WorkspaceError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@workspace_router.get("/api/workspaces/export")
def workspaces_export(slug: str):
    from fastapi.responses import Response
    try:
        data = WorkspaceService(_deps().config).export_zip(slug)
    except WorkspaceError as e:
        return {"ok": False, "error": str(e)}
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{slug}-docx.zip"'})


@workspace_router.post("/api/workspaces/rescan")
def workspaces_rescan():
    deps = _deps()
    try:
        WorkspaceService(deps.config, deps.llm).rescan()
    except (WorkspaceError, InitError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@workspace_router.post("/api/config/reload")
def reload_config():
    deps = _deps()
    changed = deps.config.reload()
    deps.templates.reload()
    return {"reloaded": True, "changed": changed}


# ---------- 会话 ----------

@workspace_router.post("/api/session/reset")
def reset_session():
    """清空对话历史（不影响 docx 学习数据）。用于清除上下文污染。"""
    deps = _deps()
    with deps.session_store.locked():
        session = deps.session_store.load()
        n = len(session.chat_history)
        session.chat_history = []
        session.archive_summary = ""
        session.archive_upto = 0
        session.compress_cooldown = 0
        deps.session_store.save(session)
    return {"cleared": n}


# ---------- 会话模式（M6：study/code 双轴之 agent 状态轴） ----------

_SESSION_MODES = ("study", "code")


@workspace_router.get("/api/session/mode")
def get_session_mode():
    """当前会话模式（前端加载时同步模式按钮态与默认布局）。"""
    session = _deps().session_store.load()
    return {"ok": True, "mode": getattr(session, "mode", "study")}


@workspace_router.post("/api/session/mode")
def set_session_mode(body: dict):
    """切换会话模式：code → planner 引擎 + ACTION 工具武装；study → 导学引擎。"""
    deps = _deps()
    mode = ((body or {}).get("mode") or "").strip()
    if mode not in _SESSION_MODES:
        return {"ok": False,
                "error": f"非法模式: {mode or '（空）'}（枚举: {_SESSION_MODES}）"}
    note = ""
    with deps.session_store.locked():
        session = deps.session_store.load()
        session.mode = mode
        from ..domain.enums import DayPhase
        if session.day_phase in (DayPhase.INTERVIEW.value,
                                 DayPhase.PREREQ.value,
                                 DayPhase.REVIEWING.value):
            session.interview_cid = ""
            session.interview_round = 0
            session.interview_score = None
            session.prereq_targets = []
            session.prereq_retry = 0
            session.day_phase = DayPhase.STUDYING.value
            note = "（进行中的面试/诊断/复盘已中断）"
        deps.session_store.save(session)
    return {"ok": True, "mode": mode, "note": note}
