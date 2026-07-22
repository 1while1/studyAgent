"""OpenAI 兼容协议实现（SiliconFlow / DeepSeek / Kimi / OpenAI 均可）。

base_url / api_key 从环境变量读取（.env），model 等参数走 settings.toml。
"""

from __future__ import annotations

from typing import Iterator

from ..services.config_service import ConfigService
from .base import LLMClient, Message


class OpenAICompatClient(LLMClient):
    """section 指向 settings.toml 中 [llm.<section>] 配置块。

    配置键：model / max_tokens / temperature / base_url（直写）
    或 base_url_env / api_key_env（从环境变量读取，默认 LLM_BASE_URL / LLM_API_KEY）。
    """

    def __init__(self, config: ConfigService, section: str = "openai_compat"):
        from openai import OpenAI  # 延迟导入，Mock 模式下不强制依赖

        params = config.llm_config.get(section, {})
        base_url = params.get("base_url") or config.env(
            params.get("base_url_env", "LLM_BASE_URL"))
        api_key = params.get("api_key") or config.env(
            params.get("api_key_env", "LLM_API_KEY"))
        if not base_url or not api_key:
            raise RuntimeError(
                f"[llm.{section}] 缺少 base_url/api_key，请配置 study-web/.env（见 .env.example）")
        self._model = params.get("model", "deepseek-ai/DeepSeek-V3")
        self._max_tokens = params.get("max_tokens", 4096)
        self._temperature = params.get("temperature", 0.7)
        timeout = float(params.get("timeout")
                        or config.get("llm_timeout", 300))
        self._client = OpenAI(base_url=base_url, api_key=api_key,
                              timeout=timeout, max_retries=1)

    def chat_stream(self, messages: list[Message],
                    max_tokens: int | None = None) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens or self._max_tokens,
            temperature=self._temperature,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:  # 跳过心跳/用量等空块（部分兼容网关会下发）
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
