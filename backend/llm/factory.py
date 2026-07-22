"""LLM 工厂：按 settings.toml [llm] 配置实例化，支持主备 fallback。

新增渠道：在 _BUILDERS 注册一个构建函数 + settings.toml 加配置块。
"""

from __future__ import annotations

from ..services.config_service import ConfigService
from .base import LLMClient
from .fallback import FallbackClient
from .mock import MockLLM
from .openai_compat import OpenAICompatClient

_BUILDERS = {
    "mock": lambda config, **kw: MockLLM(**kw),
    "openai_compat": lambda config, **kw: OpenAICompatClient(config, "openai_compat"),
    "deepseek_official": lambda config, **kw: OpenAICompatClient(config, "deepseek_official"),
}


def register_provider(name: str, builder) -> None:
    _BUILDERS[name] = builder


def _build(provider: str, config: ConfigService, **kwargs) -> LLMClient:
    if provider not in _BUILDERS:
        raise RuntimeError(
            f"未知 LLM provider: {provider}（可用: {', '.join(_BUILDERS)}）")
    client = _BUILDERS[provider](config, **kwargs)
    if provider == "mock":
        return client  # 假模型不记账
    from ..services.observer import get_observer
    from .observed import ObservedLLM
    return ObservedLLM(client, get_observer(config), provider)


def create_llm(config: ConfigService, **kwargs) -> LLMClient:
    provider = config.llm_config.get("provider", "mock")
    primary = _build(provider, config, **kwargs)
    fallback_name = config.llm_config.get("fallback_provider", "")
    if fallback_name and fallback_name != provider:
        try:
            fallback = _build(fallback_name, config)
        except Exception:
            # 备用渠道未配置好（如缺 key）时静默降级为单渠道
            return primary
        return FallbackClient(primary, fallback, fallback_name)
    return primary
