"""可观测性（services/observer + llm/observed）测试。"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import ConfigService
from backend.services.observer import Observer, est_tokens, task_scope


class ObserverTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="observer_"))
        settings = self.tmp / "settings.toml"
        settings.write_text("", encoding="utf-8")
        self.config = ConfigService(settings)
        self.obs = Observer(self.config)
        self.log_path = self.obs._log_path

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _records(self):
        if not self.log_path.exists():
            return []
        return [json.loads(l) for l in
                self.log_path.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestEstTokens(ObserverTestBase):
    def test_empty(self):
        self.assertEqual(est_tokens(""), 0)

    def test_monotonic_and_cjk_weight(self):
        short = "你好世界"
        long = "你好世界" * 10
        self.assertGreater(est_tokens(long), est_tokens(short))
        # 汉字估算显著重于英文字母
        self.assertGreater(est_tokens("汉字测试"), est_tokens("abcd"))


class TestLogLlm(ObserverTestBase):
    def test_usage_preferred_over_estimate(self):
        self.obs.log_llm("deepseek_official", "deepseek-chat", 1200,
                         "输入文本" * 50, "输出文本" * 10,
                         {"prompt_tokens": 500, "completion_tokens": 100},
                         ok=True)
        recs = self._records()
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual((r["in_tokens"], r["out_tokens"]), (500, 100))
        self.assertFalse(r["tokens_est"])
        self.assertTrue(r["ok"])
        # usage 到达后应写校准文件
        self.assertTrue(self.obs._calib_path.exists())

    def test_estimate_when_no_usage_and_calibrated(self):
        in_text = "中文输入" * 100
        # 先灌一条 usage=2×估算 的记录 → 校准比率 ≈2
        base = est_tokens(in_text)
        self.obs._update_calib("p/m", 2.0)
        self.obs.log_llm("p", "m", 100, in_text, "", None, ok=True)
        r = self._records()[0]
        self.assertTrue(r["tokens_est"])
        self.assertEqual(r["in_tokens"], round(base * 2.0))

    def test_status_memory(self):
        self.obs.log_llm("p", "m", 321, "in", "out", None, ok=False,
                         error="boom")
        st = self.obs.status()
        self.assertEqual(st["last_call"]["latency_ms"], 321)
        self.assertFalse(st["last_call"]["ok"])
        self.assertEqual(st["last_call"]["error"], "boom")
        self.assertEqual(st["today"]["calls"], 1)

    def test_task_scope_label(self):
        with task_scope("warmup"):
            self.obs.log_llm("p", "m", 1, "i", "o", None, ok=True)
        with task_scope("init"):
            self.obs.log_llm("p", "m", 1, "i", "o", None, ok=True)
        self.obs.log_llm("p", "m", 1, "i", "o", None, ok=True)  # 默认 chat
        tasks = [r["task"] for r in self._records()]
        self.assertEqual(tasks, ["warmup", "init", "chat"])

    def test_usage_summary_aggregates_and_cost(self):
        self.obs.log_llm("deepseek_official", "deepseek-chat", 1, "i", "o",
                         {"prompt_tokens": 1000, "completion_tokens": 500},
                         ok=True)
        # 换无校准记录的渠道，隔离校准比率耦合
        self.obs.log_llm("p2", "m2", 1, "i", "o", None, ok=False, error="x")
        summary = self.obs.usage_summary(7)
        self.assertEqual(summary["totals"]["calls"], 2)
        self.assertEqual(summary["totals"]["failures"], 1)
        self.assertEqual(summary["totals"]["in_tokens"],
                         1000 + est_tokens("i"))  # 第二条为估算
        row = next(r for r in summary["rows"] if r["model"] == "m2")
        self.assertEqual(row["est_calls"], 1)

    def test_disabled_noop(self):
        (self.tmp / "settings.toml").write_text("agent_log_enabled = false",
                                                encoding="utf-8")
        self.config.reload()
        obs = Observer(self.config)
        obs.log_llm("p", "m", 1, "i", "o", None, ok=True)
        self.assertFalse(obs._log_path.exists())

    def test_log_tool(self):
        self.obs.log_tool("read_doc", True, "docs/a")
        r = self._records()[0]
        self.assertEqual((r["kind"], r["name"], r["ok"]), ("tool", "read_doc", True))


class TestObservedLLM(ObserverTestBase):
    def test_wrapper_logs_success_and_usage(self):
        from backend.llm.base import LLMClient
        from backend.llm.observed import ObservedLLM

        class Fake(LLMClient):
            def chat_stream(self, messages, max_tokens=None):
                self.last_usage = {"prompt_tokens": 10, "completion_tokens": 3}
                yield "回答"

        llm = ObservedLLM(Fake(), self.obs, "fake")
        text = "".join(llm.chat_stream([{"role": "user", "content": "问"}]))
        self.assertEqual(text, "回答")
        r = self._records()[0]
        self.assertEqual((r["provider"], r["in_tokens"], r["out_tokens"]),
                         ("fake", 10, 3))
        self.assertTrue(r["ok"])

    def test_wrapper_logs_failure_and_reraises(self):
        from backend.llm.base import LLMClient
        from backend.llm.observed import ObservedLLM

        class Boom(LLMClient):
            def chat_stream(self, messages, max_tokens=None):
                yield "半截"
                raise RuntimeError("断流")

        llm = ObservedLLM(Boom(), self.obs, "boom")
        with self.assertRaises(RuntimeError):
            list(llm.chat_stream([{"role": "user", "content": "问"}]))
        r = self._records()[0]
        self.assertFalse(r["ok"])
        self.assertIn("断流", r["error"])
        self.assertEqual(r["out_tokens"], est_tokens("半截"))


if __name__ == "__main__":
    unittest.main()
