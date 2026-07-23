"""上下文控制（M5b）测试：三层装配、预算钳制、压缩机械校验、两档路由。

覆盖：装配等价/窗口收缩/生效预算钳制/钉住摘要/机械校验/压缩降级/归档逐出/
50+ 轮不断片/fallback 链/SessionContext 兼容/create_llm_cheap/session reset/
llm-config context 保存热生效。
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
from backend.engine.context_manager import (ContextManager, effective_budget,
                                            validate_compression)
from backend.llm.base import LLMClient
from backend.llm.factory import create_llm_cheap
from backend.llm.mock import MockLLM
from backend.services.config_service import ConfigService

TODAY = date.today().isoformat()

_SETTINGS = (
    'active_workspace = "t"\n'
    'status_enum = ["not_started", "in_progress", "completed"]\n'
    '{context}'
    '{model_context}'
    '[evidence_delta]\nquiz_right = 0.10\n'
    '[[stages]]\nname = "teaching"\nnext = ""\n'
    'sop_step = "步骤一"\ninstruction = "讲"\n'
    '{llm}'
    '[[workspaces]]\nslug = "t"\n'
    'docx_dir = "{docx}"\n'
    'project_dir = "{tmp}"\n'
    'session_path = "{session}"\n'
)

_CTX_SMALL = ('[context]\nbudget_tokens = 1024\ntrigger_ratio = 0.8\n'
              'pin_top_k = 5\narchive_max_chars = 4000\nmax_messages = 200\n')
_CTX_DEFAULT = ''
_MODEL_CTX = '[model_context]\ndefault = 32768\n'
_LLM_MOCK = '[llm]\nprovider = "mock"\n'
_LLM_DEEPSEEK = ('[llm]\nprovider = "deepseek_official"\n'
                 '[llm.deepseek_official]\nmodel = "deepseek-chat"\n'
                 'max_tokens = 4096\n')

# 合法压缩输出（含 Day2-A、未决问题 0 条）
VALID_SUMMARY = ("【概念】Day2-A\n【未决问题】（共 0 条）\n"
                 "【要点】持续学习 Prompt 工程基础。")


class StubLLM(LLMClient):
    """按队列输出/抛错的 stub（记录调用）。"""

    def __init__(self, outputs=None, fail=False):
        self.outputs = list(outputs or [])
        self.fail = fail
        self.calls = []

    def chat_stream(self, messages, max_tokens=None):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("模拟 cheap 渠道故障")
        text = self.outputs.pop(0) if self.outputs else "（空输出）"
        yield text


class Base(unittest.TestCase):
    context_block = _CTX_SMALL
    llm_block = _LLM_MOCK

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ctxmgr_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        self._writes(["settings.toml"], self._settings_text())
        self.config = ConfigService(self.tmp / "settings.toml")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _settings_text(self):
        return _SETTINGS.format(
            context=self.context_block, model_context=_MODEL_CTX,
            llm=self.llm_block, docx=self.docx.as_posix(),
            tmp=self.tmp.as_posix(),
            session=(self.tmp / "session.json").as_posix())

    def _writes(self, names, text):
        (self.tmp / names[0]).write_text(text, encoding="utf-8")

    def _deps(self, llm=None, llm_cheap=None):
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.tmp / "session.json")
        deps.llm = llm or MockLLM()
        deps.llm_cheap = llm_cheap if llm_cheap is not None else deps.llm
        return deps

    def _write_state(self, day=2, units=None):
        units = units or [{"id": "A", "title": "单元A", "status": "in_progress"}]
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": day, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {str(day): {"date": TODAY, "units": units}}},
            ensure_ascii=False), encoding="utf-8")


def _msgs(pairs: int, chars: int, start: int = 0) -> list[dict]:
    out = []
    for i in range(start, start + pairs):
        out.append({"role": "user", "content": f"第{i}轮" + "问" * chars})
        out.append({"role": "assistant",
                    "content": f"答{i}（Day2-A）" + "讲" * chars})
    return out


class TestAssemble(Base):
    def test_small_history_all_in_window(self):
        """小历史（est 低于预算×0.8）→ 全量进窗，不触发压缩。"""
        cm = ContextManager(self._deps())
        session = SessionContext(chat_history=_msgs(2, 20))
        messages, plan = cm.assemble(session, "SYS")
        self.assertEqual(messages[0], {"role": "system", "content": "SYS"})
        self.assertEqual(len(messages), 1 + 4)  # system + 4 条历史
        self.assertFalse(plan["needs_compression"])

    def test_window_shrinks_within_budget(self):
        """大历史 → 窗口收缩：只留近期、est ≤ 预算、条数 < 全量。"""
        cm = ContextManager(self._deps())
        session = SessionContext(chat_history=_msgs(10, 300))
        messages, plan = cm.assemble(session, "SYS")
        window = messages[1:]
        self.assertLess(len(window), 20)
        self.assertGreaterEqual(len(window), 1)
        self.assertLessEqual(cm._est_messages(window), 1024)
        # 保留的是最近的轮次（低水位下窗口可能只剩最新一条）
        self.assertIn("答9", window[-1]["content"])
        self.assertTrue(plan["needs_compression"])
        self.assertEqual(plan["compress_from"], 0)
        self.assertEqual(plan["compress_upto"], 20 - len(window))

    def test_archive_note_injected_as_system(self):
        cm = ContextManager(self._deps())
        session = SessionContext(chat_history=_msgs(1, 10),
                                 archive_summary="【概念】Day1-A\n旧摘要")
        messages, _ = cm.assemble(session, "SYS")
        self.assertEqual(messages[1]["role"], "system")
        self.assertIn("旧摘要", messages[1]["content"])

    def test_archive_upto_out_of_range_defensive(self):
        cm = ContextManager(self._deps())
        session = SessionContext(chat_history=_msgs(1, 10), archive_upto=99)
        messages, plan = cm.assemble(session, "SYS")
        self.assertEqual(len(messages), 1 + 2)  # 钳 0 后全量
        self.assertFalse(plan["needs_compression"])


class TestEffectiveBudget(Base):
    def test_user_budget_governs_when_below_limit(self):
        # budget 1024，模型上限 32768-4096 → min=1024（再经下限钳制仍 1024）
        self.assertEqual(effective_budget(self.config), 1024)

    def test_model_limit_governs_when_below_budget(self):
        self._writes(["settings.toml"], _SETTINGS.format(
            context='[context]\nbudget_tokens = 256000\n',
            model_context='[model_context]\ndefault = 32768\n'
                          'deepseek-chat = 10000\n',
            llm=_LLM_DEEPSEEK, docx=self.docx.as_posix(),
            tmp=self.tmp.as_posix(),
            session=(self.tmp / "s.json").as_posix()))
        cfg = ConfigService(self.tmp / "settings.toml")
        # min(256000, 10000-4096) = 5904
        self.assertEqual(effective_budget(cfg), 5904)

    def test_unknown_model_falls_back_to_default(self):
        self._writes(["settings.toml"], _SETTINGS.format(
            context='[context]\nbudget_tokens = 256000\n',
            model_context='[model_context]\ndefault = 32768\n',
            llm='[llm]\nprovider = "x"\n[llm.x]\nmodel = "unknown-xyz"\n'
                'max_tokens = 4096\n',
            docx=self.docx.as_posix(), tmp=self.tmp.as_posix(),
            session=(self.tmp / "s.json").as_posix()))
        cfg = ConfigService(self.tmp / "settings.toml")
        # min(256000, 32768-4096) = 28672
        self.assertEqual(effective_budget(cfg), 28672)

    def test_floor_1024(self):
        self._writes(["settings.toml"], _SETTINGS.format(
            context='[context]\nbudget_tokens = 100\n',
            model_context=_MODEL_CTX, llm=_LLM_MOCK,
            docx=self.docx.as_posix(), tmp=self.tmp.as_posix(),
            session=(self.tmp / "s.json").as_posix()))
        cfg = ConfigService(self.tmp / "settings.toml")
        self.assertEqual(effective_budget(cfg), 1024)


class TestLearnerSummary(Base):
    def _write_learner(self):
        (self.docx / "concepts.json").write_text(json.dumps({
            "schema_version": 1,
            "concepts": {"Day2-A": {"title": "单元A", "prerequisites": []},
                         "Day2-B": {"title": "单元B", "prerequisites": []}}},
            ensure_ascii=False), encoding="utf-8")
        ev = lambda ref, d: {"type": "quiz_right", "source_ref": ref,
                             "delta": d, "ts": TODAY}
        (self.docx / "learner_model.json").write_text(json.dumps({
            "schema_version": 1,
            "concepts": {
                "Day2-A": {"title": "单元A", "mastery": 0.1,
                           "evidence": [ev("a", 0.10)],
                           "last_review_day": 2, "review_due": [3]},
                "Day2-B": {"title": "单元B", "mastery": 0.2,
                           "evidence": [ev("b1", 0.10), ev("b2", 0.10)],
                           "last_review_day": 2, "review_due": [3]}}},
            ensure_ascii=False), encoding="utf-8")

    def test_render_topk_and_current_unit(self):
        self._write_state()
        self._write_learner()
        cm = ContextManager(self._deps())
        session = SessionContext(current_unit_id="A")
        summary = cm.learner_summary(session)
        self.assertIn("Day2-A", summary)
        self.assertIn("Day2-B", summary)
        # mastery 升序：A(0.10) 在 B(0.20) 前；当前单元标记
        self.assertLess(summary.index("Day2-A"), summary.index("Day2-B"))
        a_line = [l for l in summary.splitlines() if "Day2-A" in l][0]
        self.assertIn("（当前单元）", a_line)
        self.assertIn("薄弱", summary)

    def test_empty_when_no_model(self):
        cm = ContextManager(self._deps())
        self.assertEqual(cm.learner_summary(SessionContext()), "")

    def test_topk_zero_evidence_sinks(self):
        """R4：零证据 concept（未学单元）沉底并标「未学」，不挤占薄弱项。"""
        self._write_state()
        ev = lambda ref: {"type": "quiz_right", "source_ref": ref,
                          "delta": 0.10, "ts": TODAY}
        concepts = {"Day2-A": {"title": "单元A", "prerequisites": []},
                    "Day2-B": {"title": "单元B", "prerequisites": []}}
        model_concepts = {
            "Day2-A": {"title": "单元A", "mastery": 0.1,
                       "evidence": [ev("a")], "last_review_day": 2,
                       "review_due": [3]},
            "Day2-B": {"title": "单元B", "mastery": 0.2,
                       "evidence": [ev("b1"), ev("b2")],
                       "last_review_day": 2, "review_due": [3]}}
        for i in range(1, 6):  # 5 个零证据未学单元
            cid = f"Day3-{chr(64 + i)}"
            concepts[cid] = {"title": f"未学{i}", "prerequisites": []}
        (self.docx / "concepts.json").write_text(json.dumps(
            {"schema_version": 1, "concepts": concepts},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "learner_model.json").write_text(json.dumps(
            {"schema_version": 1, "concepts": model_concepts},
            ensure_ascii=False), encoding="utf-8")
        cm = ContextManager(self._deps())
        summary = cm.learner_summary(SessionContext(current_unit_id="A"))
        lines = summary.splitlines()
        # 有证据的 A(0.1)、B(0.2) 排最前；零证据沉底且标「未学」
        self.assertIn("Day2-A", lines[0])
        self.assertIn("Day2-B", lines[1])
        self.assertLess(summary.index("Day2-B"), summary.index("Day3-A"))
        self.assertIn("未学", summary)
        self.assertIn("薄弱", lines[0])


class TestValidateCompression(unittest.TestCase):
    def test_missing_id_rejected(self):
        reason = validate_compression({"Day2-A", "Day2-B"}, 0,
                                      "【概念】Day2-A\n【未决问题】（共 0 条）")
        self.assertIsNotNone(reason)
        self.assertIn("Day2-B", reason)

    def test_wrong_question_count_rejected(self):
        out = "【概念】Day2-A\n【未决问题】（共 1 条）\n1. 啥？"
        reason = validate_compression({"Day2-A"}, 0, out)
        self.assertIsNotNone(reason)
        self.assertIn("计数", reason)

    def test_valid_passes(self):
        self.assertIsNone(validate_compression(
            {"Day2-A"}, 0, VALID_SUMMARY))
        self.assertIsNone(validate_compression(set(), 0, VALID_SUMMARY))


class TestCompress(Base):
    def _session_with_turns(self, n=4):
        return SessionContext(chat_history=_msgs(n, 50))

    def _plan(self, session, upto=None):
        return {"needs_compression": True, "compress_from": 0,
                "compress_upto": upto if upto is not None
                else len(session.chat_history)}

    def test_success_writes_archive(self):
        stub = StubLLM(outputs=[VALID_SUMMARY])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        cm = ContextManager(deps)
        session = self._session_with_turns()
        cm.maybe_compress(session, self._plan(session, 4))
        self.assertEqual(session.archive_summary, VALID_SUMMARY)
        self.assertEqual(session.archive_upto, 4)
        self.assertEqual(len(stub.calls), 1)

    def test_degrade_after_two_bad_outputs(self):
        stub = StubLLM(outputs=["坏输出一", "坏输出二"])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        cm = ContextManager(deps)
        session = self._session_with_turns()
        cm.maybe_compress(session, self._plan(session, 4))
        self.assertEqual(session.archive_summary, "")   # 原样保留
        self.assertEqual(session.archive_upto, 0)
        self.assertEqual(len(session.chat_history), 8)  # 不丢数据
        self.assertEqual(len(stub.calls), 2)            # 重试一次后放弃
        self.assertEqual(session.compress_cooldown, 3)  # R2：失败写冷却

    def test_cooldown_blocks_retry_storm(self):
        """R2：冷却期内跳过不再烧 token，期满重试。"""
        stub = StubLLM(outputs=["坏输出一", "坏输出二"])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        cm = ContextManager(deps)
        session = self._session_with_turns()
        plan = self._plan(session, 4)
        cm.maybe_compress(session, plan)
        self.assertEqual(session.compress_cooldown, 3)
        self.assertEqual(len(stub.calls), 2)
        for expected in (2, 1, 0):
            cm.maybe_compress(session, plan)
            self.assertEqual(session.compress_cooldown, expected)
        self.assertEqual(len(stub.calls), 2)  # 冷却期内未再调用
        cm.maybe_compress(session, plan)       # 期满重试（输出耗尽仍失败）
        self.assertGreater(len(stub.calls), 2)
        self.assertEqual(session.compress_cooldown, 3)

    def test_hysteresis_after_compress(self):
        """R2 低水位滞回：压缩成功后候选区低于触发线，下轮不再触发。"""
        stub = StubLLM(outputs=[VALID_SUMMARY])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        cm = ContextManager(deps)
        session = SessionContext(chat_history=_msgs(10, 300))
        _, plan = cm.assemble(session, "SYS")
        self.assertTrue(plan["needs_compression"])
        cm.maybe_compress(session, plan)
        self.assertGreater(session.archive_upto, 0)
        _, plan2 = cm.assemble(session, "SYS")
        self.assertFalse(plan2["needs_compression"])

    def test_pinned_deduction_shrinks_window(self):
        """R3：钉住层预扣——大 system 压低可用预算，窗口更窄。"""
        cm = ContextManager(self._deps())
        session = SessionContext(chat_history=_msgs(6, 60))
        msgs_small, _ = cm.assemble(session, "短")
        msgs_big, plan_big = cm.assemble(session, "钉" * 2000)
        self.assertLess(len(msgs_big), len(msgs_small))
        self.assertTrue(plan_big["needs_compression"])

    def test_llm_failure_silent(self):
        stub = StubLLM(fail=True)
        deps = self._deps(llm=StubLLM(fail=True), llm_cheap=stub)
        cm = ContextManager(deps)
        session = self._session_with_turns()
        cm.maybe_compress(session, self._plan(session, 4))
        self.assertEqual(session.archive_upto, 0)

    def test_fallback_to_strong(self):
        cheap = StubLLM(fail=True)
        strong = StubLLM(outputs=[VALID_SUMMARY])
        deps = self._deps(llm=strong, llm_cheap=cheap)
        cm = ContextManager(deps)
        session = self._session_with_turns()
        cm.maybe_compress(session, self._plan(session, 4))
        self.assertEqual(len(cheap.calls), 1)
        self.assertEqual(len(strong.calls), 1)  # cheap 失败 → strong 接手
        self.assertEqual(session.archive_upto, 4)

    def test_question_count_carryover(self):
        """旧摘要 1 条未决 + 新 turns 1 条疑问 → 上界 2；超限拒、以内过（R1）。"""
        old = ("【概念】Day2-A\n【未决问题】（共 1 条）\n1. 旧疑问\n【要点】旧")
        session = SessionContext(
            chat_history=[{"role": "user", "content": "新疑问是什么？"},
                          {"role": "assistant", "content": "解答（Day2-A）"}],
            archive_summary=old)
        # 声明 3 条（> 上界 2）→ 拒；声明 2 条 → 过
        over = ("【概念】Day2-A\n【未决问题】（共 3 条）\n1. a\n2. b\n3. c\n"
                "【要点】x")
        good = ("【概念】Day2-A\n【未决问题】（共 2 条）\n1. 旧疑问\n"
                "2. 新疑问\n【要点】x")
        stub = StubLLM(outputs=[over, good])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        cm = ContextManager(deps)
        cm.maybe_compress(session, {"needs_compression": True,
                                    "compress_from": 0, "compress_upto": 2})
        self.assertEqual(len(stub.calls), 2)  # 第一次超限被拒，重试通过
        self.assertEqual(session.archive_summary, good)

    def test_under_count_passes(self):
        """R1 防增不防减：模型判定疑问已解决（声明 < 上界）→ 通过。"""
        session = SessionContext(
            chat_history=[{"role": "user", "content": "这个怎么理解？"},
                          {"role": "assistant", "content": "已讲透（Day2-A）"}])
        resolved = ("【概念】Day2-A\n【未决问题】（共 0 条）\n"
                    "【要点】疑问已解答。")
        stub = StubLLM(outputs=[resolved])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        cm = ContextManager(deps)
        cm.maybe_compress(session, {"needs_compression": True,
                                    "compress_from": 0, "compress_upto": 2})
        self.assertEqual(session.archive_summary, resolved)
        self.assertEqual(session.archive_upto, 2)

    def test_eviction_when_over_limit(self):
        long_valid = ("【概念】Day2-A\n【未决问题】（共 0 条）\n"
                      "【要点】" + "长" * 200)
        self._writes(["settings.toml"], _SETTINGS.format(
            context=('[context]\nbudget_tokens = 1024\ntrigger_ratio = 0.8\n'
                     'archive_max_chars = 80\n'),
            model_context=_MODEL_CTX, llm=_LLM_MOCK,
            docx=self.docx.as_posix(), tmp=self.tmp.as_posix(),
            session=(self.tmp / "session.json").as_posix()))
        config = ConfigService(self.tmp / "settings.toml")
        from tests.test_flows import make_deps
        deps = make_deps(config, self.tmp / "session.json")
        deps.llm = MockLLM()
        deps.llm_cheap = StubLLM(outputs=[long_valid])
        cm = ContextManager(deps)
        session = self._session_with_turns()
        cm.maybe_compress(session, self._plan(session, 4))
        self.assertTrue(session.archive_summary.startswith("…（更早内容已逐出）"))
        self.assertLessEqual(len(session.archive_summary), 80 + 20)

    def test_50_rounds_no_break(self):
        """50+ 轮不断片：每轮装配 est ≤ 预算、archive_upto 单调、无异常。"""
        stub = StubLLM(outputs=[VALID_SUMMARY] * 200)
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        cm = ContextManager(deps)
        session = SessionContext()
        last_upto = 0
        for i in range(55):
            session.chat_history += _msgs(1, 100, start=i)
            messages, plan = cm.assemble(session, "SYS")
            window = [m for m in messages[1:] if m["role"] != "system"]
            self.assertLessEqual(cm._est_messages(window), 1024)
            self.assertLessEqual(len(window), 200)
            cm.maybe_compress(session, plan)
            self.assertGreaterEqual(session.archive_upto, last_upto)
            last_upto = session.archive_upto
        self.assertGreater(session.archive_upto, 0)
        self.assertIn("Day2-A", session.archive_summary)


class TestMisc(Base):
    def test_session_fields_roundtrip_and_compat(self):
        s = SessionContext(archive_summary="x", archive_upto=3)
        s2 = SessionContext.from_dict(s.to_dict())
        self.assertEqual((s2.archive_summary, s2.archive_upto), ("x", 3))
        old = SessionContext.from_dict({"day_phase": "not_started"})
        self.assertEqual((old.archive_summary, old.archive_upto), ("", 0))

    def test_create_llm_cheap(self):
        self.assertIsNone(create_llm_cheap(self.config))  # 未配置 → None
        self._writes(["settings.toml"], _SETTINGS.format(
            context=_CTX_SMALL, model_context=_MODEL_CTX,
            llm='[llm]\nprovider = "mock"\ncheap_provider = "mock"\n',
            docx=self.docx.as_posix(), tmp=self.tmp.as_posix(),
            session=(self.tmp / "s.json").as_posix()))
        cfg = ConfigService(self.tmp / "settings.toml")
        self.assertIsInstance(create_llm_cheap(cfg), MockLLM)


class TestSessionReset(Base):
    def test_reset_clears_archive(self):
        deps = self._deps()
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        deps.session_store.save(SessionContext(
            chat_history=_msgs(2, 10), archive_summary="旧摘要",
            archive_upto=3))
        result = routes.reset_session()
        self.assertEqual(result["cleared"], 4)
        saved = json.loads(
            (self.tmp / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["archive_summary"], "")
        self.assertEqual(saved["archive_upto"], 0)


class TestChatFailureKeepsArchive(Base):
    def test_llm_failure_keeps_archive(self):
        """LLM 失败路径不触碰归档字段（读代码确认安全 → 测试锁定）。"""
        deps = self._deps(llm=StubLLM(fail=True),
                          llm_cheap=StubLLM(fail=True))
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        deps.session_store.save(SessionContext(
            chat_history=_msgs(2, 10), archive_summary="旧摘要",
            archive_upto=3))
        resp = routes.chat(routes.TextIn(text="你好"))

        async def drive():
            chunks = []
            async for chunk in resp.body_iterator:
                chunks.append(chunk)
            return chunks
        text = "".join(asyncio.run(drive()))
        self.assertIn("error", text)
        saved = json.loads(
            (self.tmp / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["archive_summary"], "旧摘要")
        self.assertEqual(saved["archive_upto"], 3)
        # 用户消息仍落盘（前后端历史不分叉）
        self.assertTrue(any(m["role"] == "user" and "你好" in m["content"]
                            for m in saved["chat_history"]))


class TestLlmConfigContext(Base):
    # llm-config 保存会重写全部 provider 节区 → 夹具需预置这些节区
    llm_block = ('[llm]\nprovider = "mock"\n'
                 '[llm.openai_compat]\nmodel = "deepseek-v4-pro"\n'
                 'max_tokens = 4096\ntemperature = 0.7\n'
                 'api_key_env = "LLM_API_KEY"\n'
                 '[llm.deepseek_official]\nmodel = "deepseek-chat"\n'
                 'max_tokens = 4096\ntemperature = 0.7\n'
                 'api_key_env = "LLM_API_KEY_DEEPSEEK"\n')
    def test_save_context_keys_merge_and_hot_reload(self):
        deps = self._deps()
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        # 预置 [context] 其他键，验证合并不丢
        text = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        text = text.replace("pin_top_k = 5", "pin_top_k = 7")
        (self.tmp / "settings.toml").write_text(text, encoding="utf-8")
        deps.config.reload()
        old_path = routes.SETTINGS_PATH
        routes.SETTINGS_PATH = self.tmp / "settings.toml"
        try:
            body = routes.LlmConfigIn(provider="mock",
                                      context_budget_tokens=128000,
                                      context_trigger_ratio=0.75)
            result = routes.save_llm_config(body)
        finally:
            routes.SETTINGS_PATH = old_path
        self.assertTrue(result["ok"], result.get("error"))
        saved = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        self.assertIn("budget_tokens = 128000", saved)
        self.assertIn("trigger_ratio = 0.75", saved)
        self.assertIn("pin_top_k = 7", saved)  # 既有键未丢
        view = result["config"]["context"]
        self.assertEqual(view["budget_tokens"], 128000)
        # mock 渠道无模型节区 → default 上限 32768 - 4096 预留 = 28672
        self.assertEqual(view["effective_budget"], 28672)

    def test_save_preserves_section_comments(self):
        """config_writer 保留节区内独立注释行（防 UI 保存吞注释）。"""
        deps = self._deps()
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        text = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        text = text.replace("max_messages = 200",
                            "max_messages = 200\n# 模型上限表见下节")
        (self.tmp / "settings.toml").write_text(text, encoding="utf-8")
        deps.config.reload()
        old_path = routes.SETTINGS_PATH
        routes.SETTINGS_PATH = self.tmp / "settings.toml"
        try:
            body = routes.LlmConfigIn(provider="mock",
                                      context_budget_tokens=128000)
            result = routes.save_llm_config(body)
        finally:
            routes.SETTINGS_PATH = old_path
        self.assertTrue(result["ok"], result.get("error"))
        saved = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        self.assertIn("# 模型上限表见下节", saved)  # 注释未被吞


if __name__ == "__main__":
    unittest.main()
