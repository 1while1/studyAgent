# -*- coding: utf-8 -*-
"""M8 上下文仪表测试：usage 链式提取 / 账本落盘 / context-status 校准口径。

设计约定（校准系数制）：
- 每轮 done 后 session 记录 API 实测 prompt/completion + 校准系数
  calib = 实测 prompt / 本地估算 prompt（随实测自动修正，持久化）
- 网关降级轮（无 usage）→ measured=False 保留旧实测值与 calib
- 仪表显示 = 当前会话装配估算 × calib：同一会话状态刷新/重启显示稳定，
  不锚定「最后一轮调用的 prompt」（指令轮含 SOP 卡/教材注入，差异巨大）
- 分层分解只能本地估算，按 calib 缩放
"""
import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api import routes
from backend.domain.models import SessionContext
from backend.engine.orchestrator import ChatOrchestrator
from backend.engine.tool_use import extract_usage
from backend.llm.base import LLMClient
from backend.llm.fallback import FallbackClient
from backend.llm.mock import MockLLM
from backend.services.config_service import ConfigService

TODAY = date.today().isoformat()


class _UsageLLM(LLMClient):
    """模拟返回真实 usage 的渠道。"""

    def __init__(self, pt=1234, ct=56):
        self._pt, self._ct = pt, ct
        self.last_usage = None

    def chat_stream(self, messages, max_tokens=None):
        self.last_usage = {"prompt_tokens": self._pt,
                           "completion_tokens": self._ct}
        yield "回复内容"


class _NoUsageFailLLM(LLMClient):
    last_usage = None

    def chat_stream(self, messages, max_tokens=None):
        raise RuntimeError("主渠道故障")
        yield


def _consume(resp):
    async def drive():
        events = []
        async for chunk in resp.body_iterator:
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events
    return asyncio.run(drive())


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ctxmeter_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        (self.tmp / "settings.toml").write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[commands."账本测试"]\nhandler = "declarative"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(self.tmp / "settings.toml")
        self.session_path = self.tmp / "session.json"
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {"2": {"date": TODAY, "units": [
                {"id": "A", "title": "测试单元", "status": "in_progress"}]}}},
            ensure_ascii=False), encoding="utf-8")
        from tests.test_flows import make_deps
        self.deps = make_deps(self.config, self.session_path)
        self.orch = ChatOrchestrator(self.config, self.deps.stages,
                                     self.deps.quiz, self.deps.state_store,
                                     self.deps.memory, self.deps.templates)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _init_routes(self, llm):
        self.deps.llm = llm
        self.deps.llm_cheap = llm
        self.deps.quiz.set_llm(llm)
        routes.init(self.deps, self.orch)

    def _load_session(self):
        return json.loads(self.session_path.read_text(encoding="utf-8"))


class TestExtractUsage(unittest.TestCase):
    def test_walks_wrapper_chain_to_serving_client(self):
        chain = FallbackClient(_NoUsageFailLLM(), _UsageLLM(100, 20))
        out = "".join(chain.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(out, "回复内容")
        u = extract_usage(chain)
        self.assertEqual(u, {"prompt_tokens": 100, "completion_tokens": 20})

    def test_mock_chain_returns_none(self):
        self.assertIsNone(extract_usage(MockLLM()))

    def test_fallback_stale_usage_never_anchored(self):
        """上轮 fallback 服务（有 usage），本轮主渠道成功但无 usage：
        不得锚定 fallback 的陈旧值（FallbackClient 每轮重置+镜像）。"""
        class _FlakyPrimary(LLMClient):
            last_usage = None  # 主渠道网关降级：永不记账

            def __init__(self):
                self.fail = True

            def chat_stream(self, messages, max_tokens=None):
                if self.fail:
                    raise RuntimeError("故障")
                yield "主渠道回复"

        primary = _FlakyPrimary()
        chain = FallbackClient(primary, _UsageLLM(100, 20))
        "".join(chain.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(extract_usage(chain),
                         {"prompt_tokens": 100, "completion_tokens": 20})
        primary.fail = False  # 本轮主渠道成功但无 usage
        "".join(chain.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertIsNone(extract_usage(chain))  # 不是陈旧的 {100,20}

    def test_observed_mirrors_inner_usage_per_turn(self):
        """ObservedLLM 把 inner 的 usage 镜像到自身（每轮重置）。"""
        from types import SimpleNamespace
        from backend.llm.observed import ObservedLLM
        observer = SimpleNamespace(log_llm=lambda *a, **k: None)
        chain = ObservedLLM(_UsageLLM(7, 8), observer, "test")
        "".join(chain.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(extract_usage(chain),
                         {"prompt_tokens": 7, "completion_tokens": 8})
        chain2 = ObservedLLM(MockLLM(), observer, "test")
        "".join(chain2.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertIsNone(extract_usage(chain2))


class TestCtxLedger(_Base):
    def test_measured_turn_persists_ledger(self):
        self._init_routes(_UsageLLM(1234, 56))
        _consume(routes.chat(routes.TextIn(text="你好")))
        s = self._load_session()
        self.assertEqual(s["ctx_prompt_tokens"], 1234)
        self.assertEqual(s["ctx_completion_tokens"], 56)
        self.assertTrue(s["ctx_measured"])
        # 校准系数随实测轮落盘（实测 prompt / 本地估算 prompt）
        self.assertGreater(s["ctx_calib"], 0)
        self.assertLess(s["ctx_calib"], 5)

    def test_degraded_turn_keeps_old_measured_values(self):
        self._init_routes(_UsageLLM(1234, 56))
        _consume(routes.chat(routes.TextIn(text="第一轮")))
        calib_after_m1 = self._load_session()["ctx_calib"]
        self._init_routes(MockLLM())  # 降级轮：无 usage
        _consume(routes.chat(routes.TextIn(text="第二轮")))
        s = self._load_session()
        self.assertFalse(s["ctx_measured"])
        self.assertEqual(s["ctx_prompt_tokens"], 1234)  # 旧实测值保留
        self.assertEqual(s["ctx_completion_tokens"], 56)
        self.assertEqual(s["ctx_calib"], calib_after_m1)  # 校准系数不被降级轮破坏

    def test_command_stream_records_ledger(self):
        """command 流（声明式指令走 LLM 回合）同样落上下文账本。"""
        self._init_routes(_UsageLLM(4321, 65))
        _consume(routes.command(routes.TextIn(text="[账本测试] 随便聊")))
        s = self._load_session()
        self.assertEqual(s["ctx_prompt_tokens"], 4321)
        self.assertEqual(s["ctx_completion_tokens"], 65)
        self.assertTrue(s["ctx_measured"])


class TestContextStatus(_Base):
    def test_calibrated_total_scales_with_estimate(self):
        """校准口径：total = 当前装配估算 × calib，只随会话内容变化。"""
        self._init_routes(MockLLM())
        seeded = SessionContext()
        seeded.chat_history.append({"role": "user", "content": "历史消息" * 50})
        self.deps.session_store.save(seeded)
        est_total = routes.context_status()["total"]  # calib=0 → 纯估算基准
        seeded.ctx_calib = 1.5
        seeded.ctx_prompt_tokens = 999999  # 旧实测原始值不得参与总量
        seeded.ctx_completion_tokens = 1
        seeded.ctx_measured = True
        self.deps.session_store.save(seeded)
        r = routes.context_status()
        self.assertEqual(r["source"], "calibrated")
        self.assertEqual(r["total"], round(est_total * 1.5))
        self.assertEqual(r["last_measured"], 1000000)  # 仅作参考透出
        layers = r["layers"]
        self.assertGreater(layers["pinned"], 0)
        # 分层按 calib 缩放：各层之和 ≈ 总量（±取整误差）
        self.assertAlmostEqual(
            layers["pinned"] + layers["archive"] + layers["window"],
            round(est_total * 1.5), delta=3)
        self.assertEqual(r["ratio"], round(round(est_total * 1.5) / r["budget"], 4))

    def test_display_stable_across_reads_and_restart(self):
        """稳定性契约：同一会话状态，重复读/重载 session 后显示完全一致。"""
        self._init_routes(MockLLM())
        seeded = SessionContext()
        seeded.chat_history.append({"role": "user", "content": "一些历史"})
        seeded.ctx_calib = 1.2
        self.deps.session_store.save(seeded)
        r1 = routes.context_status()
        r2 = routes.context_status()  # 刷新页面 = 再读一次
        self.assertEqual(r1["total"], r2["total"])
        # 模拟服务重启：从磁盘重载 session（calib 持久化不丢）
        reloaded = self.deps.session_store.load()
        self.assertEqual(reloaded.ctx_calib, 1.2)
        r3 = routes.context_status()
        self.assertEqual(r1["total"], r3["total"])

    def test_estimated_when_never_measured(self):
        self._init_routes(MockLLM())
        seeded = SessionContext()
        seeded.chat_history.append({"role": "user", "content": "一些历史"})
        self.deps.session_store.save(seeded)
        r = routes.context_status()
        self.assertEqual(r["source"], "estimated")
        layers = r["layers"]
        self.assertEqual(r["total"],
                         layers["pinned"] + layers["archive"] + layers["window"])
        self.assertGreater(r["total"], 0)
        self.assertGreater(r["budget"], 0)
        self.assertEqual(r["turns"], 1)
        self.assertEqual(r["archived_turns"], 0)

    def test_context_status_has_today(self):
        """M9：context-status 带今日 LLM 消耗（顶栏 tooltip 数据源）。"""
        self._init_routes(MockLLM())
        self.deps.session_store.save(SessionContext())
        r = routes.context_status()
        self.assertIn("today", r)
        self.assertIn("calls", r["today"])

    def test_usage_route_ws_param_and_days_clamp(self):
        """M9：/api/observability/usage 路由层——ws 透传与 days 钳制。"""
        self._init_routes(MockLLM())
        r = routes.observability_usage(days=7, ws="不存在的项目")
        self.assertEqual(r["totals"]["calls"], 0)  # 过滤后为空
        for key in ("kpi", "daily", "today", "by_workspace",
                    "by_model", "by_task", "workspaces"):
            self.assertIn(key, r)
        r2 = routes.observability_usage(days=99999, ws="")
        self.assertEqual(r2["days"], 365)  # 上限钳制


if __name__ == "__main__":
    unittest.main()
