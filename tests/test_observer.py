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
                         "输入文本" * 150, "输出文本" * 30,
                         {"prompt_tokens": 500, "completion_tokens": 100},
                         ok=True)
        recs = self._records()
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual((r["in_tokens"], r["out_tokens"]), (500, 100))
        self.assertFalse(r["tokens_est"])
        self.assertTrue(r["ok"])
        # usage 到达后应写校准文件（样本需达下限，见下限测试）
        self.assertTrue(self.obs._calib_path.exists())

    def test_small_samples_rejected_from_calib(self):
        """Agnes 类网关固定开销会主导小样本比率（"Say OK"报 254 prompt），
        est 低于下限的样本不得参与 ratio 学习（防 EWMA 失真）。"""
        tiny = "你好"  # est ≪ 400
        self.obs.log_llm("agnes", "agnes-2.0-flash", 500, tiny, "好",
                         {"prompt_tokens": 254, "completion_tokens": 2},
                         ok=True)
        self.assertEqual(self.obs._load_calib(), {})  # 什么都没学
        # 但记账本身不受影响
        r = self._records()[0]
        self.assertEqual(r["in_tokens"], 254)
        self.assertFalse(r["tokens_est"])

    def test_large_sample_still_learns(self):
        big = "中文输入" * 200  # est ≥ 400
        base = est_tokens(big)
        self.assertGreaterEqual(base, 400)
        self.obs.log_llm("agnes", "agnes-2.0-flash", 500, big, "",
                         {"prompt_tokens": int(base * 2), "completion_tokens": 0},
                         ok=True)
        ratio = self.obs._load_calib()["agnes/agnes-2.0-flash"]["ratio"]
        self.assertAlmostEqual(ratio, 2.0, delta=0.01)

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


_PRICING_TOML = (
    '[pricing."m"]\ninput_per_million = 10\noutput_per_million = 20\n'
    'cache_hit_per_million = 1\ncurrency = "CNY"\n'
    '[pricing.peak]\nmultiplier = 2\nhours = [[9, 12]]\n')


class TestUsageM9(ObserverTestBase):
    """M9：缓存命中成本 / 峰谷倍率 / ws 维度 / seed_today / 日志滚动 / 聚合扩展。"""

    def setUp(self):
        super().setUp()
        (self.tmp / "settings.toml").write_text(_PRICING_TOML, encoding="utf-8")
        self.config.reload()
        self.obs = Observer(self.config)

    def _raw(self, ts: str, **kw):
        """手写一条 llm 记录（可控时间戳/字段）。"""
        import json as _json
        rec = {"kind": "llm", "provider": "p", "model": "m", "task": "chat",
               "in_tokens": 0, "out_tokens": 0, "ok": True, "ts": ts}
        rec.update(kw)
        self.obs._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.obs._log_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")

    def test_cache_hit_and_peak_cost(self):
        # 谷时 20:00，未命中 1M → 10 元
        self._raw("2026-07-20 20:00:00", in_tokens=1_000_000)
        # 峰时 10:00，未命中 1M → ×2 = 20 元
        self._raw("2026-07-20 10:00:00", in_tokens=1_000_000)
        # 谷时，1M 输入其中 60 万命中：0.4M×10 + 0.6M×1 = 4.6 元
        self._raw("2026-07-21 20:00:00", in_tokens=1_000_000,
                  cache_hit=600_000)
        s = self.obs.usage_summary(0)
        self.assertAlmostEqual(s["totals"]["cost"], 10 + 20 + 4.6, places=3)
        self.assertEqual(s["totals"]["cache_hit"], 600_000)
        self.assertAlmostEqual(s["kpi"]["cache_hit_rate"],
                               round(600_000 / 3_000_000, 4), places=4)

    def test_no_cache_field_legacy_records_full_price(self):
        """旧记录无 cache_hit 字段 → 全部按未命中价（略高估，设计留档）。"""
        self._raw("2026-07-20 20:00:00", in_tokens=1_000_000)
        s = self.obs.usage_summary(0)
        self.assertAlmostEqual(s["totals"]["cost"], 10.0, places=3)

    def test_workspace_dimension_and_filter(self):
        self._raw("2026-07-20 20:00:00", in_tokens=100, ws="ragent")
        self._raw("2026-07-20 20:00:01", in_tokens=200, ws="tinyrag")
        self._raw("2026-07-20 20:00:02", in_tokens=400)  # 无 ws → 旧记录桶
        s = self.obs.usage_summary(0)
        self.assertEqual(set(s["workspaces"]),
                         {"ragent", "tinyrag", Observer.LEGACY_WS})
        by = {b["ws"]: b for b in s["by_workspace"]}
        self.assertEqual(by["ragent"]["in_tokens"], 100)
        self.assertEqual(by[Observer.LEGACY_WS]["in_tokens"], 400)
        f = self.obs.usage_summary(0, ws="ragent")
        self.assertEqual(f["totals"]["in_tokens"], 100)
        self.assertEqual(f["totals"]["calls"], 1)

    def test_seed_today_restart_safe(self):
        import time as _time
        today = _time.strftime("%Y-%m-%d")
        self._raw(f"{today} 01:00:00", in_tokens=111, out_tokens=5)
        self._raw("2020-01-01 01:00:00", in_tokens=999)  # 非今日
        obs2 = Observer(self.config)  # 模拟重启
        st = obs2.status()["today"]
        self.assertEqual(st["calls"], 1)
        self.assertEqual(st["in_tokens"], 111)
        self.assertEqual(st["out_tokens"], 5)

    def test_log_rotation(self):
        self.obs._ROTATE_BYTES = 50  # 极小阈值触发轮转
        self.obs.log_llm("p", "m", 1, "i" * 100, "o", None, ok=True)
        self.obs.log_llm("p", "m", 1, "i", "o", None, ok=True)  # 触发轮转
        backup = self.obs._log_path.parent / (self.obs._log_path.name + ".1")
        self.assertTrue(backup.exists())
        recs = self._records()
        self.assertEqual(len(recs), 1)  # 新文件只含轮转后记录

    def test_daily_and_by_model_task(self):
        self._raw("2026-07-20 20:00:00", in_tokens=100, out_tokens=10,
                  model="m", task="chat")
        self._raw("2026-07-21 20:00:00", in_tokens=200, out_tokens=20,
                  model="m2", task="warmup")
        s = self.obs.usage_summary(0)
        self.assertEqual([(d["date"], d["in_tokens"]) for d in s["daily"]],
                         [("2026-07-20", 100), ("2026-07-21", 200)])
        bm = {b["model"]: b for b in s["by_model"]}
        self.assertEqual(bm["m2"]["in_tokens"], 200)
        bt = {b["task"]: b for b in s["by_task"]}
        self.assertEqual(bt["warmup"]["calls"], 1)
        self.assertIn("today", s)
        self.assertIn("kpi", s)


if __name__ == "__main__":
    unittest.main()
