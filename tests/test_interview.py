"""模拟面试（M5c）测试：确定性选题 + 口述→追问→teach_back 证据落盘。

orchestrator 驱动方式同 test_flows：直接调 instruction_for/post_process
并喂合成 assistant 文本（评分契约【评分：X.X】），不断言自由文本。
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.enums import DayPhase
from backend.domain.models import SessionContext
from backend.engine.commands.interview import InterviewHandler
from backend.engine.commands.registry import CommandRegistry
from backend.engine.orchestrator import ChatOrchestrator
from backend.services.config_service import ConfigService

TODAY = date.today().isoformat()

_SETTINGS = (
    'active_workspace = "t"\n'
    'status_enum = ["not_started", "in_progress", "completed"]\n'
    '[evidence_delta]\nquiz_right = 0.10\nteach_back_pass = 0.25\n'
    'teach_back_fail = -0.20\n'
    '[[stages]]\nname = "teaching"\nnext = ""\n'
    'sop_step = "步骤一"\ninstruction = "讲"\n'
    '[commands."模拟面试"]\nhandler = "interview"\nsop_card = ""\n'
    '[[workspaces]]\nslug = "t"\n'
    'docx_dir = "{docx}"\n'
    'project_dir = "{tmp}"\n'
    'session_path = "{session}"\n'
)


class TestInterview(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="interview_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        (self.tmp / "settings.toml").write_text(_SETTINGS.format(
            docx=self.docx.as_posix(), tmp=self.tmp.as_posix(),
            session=(self.tmp / "session.json").as_posix()), encoding="utf-8")
        self.config = ConfigService(self.tmp / "settings.toml")
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {"2": {"date": TODAY, "units": [
                {"id": "A", "title": "单元A", "status": "in_progress"},
                {"id": "B", "title": "单元B", "status": "completed"}]}}},
            ensure_ascii=False), encoding="utf-8")
        ev = lambda ref: {"type": "quiz_right", "source_ref": ref,
                          "delta": 0.10, "ts": TODAY}
        (self.docx / "concepts.json").write_text(json.dumps({
            "schema_version": 1,
            "concepts": {"Day2-A": {"title": "单元A主题", "prerequisites": []},
                         "Day2-B": {"title": "单元B主题", "prerequisites": []}}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "learner_model.json").write_text(json.dumps({
            "schema_version": 1,
            "concepts": {
                "Day2-A": {"title": "单元A主题", "mastery": 0.2,
                           "evidence": [ev("a1"), ev("a2")],
                           "last_review_day": 2, "review_due": [3]},
                "Day2-B": {"title": "单元B主题", "mastery": 0.1,
                           "evidence": [ev("b1")],
                           "last_review_day": 2, "review_due": [3]}}},
            ensure_ascii=False), encoding="utf-8")
        from tests.test_flows import make_deps
        self.deps = make_deps(self.config, self.tmp / "session.json")
        self.orch = ChatOrchestrator(
            self.config, self.deps.stages, self.deps.quiz,
            self.deps.state_store, self.deps.memory, self.deps.templates)
        self.handler = InterviewHandler()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _model(self):
        return json.loads(
            (self.docx / "learner_model.json").read_text(encoding="utf-8"))

    def _start(self, args="", unit=None):
        session = self.deps.session_store.load()
        session.current_unit_id = unit
        result = self.handler.run(self.deps, session, args)
        return session, result

    # ---- 指令注册与选题 ----

    def test_command_registered(self):
        matched = CommandRegistry(self.config).match("[模拟面试]")
        self.assertIsNotNone(matched)

    def test_pick_by_args(self):
        session, result = self._start(args="Day2-A")
        self.assertEqual(session.interview_cid, "Day2-A")
        self.assertEqual(session.day_phase, DayPhase.INTERVIEW.value)
        self.assertEqual(session.interview_round, 0)
        self.assertIn("单元A主题", result.llm_instruction)

    def test_pick_current_unit(self):
        session, _ = self._start(unit="A")
        self.assertEqual(session.interview_cid, "Day2-A")

    def test_pick_weakest_evidenced(self):
        # 无 args 无当前单元 → 有证据中 mastery 最低（Day2-B 0.10 < A 0.20）
        session, _ = self._start()
        self.assertEqual(session.interview_cid, "Day2-B")

    def test_pick_no_match_shows_catalog(self):
        _, result = self._start(args="Day9-Z")
        self.assertIsNone(result.llm_instruction)
        self.assertIn("没找到指定知识点", result.messages[0])
        self.assertIn("Day2-A", result.messages[0])

    def test_pick_empty_model(self):
        (self.docx / "concepts.json").write_text(json.dumps(
            {"schema_version": 1, "concepts": {}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "learner_model.json").write_text(json.dumps(
            {"schema_version": 1, "concepts": {}},
            ensure_ascii=False), encoding="utf-8")
        _, result = self._start()
        self.assertIsNone(result.llm_instruction)
        self.assertIn("还没有可面试的知识点", result.messages[0])

    def test_fail_fast(self):
        session = SessionContext(day_phase=DayPhase.REVIEWING.value)
        self.assertIn("复盘", self.handler.fail_fast(
            self.deps, session, ""))
        session2 = SessionContext(day_phase=DayPhase.INTERVIEW.value)
        self.assertIn("进行中", self.handler.fail_fast(
            self.deps, session2, ""))
        # R3 矩阵：仅 STUDYING 可发起
        self.assertIsNone(self.handler.fail_fast(
            self.deps,
            SessionContext(day_phase=DayPhase.STUDYING.value), ""))
        ended = SessionContext(day_phase=DayPhase.ENDED.value)
        self.assertIn("已结束", self.handler.fail_fast(
            self.deps, ended, ""))
        not_started = SessionContext(day_phase=DayPhase.NOT_STARTED.value)
        self.assertIn("尚未开始", self.handler.fail_fast(
            self.deps, not_started, ""))

    def test_day_review_end_day_block_interview(self):
        """R3 矩阵：复盘/结束指令在 INTERVIEW 中拦截（不对称修复）。"""
        from backend.engine.commands.day_review import DayReviewHandler
        from backend.engine.commands.end_day import EndDayHandler
        session = SessionContext(day_phase=DayPhase.INTERVIEW.value)
        self.assertIn("面试", DayReviewHandler().fail_fast(
            self.deps, session, ""))
        self.assertIn("面试", EndDayHandler().fail_fast(
            self.deps, session, ""))

    def test_pending_score_untouched(self):
        """R4：面试口述分不污染 quiz pending_score。"""
        session, _ = self._start(args="Day2-A")
        session.pending_score = 4.0  # 模拟 quiz scored 待确认
        self._turn(session, "口述", "点评……【评分：2.5】")
        self.assertEqual(session.pending_score, 4.0)   # quiz 分未被覆盖
        self.assertEqual(session.interview_score, 2.5)

    def test_missing_card_fail_closed(self):
        """R7：策略卡缺失 → 不开空头面试（phase 不变）。"""
        import backend.services.config_service as cs
        from backend.engine import tool_registry
        empty = self.tmp / "empty_pedagogy"
        empty.mkdir()
        old = cs.PEDAGOGY_DIR
        cs.PEDAGOGY_DIR = empty
        try:
            session = self.deps.session_store.load()
            session.day_phase = DayPhase.STUDYING.value
            result = self.handler.run(self.deps, session, "Day2-A")
        finally:
            cs.PEDAGOGY_DIR = old
        self.assertIsNone(result.llm_instruction)
        self.assertIn("策略卡缺失", result.messages[0])
        self.assertNotEqual(session.day_phase, DayPhase.INTERVIEW.value)
        self.assertEqual(session.interview_cid, "")

    def test_idempotent_message(self):
        """R5：同日第二场面试文案区分「幂等跳过」而非「落盘失败」。"""
        session, _ = self._start(args="Day2-A")
        self._turn(session, "口述", "点评【评分：4.2】")
        self._turn(session, "答一", "点评+追问")
        self._turn(session, "答二", "总评【评分：4.3】")
        session2, _ = self._start(args="Day2-A")
        self._turn(session2, "口述", "点评【评分：4.5】")
        self._turn(session2, "答一", "点评+追问")
        _, extras = self._turn(session2, "答二", "总评【评分：4.6】")
        self.assertTrue(any("幂等跳过" in e for e in extras))
        self.assertFalse(any("落盘失败" in e for e in extras))

    # ---- 全流程：口述 → 追问 → teach_back 落盘 ----

    def _turn(self, session, user_text, assistant_text):
        instruction = self.orch.instruction_for(session, user_text)
        extras = self.orch.post_process(session, assistant_text)
        self.deps.session_store.save(session)
        return instruction, extras

    def test_full_flow_teach_back_pass(self):
        session, _ = self._start(args="Day2-A")
        # round 0：用户口述 → 四档评估指令 → 评分 → round 1
        instruction, _ = self._turn(session, "我讲讲 SSE 背压……",
                                    "四档点评……【评分：4.2】\n追问一")
        self.assertIn("四档", instruction)
        self.assertEqual(session.interview_round, 1)
        self.assertEqual(session.interview_score, 4.2)
        # round 1：追问策略指令 → round 2
        instruction, _ = self._turn(session, "背压回答一", "点评+追问二")
        self.assertIn("追问", instruction)
        self.assertEqual(session.interview_round, 2)
        # round 2：终评 → teach_back_pass 落盘 + phase 还原
        instruction, extras = self._turn(session, "背压回答二",
                                         "总评……【评分：4.3】")
        self.assertIn("最后一轮", instruction)
        self.assertEqual(session.day_phase, DayPhase.STUDYING.value)
        self.assertEqual(session.interview_cid, "")
        self.assertIsNone(session.interview_score)
        self.assertTrue(any("模拟面试结束" in e for e in extras))
        evs = self._model()["concepts"]["Day2-A"]["evidence"]
        tb = [e for e in evs if e["type"] == "teach_back_pass"]
        self.assertEqual(len(tb), 1)
        self.assertEqual(tb[0]["source_ref"],
                         f"interview:Day2-A:{TODAY}")
        self.assertAlmostEqual(tb[0]["delta"], 0.25)

    def test_full_flow_teach_back_fail(self):
        session, _ = self._start(args="Day2-B")
        self._turn(session, "我讲讲……", "点评……【评分：2.0】")
        self._turn(session, "回答一", "点评+追问")
        _, extras = self._turn(session, "回答二", "总评……【评分：2.0】")
        evs = self._model()["concepts"]["Day2-B"]["evidence"]
        tb = [e for e in evs if e["type"] == "teach_back_fail"]
        self.assertEqual(len(tb), 1)
        self.assertAlmostEqual(tb[0]["delta"], -0.20)
        self.assertTrue(any("未通过" in e for e in extras))

    def test_idempotent_same_day(self):
        """同日同 concept 第二场面试：source_ref 幂等不重复加证据。"""
        session, _ = self._start(args="Day2-A")
        self._turn(session, "口述", "点评【评分：4.2】")
        self._turn(session, "答一", "点评+追问")
        self._turn(session, "答二", "总评【评分：4.3】")
        n1 = len(self._model()["concepts"]["Day2-A"]["evidence"])
        session2, _ = self._start(args="Day2-A")  # 同日第二场
        self._turn(session2, "口述", "点评【评分：4.5】")
        self._turn(session2, "答一", "点评+追问")
        self._turn(session2, "答二", "总评【评分：4.6】")
        n2 = len(self._model()["concepts"]["Day2-A"]["evidence"])
        self.assertEqual(n1, n2)  # 幂等：无重复 teach_back

    def test_resume_mid_interview(self):
        """中断恢复：round 1 的 session 重载后按追问回合继续。"""
        session, _ = self._start(args="Day2-A")
        self._turn(session, "口述", "点评【评分：4.2】")
        # 模拟重开：从 store 重新加载
        reloaded = self.deps.session_store.load()
        self.assertEqual(reloaded.day_phase, DayPhase.INTERVIEW.value)
        self.assertEqual(reloaded.interview_round, 1)
        instruction = self.orch.instruction_for(reloaded, "继续")
        self.assertIn("追问", instruction)
        self.assertNotIn("最后一轮", instruction)

    def test_missing_score_not_advance(self):
        """round 0 无评分标记 → 不推进（评分契约铁律 6）。"""
        session, _ = self._start(args="Day2-A")
        _, extras = self._turn(session, "口述", "点评但没有评分标记")
        self.assertEqual(session.interview_round, 0)
        self.assertTrue(any("评分" in e for e in extras))


if __name__ == "__main__":
    unittest.main()
