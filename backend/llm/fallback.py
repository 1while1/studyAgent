"""FallbackClient：主渠道失败时自动切换备用渠道。

- 若主渠道在吐出任何内容前就失败 → 静默切换备用渠道
- 若主渠道中途断流 → 追加提示后用备用渠道重新生成完整回答
"""

from __future__ import annotations

import logging
from typing import Iterator

from .base import LLMClient, Message

logger = logging.getLogger("study-web.llm.fallback")


class FallbackClient(LLMClient):
    def __init__(self, primary: LLMClient, fallback: LLMClient,
                 fallback_name: str = "fallback"):
        self._primary = primary
        self._fallback = fallback
        self._fallback_name = fallback_name

    def chat_stream(self, messages: list[Message],
                    max_tokens: int | None = None) -> Iterator[str]:
        yielded_any = False
        try:
            for delta in self._primary.chat_stream(messages, max_tokens=max_tokens):
                yielded_any = True
                yield delta
            return
        except Exception as e:
            logger.warning("主渠道失败，切换备用渠道 %s: %s", self._fallback_name, e)
        if yielded_any:
            yield "\n\n（主渠道中断，以下由备用渠道重新生成）\n\n"
        yield from self._fallback.chat_stream(messages, max_tokens=max_tokens)
