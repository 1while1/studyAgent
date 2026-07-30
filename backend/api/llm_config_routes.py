"""可观测性 + 模型配置 + 上下文状态路由：/api/observability/* /api/llm-config/* /api/context-status。"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from ..engine.context_manager import ContextManager
from ..services.observer import get_observer

config_router = APIRouter(tags=["可观测性", "模型配置"])


def _validate_base_url(url: str, allow_private: bool = False) -> str | None:
    """校验 base_url，返回错误信息或 None（C-4 SSRF 防护）。"""
    if not url:
        return None  # 空值允许

    # 强制 http/https
    if not url.startswith(("http://", "https://")):
        return "base_url 必须以 http:// 或 https:// 开头"

    if allow_private:
        return None

    # 解析 hostname
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return "base_url 缺少主机名"

        # 检查是否为内网 IP
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return "base_url 不允许指向本地地址"

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return "base_url 不允许指向内网地址"
        except ValueError:
            pass  # hostname 不是 IP 地址（域名），允许

        return None
    except Exception:
        return "base_url 格式无效"


def _deps():
    from . import routes
    return routes._deps


# ---------- 可观测性（M2） ----------

@config_router.get("/api/observability/status")
def observability_status():
    deps = _deps()
    cfg = deps.config.llm_config
    st = get_observer(deps.config).status()
    return {**st, "provider": cfg.get("provider", "?"),
            "fallback_provider": cfg.get("fallback_provider", "")}


@config_router.get("/api/observability/usage")
def observability_usage(days: int = 7, ws: str = ""):
    """M9：days=0 表示全部；ws 非空按项目过滤。"""
    days = max(0, min(int(days), 365))
    return get_observer(_deps().config).usage_summary(days, ws=ws)


# ---------- 模型配置页面 ----------

from ..llm.factory import _BUILDERS, create_llm, create_llm_cheap
from ..services.config_writer import (_esc, mask_key, update_env_file,
                                      update_toml_sections)
from ..services.config_service import ENV_PATH, SETTINGS_PATH

_PROVIDER_META = {
    "openai_compat": {"label": "OpenCode Go（OpenAI 兼容）",
                      "api_key_env": "LLM_API_KEY"},
    "deepseek_official": {"label": "DeepSeek 官方",
                          "api_key_env": "LLM_API_KEY_DEEPSEEK"},
    "agnes": {"label": "Agnes（OpenAI 兼容，当前免费）",
              "api_key_env": "LLM_API_KEY_AGNES"},
    "mock": {"label": "Mock（离线假模型）"},
}


def _section_view(section: str) -> dict:
    cfg = _deps().config
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


def _context_view() -> dict:
    """上下文窗口视图（M5b）：预算/触发比例 + 模型上限与生效预算预览。"""
    from ..engine.context_manager import (_safe_float, _safe_int,
                                          effective_budget)
    cfg = _deps().config
    ctx = cfg.data.get("context", {})
    llm_cfg = cfg.llm_config
    provider = llm_cfg.get("provider", "")
    model = llm_cfg.get(provider, {}).get("model", "")
    limits = cfg.data.get("model_context", {})
    return {"budget_tokens": _safe_int(ctx.get("budget_tokens"), 256000),
            "trigger_ratio": _safe_float(ctx.get("trigger_ratio"), 0.8),
            "model": model,
            "model_limit": _safe_int(limits.get(model,
                                                limits.get("default", 32768)),
                                     32768),
            "effective_budget": effective_budget(cfg)}


@config_router.get("/api/context-status")
def context_status():
    """M8 上下文仪表：当前会话上下文占用（校准估算口径）。"""
    from ..engine.context_manager import _safe_float, effective_budget
    deps = _deps()
    session = deps.session_store.load()
    cm = ContextManager(deps)
    budget = effective_budget(deps.config)
    trigger = _safe_float(
        deps.config.data.get("context", {}).get("trigger_ratio"), 0.8)
    system = deps.prompts.build(
        session, learner_summary=cm.learner_summary(session))
    messages, _plan = cm.assemble(session, system)
    pinned = [m for m in messages if m["role"] == "system"]
    window = [m for m in messages if m["role"] != "system"]
    est_pinned = cm._est_text(pinned[0]["content"]) if pinned else 0
    est_archive = sum(cm._est_text(m["content"]) for m in pinned[1:])
    est_window = cm._est_messages(window)
    est_total = est_pinned + est_archive + est_window
    calib = session.ctx_calib or 0.0
    if calib > 0:
        total, source, scale = round(est_total * calib), "calibrated", calib
    else:
        total, source, scale = est_total, "estimated", 1.0
    return {
        "total": total, "source": source, "budget": budget,
        "ratio": round(total / budget, 4) if budget else 0,
        "trigger_ratio": trigger,
        "layers": {"pinned": round(est_pinned * scale),
                   "archive": round(est_archive * scale),
                   "window": round(est_window * scale)},
        "turns": len(session.chat_history),
        "archived_turns": max(0, min(session.archive_upto,
                                     len(session.chat_history))),
        "last_measured": (session.ctx_prompt_tokens
                          + session.ctx_completion_tokens)
                         if session.ctx_measured else None,
        "today": get_observer(deps.config).status()["today"],
    }


@config_router.get("/api/llm-config")
def get_llm_config():
    cfg = _deps().config
    return {
        "provider": cfg.llm_config.get("provider", "mock"),
        "fallback_provider": cfg.llm_config.get("fallback_provider", ""),
        "warmup_on_start": bool(cfg.llm_config.get("warmup_on_start", False)),
        "providers": [{"name": n, "label": _PROVIDER_META.get(n, {}).get("label", n)}
                      for n in _BUILDERS],
        "sections": {s: _section_view(s) for s in _PROVIDER_META if s != "mock"},
        "context": _context_view(),
    }


class LlmConfigIn(BaseModel):
    provider: str
    fallback_provider: str = ""
    warmup_on_start: bool = True
    sections: dict[str, dict] = {}
    context_budget_tokens: int | None = None
    context_trigger_ratio: float | None = None


def _toml_section_lines(name: str, params: dict, meta: dict) -> list[str]:
    lines = [f"[llm.{name}]"]
    lines.append(f'model = "{_esc(params.get("model", ""))}"')
    lines.append(f"max_tokens = {int(params.get('max_tokens', 4096))}")
    lines.append(f"temperature = {float(params.get('temperature', 0.7))}")
    if params.get("base_url"):
        lines.append(f'base_url = "{_esc(params["base_url"])}"')
    lines.append(f'api_key_env = "{_esc(meta["api_key_env"])}"')
    return lines


def _toml_value(v) -> str:
    """TOML 标量渲染：数字裸写，字符串加引号并转义（防写坏 settings，C3）。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return f'"{_esc(v)}"'


@config_router.post("/api/llm-config")
def save_llm_config(body: LlmConfigIn):
    if body.provider not in _BUILDERS:
        return {"ok": False, "error": f"未知 provider: {body.provider}"}
    if body.fallback_provider and body.fallback_provider not in _BUILDERS:
        return {"ok": False, "error": f"未知 fallback provider: {body.fallback_provider}"}

    deps = _deps()

    # C-4 SSRF 防护：校验所有 section 中的 base_url
    allow_private = deps.config.data.get("allow_private_urls", False)
    for section_name, section_data in body.sections.items():
        if isinstance(section_data, dict) and "base_url" in section_data:
            error = _validate_base_url(section_data["base_url"], allow_private)
            if error:
                return {"ok": False, "error": error}

    llm_lines = ["[llm]", f'provider = "{_esc(body.provider)}"']
    if body.fallback_provider:
        llm_lines.append(f'fallback_provider = "{_esc(body.fallback_provider)}"')
    llm_lines.append(f"warmup_on_start = {'true' if body.warmup_on_start else 'false'}")
    sections = {"llm": llm_lines}
    for name, params in body.sections.items():
        meta = _PROVIDER_META.get(name)
        if meta is None or name == "mock":
            continue
        sections[f"llm.{name}"] = _toml_section_lines(name, params, meta)
    if (body.context_budget_tokens is not None
            or body.context_trigger_ratio is not None):
        existing = dict(deps.config.data.get("context", {}))
        if body.context_budget_tokens is not None:
            existing["budget_tokens"] = max(1024, int(body.context_budget_tokens))
        if body.context_trigger_ratio is not None:
            r = float(body.context_trigger_ratio)
            existing["trigger_ratio"] = min(0.95, max(0.5, r))
        ordered = [k for k in ("budget_tokens", "trigger_ratio", "pin_top_k",
                               "archive_max_chars", "max_messages")
                   if k in existing]
        ordered += [k for k in existing if k not in ordered]
        sections["context"] = ["[context]"] + [
            f"{k} = {_toml_value(existing[k])}" for k in ordered]
    try:
        update_toml_sections(deps.config.path, sections)
    except Exception as e:
        return {"ok": False, "error": f"写入 settings.toml 失败: {e}"}

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

    deps.config.reload()
    warn = ""
    try:
        deps.llm = create_llm(deps.config)
        deps.llm_cheap = create_llm_cheap(deps.config) or deps.llm
        deps.quiz.set_llm(deps.llm)
    except Exception as e:
        warn = f"配置已保存，但新渠道构建失败（{e}）；运行态暂保留旧渠道"
    return {"ok": True, "config": get_llm_config(), "warning": warn}


@config_router.post("/api/llm-config/test")
def test_llm_config(body: dict):
    section = (body or {}).get("section", "")
    if section == "mock":
        return {"ok": True, "detail": "Mock 渠道无需测试"}
    if section not in _BUILDERS:
        return {"ok": False, "error": f"未知 provider: {section}"}
    try:
        client = _BUILDERS[section](_deps().config)
        text = client.chat([{"role": "user", "content": "回复 OK"}], max_tokens=5)
        return {"ok": True, "detail": f"连接成功，模型回复：{text[:50]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
