"""API 路由：/api/chat(SSE) /api/command(SSE) /api/state /api/commands /api/config/reload。"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..engine.commands.base import CommandHandler, Deps
from ..engine.orchestrator import ChatOrchestrator
from ..services.doc_initializer import InitError
from ..services.repo_scanner import scan as repo_scan
from ..services.workspace_service import WorkspaceError, WorkspaceService

router = APIRouter()

_deps: Deps | None = None
_orchestrator: ChatOrchestrator | None = None
_rebind = None  # 工作区切换后重建 deps 的回调（由 app 注入）


def init(deps: Deps, orchestrator: ChatOrchestrator) -> None:
    global _deps, _orchestrator
    _deps, _orchestrator = deps, orchestrator


def set_rebind(fn) -> None:
    global _rebind
    _rebind = fn


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class TextIn(BaseModel):
    text: str


class LLMStreamer:
    """流式调用 LLM 并累积完整文本。"""

    def __init__(self, deps: Deps):
        self._deps = deps
        self.full: list[str] = []

    @property
    def text(self) -> str:
        return "".join(self.full)

    def stream(self, session, instruction: str, sop_card: str = ""):
        card_text = (CommandHandler.read_sop_card(self._deps, sop_card)
                     if sop_card else "")
        system = self._deps.prompts.build(
            session, sop_card=card_text, extra_instruction=instruction)
        max_turns = self._deps.config.get("chat_history_max_turns", 20)
        history = session.chat_history[-max_turns * 2:]
        messages = [{"role": "system", "content": system}] + history
        from ..engine.tool_use import ToolUseLoop
        from ..services.code_browser import CodeBrowser
        loop = ToolUseLoop(self._deps.config, self._deps.llm,
                           CodeBrowser(self._deps.config))
        for ev in loop.run(messages):
            if ev["type"] == "delta":
                self.full.append(ev["content"])
            yield sse(ev)


@router.post("/api/chat")
def chat(body: TextIn):
    deps, orch = _deps, _orchestrator

    def gen():
        session = deps.session_store.load()
        text = body.text.strip()
        instruction = orch.instruction_for(session, text)
        session.chat_history.append({"role": "user", "content": text})
        streamer = LLMStreamer(deps)
        try:
            yield from streamer.stream(session, instruction)
        except Exception as e:
            yield sse({"type": "error", "content": f"LLM 调用失败：{e}"})
            return
        session.chat_history.append({"role": "assistant", "content": streamer.text})
        try:
            extras = orch.post_process(session, streamer.text)
        except Exception as e:
            yield sse({"type": "error", "content": f"后处理失败：{e}"})
            extras = []
        for extra in extras:
            yield sse({"type": "message", "content": extra})
        deps.session_store.save(session)
        yield sse({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/api/command")
def command(body: TextIn):
    deps = _deps

    def gen():
        from ..engine.commands.registry import CommandRegistry
        registry = CommandRegistry(deps.config)
        matched = registry.match(body.text)
        if not matched:
            yield sse({"type": "error", "content": f"未识别的指令：{body.text}"})
            return
        entry, args = matched
        handler = entry["handler"]
        session = deps.session_store.load()
        try:
            stop = handler.fail_fast(deps, session, args, entry["mode"])
        except Exception as e:
            yield sse({"type": "error", "content": f"FAIL-FAST 检查异常：{e}"})
            return
        if stop:
            yield sse({"type": "message", "content": stop})
            yield sse({"type": "done"})
            return
        try:
            result = handler.run(deps, session, args, entry["mode"])
        except Exception as e:
            yield sse({"type": "error", "content": f"指令执行失败：{e}"})
            return
        for msg in result.messages:
            yield sse({"type": "message", "content": msg})
        if result.llm_instruction:
            sop = result.sop_card if result.sop_card is not None else entry["sop_card"]
            streamer = LLMStreamer(deps)
            try:
                # 先记录用户指令，保持 user/assistant 成对，避免模型误读孤立 assistant 消息
                session.chat_history.append({"role": "user", "content": body.text})
                yield from streamer.stream(session, result.llm_instruction, sop)
            except Exception as e:
                yield sse({"type": "error", "content": f"LLM 调用失败：{e}"})
                return
            session.chat_history.append(
                {"role": "assistant", "content": streamer.text})
            deps.session_store.save(session)
        yield sse({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/api/state")
def state():
    deps = _deps
    session = deps.session_store.load()
    ws = deps.config.workspace
    result = {"session": {k: v for k, v in session.to_dict().items()
                          if k != "chat_history"},
              "workspace": {"slug": ws.slug, "title": ws.title,
                            "total_days": ws.total_days},
              "day": None, "units": [], "sync_counts": {},
              "percentage": 0, "current_day": 0}
    if deps.state_store.exists():
        s = deps.state_store.load()
        day = s["current_day"]
        result["current_day"] = day
        result["percentage"] = s.get("overall_completion_percentage", 0)
        day_data = s["days"].get(str(day), {})
        result["day"] = {"date": day_data.get("date", ""),
                         "review_completed": day_data.get("review_completed", False),
                         "review_score": day_data.get("review_score", 0)}
        checks = (deps.memory.unit_checks(deps.memory.read(day))
                  if deps.memory.exists(day) else {})
        result["units"] = [
            {**u, "checked": checks.get(u["id"], False)}
            for u in day_data.get("units", [])]
        if deps.memory.exists(day):
            result["sync_counts"] = deps.memory.sync_counts(
                deps.memory.read(day))
    return result


@router.get("/api/commands")
def commands():
    from ..engine.commands.registry import CommandRegistry
    return CommandRegistry(_deps.config).info_list()


@router.get("/api/history")
def history():
    """聊天历史（页面加载时回填）。"""
    session = _deps.session_store.load()
    return {"messages": session.chat_history[-40:]}


@router.get("/api/doc")
def read_doc(name: str):
    """学习资料查看：memory=当日 StudyMemory，interview_qa=面试话术库。"""
    if name == "memory":
        day = _deps.state_store.load()["current_day"]
        path = _deps.memory.path_for(day)
        title = f"StudyMemory Day {day}"
    elif name == "interview_qa":
        path = _deps.config.docx_dir / "InterviewQA.md"
        title = "面试话术库 InterviewQA"
    else:
        return {"ok": False, "error": "未知文档类型", "content": ""}
    if not path.exists():
        return {"ok": True, "title": title, "content": "（文件不存在）"}
    return {"ok": True, "title": title,
            "content": path.read_text(encoding="utf-8")}


# ---------- 代码浏览器 ----------

from ..services.code_browser import CodeBrowser, CodeBrowserError
from ..services.config_writer import update_code_roots


def _code_browser() -> CodeBrowser:
    return CodeBrowser(_deps.config)


@router.get("/api/code/roots")
def code_roots():
    return {"roots": _code_browser().roots()}


@router.post("/api/code/roots")
def add_code_root(body: dict):
    name = (body or {}).get("name", "").strip()
    raw_path = (body or {}).get("path", "").strip()
    if not name or not raw_path:
        return {"ok": False, "error": "name 和 path 不能为空"}
    roots = _deps.config.code_roots
    if any(r["name"] == name for r in roots):
        return {"ok": False, "error": f"项目根已存在: {name}"}
    new_roots = roots + [{"name": name, "path": raw_path}]
    try:
        # 先验证目录存在再落盘
        cb = CodeBrowser(_deps.config)
        from ..services.config_service import WEB_ROOT
        from pathlib import Path as _P
        p = _P(raw_path) if _P(raw_path).is_absolute() else (WEB_ROOT / raw_path).resolve()
        if not p.is_dir():
            return {"ok": False, "error": f"目录不存在: {raw_path}"}
        update_code_roots(SETTINGS_PATH, new_roots)
        _deps.config.reload()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "roots": _code_browser().roots()}


@router.post("/api/code/roots/delete")
def delete_code_root(body: dict):
    name = (body or {}).get("name", "").strip()
    new_roots = [r for r in _deps.config.code_roots if r["name"] != name]
    if len(new_roots) == len(_deps.config.code_roots):
        return {"ok": False, "error": f"项目根不存在: {name}"}
    try:
        update_code_roots(SETTINGS_PATH, new_roots)
        _deps.config.reload()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "roots": _code_browser().roots()}


@router.get("/api/code/tree")
def code_tree(root: str, path: str = ""):
    try:
        return {"ok": True, "entries": _code_browser().list_dir(root, path)}
    except CodeBrowserError as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/code/file")
def code_file(root: str, path: str):
    try:
        return {"ok": True, **_code_browser().read_file(root, path)}
    except CodeBrowserError as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/code/resolve")
def code_resolve(path: str):
    """把 AI 回答中的路径引用解析到已配置代码根下的真实文件。"""
    hit = _code_browser().resolve(path)
    if not hit:
        return {"ok": False}
    return {"ok": True, **hit}


# ---------- 工作区 ----------

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


@router.get("/api/workspaces")
def workspaces_list():
    return WorkspaceService(_deps.config).list()


@router.get("/api/workspaces/presets")
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


@router.get("/api/workspaces/scan-preview")
def workspaces_scan_preview(path: str):
    try:
        return {"ok": True, "profile": repo_scan(path)}
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/workspaces/create")
def workspaces_create(body: WorkspaceCreateIn):
    try:
        ws = WorkspaceService(_deps.config, _deps.llm).create(body.model_dump())
    except (WorkspaceError, InitError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    if _rebind:
        _rebind()  # 重建 deps 指向新工作区
    return {"ok": True, "slug": ws.slug, "title": ws.title}


@router.post("/api/workspaces/switch")
def workspaces_switch(body: WorkspaceSwitchIn):
    try:
        ws = WorkspaceService(_deps.config).switch(body.slug)
    except WorkspaceError as e:
        return {"ok": False, "error": str(e)}
    if _rebind:
        _rebind()
    return {"ok": True, "slug": ws.slug, "title": ws.title}


@router.post("/api/workspaces/rescan")
def workspaces_rescan():
    try:
        WorkspaceService(_deps.config, _deps.llm).rescan()
    except (WorkspaceError, InitError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@router.post("/api/config/reload")
def reload_config():
    changed = _deps.config.reload()
    _deps.templates.reload()
    return {"reloaded": True, "changed": changed}


@router.post("/api/session/reset")
def reset_session():
    """清空对话历史（不影响 docx 学习数据）。用于清除上下文污染。"""
    session = _deps.session_store.load()
    n = len(session.chat_history)
    session.chat_history = []
    _deps.session_store.save(session)
    return {"cleared": n}


# ---------- 模型配置页面 ----------

from ..llm.factory import _BUILDERS, create_llm
from ..services.config_writer import (mask_key, update_env_file,
                                      update_toml_sections)
from ..services.config_service import ENV_PATH, SETTINGS_PATH

_PROVIDER_META = {
    "openai_compat": {"label": "OpenCode Go（OpenAI 兼容）",
                      "api_key_env": "LLM_API_KEY"},
    "deepseek_official": {"label": "DeepSeek 官方",
                          "api_key_env": "LLM_API_KEY_DEEPSEEK"},
    "mock": {"label": "Mock（离线假模型）"},
}


def _section_view(section: str) -> dict:
    cfg = _deps.config
    params = cfg.llm_config.get(section, {})
    meta = _PROVIDER_META.get(section, {})
    base_url = params.get("base_url") or cfg.env(
        params.get("base_url_env", "LLM_BASE_URL"))
    api_key = params.get("api_key") or cfg.env(
        params.get("api_key_env", meta.get("api_key_env", "LLM_API_KEY")))
    return {"model": params.get("model", ""),
            "base_url": base_url,
            "api_key_masked": mask_key(api_key),
            "has_key": bool(api_key)}


@router.get("/api/llm-config")
def get_llm_config():
    cfg = _deps.config
    return {
        "provider": cfg.llm_config.get("provider", "mock"),
        "fallback_provider": cfg.llm_config.get("fallback_provider", ""),
        "warmup_on_start": bool(cfg.llm_config.get("warmup_on_start", False)),
        "providers": [{"name": n, "label": _PROVIDER_META.get(n, {}).get("label", n)}
                      for n in _BUILDERS],
        "sections": {s: _section_view(s) for s in _PROVIDER_META if s != "mock"},
    }


class LlmConfigIn(BaseModel):
    provider: str
    fallback_provider: str = ""
    warmup_on_start: bool = True
    sections: dict[str, dict] = {}


def _toml_section_lines(name: str, params: dict, meta: dict) -> list[str]:
    lines = [f"[llm.{name}]"]
    lines.append(f'model = "{params.get("model", "")}"')
    lines.append(f"max_tokens = {int(params.get('max_tokens', 4096))}")
    lines.append(f"temperature = {float(params.get('temperature', 0.7))}")
    if params.get("base_url"):
        lines.append(f'base_url = "{params["base_url"]}"')
    lines.append(f'api_key_env = "{meta["api_key_env"]}"')
    return lines


@router.post("/api/llm-config")
def save_llm_config(body: LlmConfigIn):
    if body.provider not in _BUILDERS:
        return {"ok": False, "error": f"未知 provider: {body.provider}"}
    if body.fallback_provider and body.fallback_provider not in _BUILDERS:
        return {"ok": False, "error": f"未知 fallback provider: {body.fallback_provider}"}

    # 1. 写 settings.toml 的三个 llm 节区
    llm_lines = ["[llm]", f'provider = "{body.provider}"']
    if body.fallback_provider:
        llm_lines.append(f'fallback_provider = "{body.fallback_provider}"')
    llm_lines.append(f"warmup_on_start = {'true' if body.warmup_on_start else 'false'}")
    sections = {"llm": llm_lines}
    for name, meta in _PROVIDER_META.items():
        if name == "mock":
            continue
        params = body.sections.get(name) or _section_view(name)
        sections[f"llm.{name}"] = _toml_section_lines(name, params, meta)
    try:
        update_toml_sections(SETTINGS_PATH, sections)
    except Exception as e:
        return {"ok": False, "error": f"写入 settings.toml 失败: {e}"}

    # 2. 写 .env（仅用户填了新 key 时）
    env_updates = {}
    for name, meta in _PROVIDER_META.items():
        if name == "mock":
            continue
        params = body.sections.get(name) or {}
        new_key = (params.get("api_key") or "").strip()
        if new_key and "****" not in new_key:
            env_updates[meta["api_key_env"]] = new_key
    if env_updates:
        update_env_file(ENV_PATH, env_updates)

    # 3. 热生效：重载配置 + 重建 LLM 客户端
    _deps.config.reload()
    _deps.llm = create_llm(_deps.config)
    _deps.quiz.set_llm(_deps.llm)
    return {"ok": True, "config": get_llm_config()}


@router.post("/api/llm-config/test")
def test_llm_config(body: dict):
    section = (body or {}).get("section", "")
    if section == "mock":
        return {"ok": True, "detail": "Mock 渠道无需测试"}
    if section not in _BUILDERS:
        return {"ok": False, "error": f"未知 provider: {section}"}
    try:
        client = _BUILDERS[section](_deps.config)
        text = client.chat([{"role": "user", "content": "回复 OK"}], max_tokens=5)
        return {"ok": True, "detail": f"连接成功，模型回复：{text[:50]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
