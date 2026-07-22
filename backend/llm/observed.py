"""ObservedLLM：给任意 LLMClient 包一层调用记账（M2 可观测）。

- 每次 chat_stream 记录：渠道/模型/耗时/输入输出文本/usage/成败 → observer.log_llm
- usage 读取客户端的 `last_usage` 属性（openai_compat 流式结束时捕获）
- 任务标签走 observer 模块的 ContextVar（task_scope），LLM 接口零改动
- 记账绝不阻断主流程：observer 内部已吞异常，这里不再捕获
"""

from __future__ import annotations

import time
from typing import Iterator

from ..services.observer import Observer
from .base import LLMClient, Message


class ObservedLLM(LLMClient):
    def __init__(self, inner: LLMClient, observer: Observer,
                 provider: str):
        self._inner = inner
        self._observer = observer
        self._provider = provider

    @property
    def inner(self) -> LLMClient:
        return self._inner

    def chat_stream(self, messages: list[Message],
                    max_tokens: int | None = None) -> Iterator[str]:
        start = time.time()
        out_parts: list[str] = []
        err = ""
        try:
            for delta in self._inner.chat_stream(messages, max_tokens=max_tokens):
                out_parts.append(delta)
                yield delta
        except Exception as e:
            err = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start) * 1000)
            in_text = "\n".join(str(m.get("content", "")) for m in messages)
            usage = getattr(self._inner, "last_usage", None)
            model = getattr(self._inner, "_model", "") or type(self._inner).__name__
            self._observer.log_llm(
                self._provider, model, latency_ms, in_text,
                "".join(out_parts), usage, ok=not err, error=err)
