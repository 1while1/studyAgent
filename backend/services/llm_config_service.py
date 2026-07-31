"""LLM 配置业务服务：provider 校验、TOML 拼接、env 更新、渠道重建。

从 api/llm_config_routes.py 下沉的业务逻辑，api 层只做 HTTP 编排。
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from ..llm.factory import _BUILDERS
from .config_writer import (_esc, mask_key, update_env_file,
                            update_toml_sections)
from .config_service import ENV_PATH

PROVIDER_META = {
    "openai_compat": {"label": "OpenCode Go（OpenAI 兼容）",
                      "api_key_env": "LLM_API_KEY"},
    "deepseek_official": {"label": "DeepSeek 官方",
                          "api_key_env": "LLM_API_KEY_DEEPSEEK"},
    "agnes": {"label": "Agnes（OpenAI 兼容，当前免费）",
              "api_key_env": "LLM_API_KEY_AGNES"},
    "mock": {"label": "Mock（离线假模型）"},
}


def validate_base_url(url: str, allow_private: bool = False) -> str | None:
    """校验 base_url，返回错误信息或 None（C-4 SSRF 防护）。"""
    if not url:
        return None

    if not url.startswith(("http://", "https://")):
        return "base_url 必须以 http:// 或 https:// 开头"

    if allow_private:
        return None

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return "base_url 缺少主机名"

        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return "base_url 不允许指向本地地址"

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return "base_url 不允许指向内网地址"
        except ValueError:
            pass

        return None
    except Exception:
        return "base_url 格式无效"


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
    """TOML 标量渲染：数字裸写，字符串加引号并转义。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return f'"{_esc(v)}"'


class LlmConfigService:
    """LLM 配置业务逻辑封装。"""

    # ---------- 查询 ----------

    @staticmethod
    def section_view(config, section: str) -> dict:
        """单个 provider 配置视图。"""
        params = config.llm_config.get(section, {})
        meta = PROVIDER_META.get(section, {})
        base_url = params.get("base_url") or config.env(
            params.get("base_url_env", "LLM_BASE_URL"))
        api_key = params.get("api_key") or config.env(
            params.get("api_key_env", meta.get("api_key_env", "LLM_API_KEY")))
        return {"model": params.get("model", ""),
                "base_url": base_url,
                "api_key_masked": mask_key(api_key),
                "has_key": bool(api_key)}

    @staticmethod
    def context_view(config) -> dict:
        """上下文窗口视图（M5b）。"""
        from ..engine.context_manager import (_safe_float, _safe_int,
                                              effective_budget)
        ctx = config.data.get("context", {})
        llm_cfg = config.llm_config
        provider = llm_cfg.get("provider", "")
        model = llm_cfg.get(provider, {}).get("model", "")
        limits = config.data.get("model_context", {})
        return {"budget_tokens": _safe_int(ctx.get("budget_tokens"), 256000),
                "trigger_ratio": _safe_float(ctx.get("trigger_ratio"), 0.8),
                "model": model,
                "model_limit": _safe_int(limits.get(model,
                                                    limits.get("default", 32768)),
                                         32768),
                "effective_budget": effective_budget(config)}

    @staticmethod
    def get_config_view(config) -> dict:
        """GET /api/llm-config 完整视图。"""
        return {
            "provider": config.llm_config.get("provider", "mock"),
            "fallback_provider": config.llm_config.get("fallback_provider", ""),
            "warmup_on_start": bool(config.llm_config.get("warmup_on_start", False)),
            "providers": [{"name": n, "label": PROVIDER_META.get(n, {}).get("label", n)}
                          for n in _BUILDERS],
            "sections": {s: LlmConfigService.section_view(config, s)
                         for s in PROVIDER_META if s != "mock"},
            "context": LlmConfigService.context_view(config),
        }

    # ---------- 校验 ----------

    @staticmethod
    def validate_providers(provider: str, fallback_provider: str) -> str | None:
        """校验 provider 名称，返回错误信息或 None。"""
        if provider not in _BUILDERS:
            return f"未知 provider: {provider}"
        if fallback_provider and fallback_provider not in _BUILDERS:
            return f"未知 fallback provider: {fallback_provider}"
        return None

    @staticmethod
    def validate_base_urls(sections: dict, allow_private: bool) -> str | None:
        """SSRF 校验所有 section 中的 base_url。"""
        for section_name, section_data in sections.items():
            if isinstance(section_data, dict) and "base_url" in section_data:
                error = validate_base_url(section_data["base_url"], allow_private)
                if error:
                    return error
        return None

    # ---------- 写入 ----------

    @staticmethod
    def save_config(config, provider: str, fallback_provider: str,
                    warmup_on_start: bool, sections: dict,
                    context_budget_tokens: int | None,
                    context_trigger_ratio: float | None) -> dict:
        """执行完整保存流程：TOML 写入 → env 更新 → 重载。

        返回 {"ok": True/False, ...} 响应体。
        渠道重建由调用方（api 层）负责。
        """
        # 构建 TOML 节区
        llm_lines = ["[llm]", f'provider = "{_esc(provider)}"']
        if fallback_provider:
            llm_lines.append(f'fallback_provider = "{_esc(fallback_provider)}"')
        llm_lines.append(
            f"warmup_on_start = {'true' if warmup_on_start else 'false'}")
        toml_sections = {"llm": llm_lines}

        for name, params in sections.items():
            meta = PROVIDER_META.get(name)
            if meta is None or name == "mock":
                continue
            toml_sections[f"llm.{name}"] = _toml_section_lines(name, params, meta)

        if context_budget_tokens is not None or context_trigger_ratio is not None:
            existing = dict(config.data.get("context", {}))
            if context_budget_tokens is not None:
                existing["budget_tokens"] = max(1024, int(context_budget_tokens))
            if context_trigger_ratio is not None:
                r = float(context_trigger_ratio)
                existing["trigger_ratio"] = min(0.95, max(0.5, r))
            ordered = [k for k in ("budget_tokens", "trigger_ratio", "pin_top_k",
                                   "archive_max_chars", "max_messages")
                       if k in existing]
            ordered += [k for k in existing if k not in ordered]
            toml_sections["context"] = ["[context]"] + [
                f"{k} = {_toml_value(existing[k])}" for k in ordered]

        try:
            update_toml_sections(config.path, toml_sections)
        except Exception as e:
            return {"ok": False, "error": f"写入 settings.toml 失败: {e}"}

        # env 更新
        env_updates = {}
        for name, meta in PROVIDER_META.items():
            if name == "mock":
                continue
            params = sections.get(name) or {}
            new_key = (params.get("api_key") or "").strip()
            if new_key and "****" not in new_key:
                env_updates[meta["api_key_env"]] = new_key
        if env_updates:
            update_env_file(ENV_PATH, env_updates)

        config.reload()
        return {"ok": True}

    # ---------- 测试 ----------

    @staticmethod
    def test_provider(config, section: str) -> dict:
        """测试 provider 连通性。"""
        if section == "mock":
            return {"ok": True, "detail": "Mock 渠道无需测试"}
        if section not in _BUILDERS:
            return {"ok": False, "error": f"未知 provider: {section}"}
        try:
            client = _BUILDERS[section](config)
            text = client.chat([{"role": "user", "content": "回复 OK"}],
                               max_tokens=5)
            return {"ok": True, "detail": f"连接成功，模型回复：{text[:50]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
