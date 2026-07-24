# -*- coding: utf-8 -*-
"""OpenAI 兼容客户端「长度截断自动续写」回归测试。

背景：finish_reason=length（输出撞 max_tokens）时流干净结束，
应用把半截回答当成完整回复渲染——用户看到「讲着讲着断了」。
修复：捕获 finish_reason，length 时携带已生成内容自动续写（≤4 轮），
显式小预算调用（warmup/压缩）不续写，仍超限则明示可手动「继续」。
SDK 用桩替代，断言请求序列与拼接结果。
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.llm.openai_compat import OpenAICompatClient


def _chunk(text=None, finish=None):
    delta = SimpleNamespace(content=text)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)],
        usage=None)


def _usage_chunk(pt=10, ct=20):
    return SimpleNamespace(
        choices=[], usage=SimpleNamespace(prompt_tokens=pt,
                                          completion_tokens=ct))


class _StubCompletions:
    """按脚本逐次返回流（每次 create 消费一份脚本）。"""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.scripts.pop(0))


def _make_client(scripts):
    stub = _StubCompletions(scripts)
    client = object.__new__(OpenAICompatClient)  # 跳过 __init__（不连网）
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=stub))
    client._model = "m"
    client._max_tokens = 4096
    client._temperature = 0.7
    client._usage_opts = False  # 不走 stream_options 分支
    return client, stub


class TestLengthContinuation(unittest.TestCase):
    def test_length_finish_auto_continues(self):
        client, stub = _make_client([
            [_chunk("第一段："), _chunk("甲乙丙"), _usage_chunk(10, 20),
             _chunk(None, finish="length")],
            [_chunk("丁戊己"), _usage_chunk(30, 40),
             _chunk(None, finish="stop")],
        ])
        out = "".join(client.chat_stream([{"role": "user", "content": "讲"}]))
        self.assertEqual(out, "第一段：甲乙丙丁戊己")
        self.assertEqual(len(stub.calls), 2)
        # 续写请求携带已生成内容 + 无缝继续指令
        msgs = stub.calls[1]["messages"]
        self.assertEqual(msgs[-2]["role"], "assistant")
        self.assertEqual(msgs[-2]["content"], "第一段：甲乙丙")
        self.assertIn("无缝继续", msgs[-1]["content"])
        # usage 两轮累加（记账不漏）
        self.assertEqual(client.last_usage,
                         {"prompt_tokens": 40, "completion_tokens": 60})

    def test_stop_finish_no_continuation(self):
        client, stub = _make_client([
            [_chunk("完整回答"), _chunk(None, finish="stop")],
        ])
        out = "".join(client.chat_stream([{"role": "user", "content": "讲"}]))
        self.assertEqual(out, "完整回答")
        self.assertEqual(len(stub.calls), 1)

    def test_explicit_budget_never_continues(self):
        """warmup/压缩等显式小预算调用：length 也绝不续写。"""
        client, stub = _make_client([
            [_chunk("短"), _chunk(None, finish="length")],
        ])
        out = "".join(client.chat_stream(
            [{"role": "user", "content": "预热"}], max_tokens=1))
        self.assertEqual(out, "短")
        self.assertEqual(len(stub.calls), 1)

    def test_continuation_cap_with_visible_hint(self):
        """始终 length：1+4 轮后停止，末尾明示可手动继续（绝不静默截断）。"""
        scripts = [[_chunk(f"第{i}段"), _chunk(None, finish="length")]
                   for i in range(10)]
        client, stub = _make_client(scripts)
        out = "".join(client.chat_stream([{"role": "user", "content": "讲"}]))
        self.assertEqual(len(stub.calls),
                         OpenAICompatClient._MAX_CONTINUATIONS + 1)
        self.assertIn("第0段", out)
        self.assertIn(f"第{OpenAICompatClient._MAX_CONTINUATIONS}段", out)
        self.assertNotIn("第5段", out)
        self.assertIn("续写上限", out)
        self.assertIn("继续", out)


if __name__ == "__main__":
    unittest.main()
