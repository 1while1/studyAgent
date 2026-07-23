"""ScriptableLLM（M5c §10 测试机制）：谓词脚本 LLM。

规则形如 {"match": r"正则", "respond": "文本"}：按 messages 末条内容匹配
首个谓词并返回对应文本；无匹配返回默认文本；记录 calls 供动作边界断言
（§8.2：断言动作契约，不断言自由文本）。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.llm.base import LLMClient


class ScriptableLLM(LLMClient):
    def __init__(self, rules: list[dict], default: str = "【Scriptable 默认】"):
        self._rules = [(re.compile(r["match"]), r["respond"]) for r in rules]
        self._default = default
        self.calls: list[list[dict]] = []

    def chat_stream(self, messages, max_tokens=None):
        self.calls.append([dict(m) for m in messages])
        hay = messages[-1]["content"] if messages else ""
        text = next((resp for pat, resp in self._rules if pat.search(hay)),
                    self._default)
        step = 16
        for i in range(0, len(text), step):
            yield text[i:i + step]
