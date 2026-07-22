"""AI 读文件 tool-use 闭环（engine/tool_use.ToolUseLoop）测试。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.tool_use import ToolUseLoop
from backend.llm.base import LLMClient
from backend.services.code_browser import CodeBrowser
from backend.services.config_service import ConfigService


class RecordingLLM(LLMClient):
    """按脚本分轮回答，并记录每次调用的 messages（供断言注入内容）。"""

    def __init__(self, script: list[str], chunk: int = 16):
        self._script = list(script)
        self._chunk = chunk
        self.calls: list[list[dict]] = []

    def chat_stream(self, messages, max_tokens=None):
        self.calls.append([dict(m) for m in messages])
        text = self._script.pop(0) if self._script else "（脚本耗尽）"
        for i in range(0, len(text), self._chunk):
            yield text[i:i + self._chunk]


class TestToolUseLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tooluse_"))
        proj = self.tmp / "projA"
        proj.mkdir()
        (proj / "a.txt").write_text("l1\nl2\nl3\nl4\nl5", encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(
            f'[[code_roots]]\nname = "projA"\npath = "{proj.as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.browser = CodeBrowser(self.config)
        self.base_messages = [{"role": "system", "content": "sys"},
                              {"role": "user", "content": "问"}]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, script, chunk=16):
        llm = RecordingLLM(script, chunk=chunk)
        loop = ToolUseLoop(self.config, llm, self.browser)
        events = list(loop.run(self.base_messages))
        return llm, loop, events

    @staticmethod
    def _deltas(events):
        return "".join(e["content"] for e in events if e["type"] == "delta")

    @staticmethod
    def _reads(events):
        return [e for e in events if e["type"] == "tool_read"]

    def test_marker_intercepted_and_injected(self):
        llm, loop, events = self._run([
            "前文\n[READ:projA/a.txt:L2-L3]\n（标记后被丢弃）",
            "续写完毕",
        ])
        text = self._deltas(events)
        self.assertNotIn("READ:", text)
        self.assertNotIn("READ:", loop.text)
        self.assertIn("前文", text)
        self.assertIn("续写完毕", text)
        reads = self._reads(events)
        self.assertEqual(len(reads), 1)
        self.assertTrue(reads[0]["ok"])
        self.assertEqual(reads[0]["lines"], "L2-L3")
        # 第二次调用：注入真实文件行
        self.assertEqual(len(llm.calls), 2)
        injected = llm.calls[1][-1]["content"]
        self.assertIn("【系统注入】", injected)
        self.assertIn("l2\nl3", injected)
        self.assertNotIn("l4", injected)
        # 续写上下文带了已产出文本
        self.assertEqual(llm.calls[1][-2]["role"], "assistant")
        self.assertIn("前文", llm.calls[1][-2]["content"])

    def test_marker_split_across_deltas(self):
        _, loop, events = self._run(
            ["看这里\n[READ:projA/a.txt]\n", "完"], chunk=3)
        self.assertNotIn("READ:", self._deltas(events))
        self.assertEqual(len(self._reads(events)), 1)
        self.assertIn("完", loop.text)

    def test_missing_file_continues(self):
        llm, loop, events = self._run([
            "[READ:projA/no-such.java]\n", "跳过该文件继续",
        ])
        reads = self._reads(events)
        self.assertEqual(len(reads), 1)
        self.assertFalse(reads[0]["ok"])
        self.assertIn("未找到", llm.calls[1][-1]["content"])
        self.assertIn("跳过该文件继续", loop.text)

    def test_missing_file_with_suggestions(self):
        # 文件名接近时有候选：no-such.txt vs 真实 a.txt？词干太短不命中，
        # 用接近真实文件的假路径验证候选机制
        (self.tmp / "projA" / "CouponTypeEnum.java").write_text(
            "enum X {}", encoding="utf-8")
        llm, loop, events = self._run([
            "[READ:projA/enums/CouponTypeEnum.java:L1-L1]\n", "用候选重读",
        ])
        reads = self._reads(events)
        self.assertFalse(reads[0]["ok"])
        self.assertIn("CouponTypeEnum.java", reads[0]["suggestions"][0])
        injected = llm.calls[1][-1]["content"]
        self.assertIn("候选文件", injected)
        self.assertIn("projA/CouponTypeEnum.java", injected)

    def test_read_limit_silent_drop(self):
        script = ["[READ:projA/a.txt:L1-L1]\n"] * 3 + \
                 ["[READ:projA/a.txt:L1-L1]\n超限后的尾巴"]
        llm, loop, events = self._run(script)
        self.assertEqual(len(self._reads(events)), 3)
        self.assertEqual(len(llm.calls), 4)
        # 第 4 个标记被静默丢弃，但其后的正常文本继续下发
        self.assertIn("超限后的尾巴", loop.text)
        self.assertNotIn("READ:", loop.text)

    def test_line_slice_and_truncation(self):
        # ai_read_max_lines=2：L1-L5 截断为 L1-L2
        settings = self.tmp / "s2.toml"
        proj = self.tmp / "projA"
        settings.write_text(
            'ai_read_max_lines = 2\n'
            f'[[code_roots]]\nname = "projA"\npath = "{proj.as_posix()}"\n',
            encoding="utf-8")
        config = ConfigService(settings)
        llm = RecordingLLM(["[READ:projA/a.txt:L1-L5]\n", "完"])
        loop = ToolUseLoop(config, llm, CodeBrowser(config))
        list(loop.run(self.base_messages))
        injected = llm.calls[1][-1]["content"]
        self.assertIn("l1\nl2", injected)
        self.assertNotIn("l3", injected)
        self.assertIn("截断", injected)

    def test_no_marker_passthrough(self):
        _, loop, events = self._run(["纯讲解文本\n第二行"])
        self.assertEqual(self._reads(events), [])
        self.assertEqual(loop.text, "纯讲解文本\n第二行")

    def test_backtick_wrapped_marker(self):
        # 模型把标记裹进反引号（线上真实踩坑）→ 照样截获，反引号也不残留
        llm, loop, events = self._run([
            "先读取这个类。\n\n`[READ:projA/a.txt:L1-L2]`\n\n",
            "基于真实代码讲完",
        ])
        self.assertEqual(len(self._reads(events)), 1)
        self.assertNotIn("READ:", loop.text)
        self.assertNotIn("`", loop.text)
        self.assertIn("l1\nl2", llm.calls[1][-1]["content"])

    def test_inline_marker_mid_sentence(self):
        # 行内出现的标记也能截获：前文照常下发
        _, loop, events = self._run([
            "先读取 [READ:projA/a.txt] 这个文件再讲", "完",
        ])
        self.assertEqual(len(self._reads(events)), 1)
        self.assertIn("先读取 ", loop.text)
        self.assertNotIn("READ:", loop.text)

    def test_unclosed_marker_flushed_as_text(self):
        # 流结束标记未闭合 → 按普通文本下发，不丢内容
        _, loop, events = self._run(["前面 [READ:projA/a.txt 没闭合"])
        self.assertEqual(self._reads(events), [])
        self.assertIn("[READ:projA/a.txt 没闭合", loop.text)

    def test_marker_prefix_split_tiny_chunks(self):
        # 逐字符到达的标记也能识别（hold-back 前缀残片）
        _, loop, events = self._run(
            ["看 `[READ:projA/a.txt:L2-L2]` 吧", "完"], chunk=1)
        self.assertEqual(len(self._reads(events)), 1)
        self.assertEqual(self._reads(events)[0]["lines"], "L2-L2")
        self.assertNotIn("READ:", loop.text)

    def test_suggest_camelcase_suffix_divergence(self):
        # Entity vs DO 后缀差异：stem 最长前缀命中（线上 CouponTemplate 真实场景）
        (self.tmp / "projA" / "dao").mkdir()
        (self.tmp / "projA" / "dao" / "CouponTemplateDO.java").write_text(
            "class DO {}", encoding="utf-8")
        tips = self.browser.suggest("projA/domain/entity/CouponTemplateEntity.java")
        self.assertTrue(tips)
        self.assertIn("CouponTemplateDO.java", tips[0]["path"])

    def test_empty_file_injection(self):
        (self.tmp / "projA" / "empty.sql").write_text("", encoding="utf-8")
        llm, loop, events = self._run([
            "[READ:projA/empty.sql]\n", "文件是空的，换别的讲",
        ])
        reads = self._reads(events)
        self.assertTrue(reads[0]["ok"])
        injected = llm.calls[1][-1]["content"]
        self.assertIn("内容为空", injected)
        self.assertIn("禁止编造", injected)


if __name__ == "__main__":
    unittest.main()
