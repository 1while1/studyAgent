"""FallbackClient 主备切换测试（用假客户端，不调真实 API）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.llm.base import LLMClient
from backend.llm.fallback import FallbackClient


class _FailLLM(LLMClient):
    def __init__(self, mid_stream=False):
        self._mid = mid_stream

    def chat_stream(self, messages, max_tokens=None):
        if self._mid:
            yield "半截回答"
        raise RuntimeError("模拟主渠道故障")


class _OKLLM(LLMClient):
    def chat_stream(self, messages, max_tokens=None):
        yield "备用渠道回答"


class TestFallback(unittest.TestCase):
    def test_primary_ok(self):
        client = FallbackClient(_OKLLM(), _OKLLM())
        self.assertEqual(client.chat([{"role": "user", "content": "hi"}]),
                         "备用渠道回答")

    def test_fail_before_any_chunk_switches_silently(self):
        client = FallbackClient(_FailLLM(mid_stream=False), _OKLLM())
        text = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(text, "备用渠道回答")
        self.assertNotIn("中断", text)

    def test_fail_mid_stream_marks_and_regenerates(self):
        client = FallbackClient(_FailLLM(mid_stream=True), _OKLLM())
        text = client.chat([{"role": "user", "content": "hi"}])
        self.assertIn("半截回答", text)
        self.assertIn("主渠道中断", text)
        self.assertIn("备用渠道回答", text)

    def test_both_fail_raises(self):
        client = FallbackClient(_FailLLM(), _FailLLM())
        with self.assertRaises(RuntimeError):
            client.chat([{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
