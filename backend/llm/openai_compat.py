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
        self._usage_opts = True  # 网关不支持 stream_options 时自动降级记忆

    def chat_stream(self, messages: list[Message],
                    max_tokens: int | None = None) -> Iterator[str]:
        self.last_usage = None
        use_opts = self._usage_opts
        while True:
            yielded = False
            try:
                kwargs = dict(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens or self._max_tokens,
                    temperature=self._temperature,
                    stream=True,
                )
                if use_opts:
                    # 请求末块下发 usage（DeepSeek 等支持；不支持的网关降级）
                    kwargs["stream_options"] = {"include_usage": True}
                stream = self._client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if not chunk.choices:
                        usage = getattr(chunk, "usage", None)
                        if usage is not None:
                            self.last_usage = {
                                "prompt_tokens": usage.prompt_tokens,
                                "completion_tokens": usage.completion_tokens,
                            }
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yielded = True
                        yield delta.content
                return
            except Exception:
                if use_opts and not yielded:
                    # 疑似网关不认 stream_options：降级重试一次并记住
                    use_opts = False
                    self._usage_opts = False
                    continue
                raise
