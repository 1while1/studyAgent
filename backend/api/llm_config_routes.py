"""可观测性 + 模型配置 + 上下文状态路由：/api/observability/* /api/llm-config/* /api/context-status。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..engine.context_manager import ContextManager
from ..services.llm_config_service import LlmConfigService, PROVIDER_META
from ..services.config_service import SETTINGS_PATH  # noqa: F401 测试引用
from ..services.observer import get_observer

config_router = APIRouter(tags=["可观测性", "模型配置"])


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
    return LlmConfigService.get_config_view(_deps().config)


class LlmConfigIn(BaseModel):
    provider: str
    fallback_provider: str = ""
    warmup_on_start: bool = True
    sections: dict[str, dict] = {}
    context_budget_tokens: int | None = None
    context_trigger_ratio: float | None = None


@config_router.post("/api/llm-config")
def save_llm_config(body: LlmConfigIn):
    # 校验
    err = LlmConfigService.validate_providers(body.provider, body.fallback_provider)
    if err:
        return {"ok": False, "error": err}

    deps = _deps()
    allow_private = deps.config.data.get("allow_private_urls", False)
    err = LlmConfigService.validate_base_urls(body.sections, allow_private)
    if err:
        return {"ok": False, "error": err}

    # 写入（service 层）
    result = LlmConfigService.save_config(
        deps.config, body.provider, body.fallback_provider,
        body.warmup_on_start, body.sections,
        body.context_budget_tokens, body.context_trigger_ratio)
    if not result.get("ok"):
        return result

    # 渠道重建（api 层职责：操作运行时 deps）
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
    return LlmConfigService.test_provider(_deps().config, section)


# ---- 向后兼容别名（测试通过 routes 模块引用） ----
def _section_view(section: str) -> dict:
    return LlmConfigService.section_view(_deps().config, section)


def _context_view() -> dict:
    return LlmConfigService.context_view(_deps().config)
