"""LLM 客户端抽象接口。新增渠道：实现本接口并在 factory 注册。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}


class LLMClient(ABC):
    last_usage: dict | None = None  # 最近一次调用的 usage（openai_compat 捕获）

    @abstractmethod
    def chat_stream(self, messages: list[Message],
                    max_tokens: int | None = None) -> Iterator[str]:
        """流式返回内容增量。max_tokens 可覆盖默认上限（预热等场景）。"""

    def chat(self, messages: list[Message], max_tokens: int | None = None) -> str:
        return "".join(self.chat_stream(messages, max_tokens=max_tokens))
