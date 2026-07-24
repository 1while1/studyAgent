"""OpenAI 兼容协议实现（SiliconFlow / DeepSeek / Kimi / OpenAI 均可）。

base_url / api_key 从环境变量读取（.env），model 等参数走 settings.toml。

长度截断处理：流式响应结束若 finish_reason=length（输出撞 max_tokens），
自动携带已生成内容发起续写请求，无缝拼接（用户反馈「一次性输出太多被
截断」的修复）；显式小预算调用（warmup max_tokens=1 / 压缩摘要）不续写。
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

    # 自动续写轮数上限：1 次原始 + 4 次续写 ≈ 5×max_tokens，覆盖任何教学段落；
    # 仍截断则提示用户手动「继续」（绝不静默截断）
    _MAX_CONTINUATIONS = 4

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

    def _stream_once(self, messages: list[Message],
                     max_tokens: int) -> Iterator[str]:
        """单轮流式请求；finish_reason 记录在 self._last_finish。"""
        self.last_usage = None
        self._last_finish = None
        use_opts = self._usage_opts
        while True:
            yielded = False
            try:
                kwargs = dict(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self._temperature,
                    stream=True,
                )
                if use_opts:
                    # 请求末块下发 usage（DeepSeek 等支持；不支持的网关降级）
                    kwargs["stream_options"] = {"include_usage": True}
                stream = self._client.chat.completions.create(**kwargs)
                for chunk in stream:
                    # usage 与 choices 无关地检查：OpenAI 走独立空 choices 末块，
                    # DeepSeek 把 usage 挂在带 finish_reason 的内容块上
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        self.last_usage = {
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                        }
                    if not chunk.choices:
                        continue
                    fr = getattr(chunk.choices[0], "finish_reason", None)
                    if fr:
                        self._last_finish = fr
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

    def chat_stream(self, messages: list[Message],
                    max_tokens: int | None = None) -> Iterator[str]:
        # 显式预算调用（warmup=1 / 压缩摘要）是设计好的短输出，不自动续写
        auto = max_tokens is None
        budget = max_tokens or self._max_tokens
        msgs = list(messages)
        acc = {"prompt_tokens": 0, "completion_tokens": 0}
        for attempt in range(self._MAX_CONTINUATIONS + 1):
            parts: list[str] = []
            for delta in self._stream_once(msgs, budget):
                parts.append(delta)
                yield delta
            if self.last_usage:  # 多轮 usage 累加（记账不漏续写轮）
                acc["prompt_tokens"] += self.last_usage.get("prompt_tokens") or 0
                acc["completion_tokens"] += \
                    self.last_usage.get("completion_tokens") or 0
                self.last_usage = dict(acc)
            if not auto or self._last_finish != "length":
                return
            if attempt >= self._MAX_CONTINUATIONS:
                yield "\n\n（回复过长已达续写上限，发送「继续」我可以接着讲）"
                return
            # 续写：带上已生成内容，让模型从断点无缝接续
            msgs = msgs + [
                {"role": "assistant", "content": "".join(parts)},
                {"role": "user", "content":
                 "（系统提示：上一条回复因长度限制被截断，请从断点处无缝继续，"
                 "不要重复已输出的内容，不要添加任何解释）"}]
