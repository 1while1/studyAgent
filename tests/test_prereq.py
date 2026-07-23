"""先修诊断（M7 §4）测试：PrereqHandler + orchestrator PREREQ 分支 + 行为矩阵。

断言动作契约：代码强制选题（拓扑序）、出题机械校验（缺 cid 重试/fail-closed）、
评分机械校验（缺分重试一次/再缺取消不写证据）、prereq_pass/fail 证据落盘
（同日幂等）、矩阵对称（各态 fail_fast / day_review·end_day 拦截）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.enums import DayPhase
from backend.domain.models import SessionContext
from backend.engine.commands.day_review import DayReviewHandler
from backend.engine.commands.end_day import EndDayHandler
from backend.engine.commands.prereq import PrereqHandler
from backend.engine.orchestrator import ChatOrchestrator
from backend.llm.mock import MockLLM
from backend.services.config_service import ConfigService
from tests.test_flows import make_deps

TODAY = "2026-07-23"


class TestPrereq(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prereq_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'mastery_pass_score = 3.0\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\nquiz_wrong = -0.15\n'
            'prereq_pass = 0.40\nprereq_fail = -0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {
                "1": {"date": "2026-07-22", "units": [
                    {"id": "A", "title": "基础一", "status": "completed",
                     "rating": 4.0},
                    {"id": "B", "title": "基础二", "status": "completed",
                     "rating": 4.0},
                    {"id": "C", "title": "基础三", "status": "completed",
                     "rating": 4.0}]},
                "2": {"date": TODAY, "units": [
                    {"id": "A", "title": "进阶一", "status": "in_progress",
                     "rating": 0}]}}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "concepts.json").write_text(json.dumps({
            "schema_version": 1, "concepts": {
                "Day1-A": {"id": "Day1-A", "title": "基础一",
                           "prerequisites": [], "materials": [],
                           "code_refs": []},
                "Day1-B": {"id": "Day1-B", "title": "基础二",
                           "prerequisites": ["Day1-A"], "materials": [],
                           "code_refs": []},
                "Day1-C": {"id": "Day1-C", "title": "基础三",
                           "prerequisites": ["Day1-B"], "materials": [],
                           "code_refs": []},
                "Day2-A": {"id": "Day2-A", "title": "进阶一",
                           "prerequisites": ["Day1-C"], "materials": [],
                           "code_refs": []}}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "learner_model.json").write_text(json.dumps({
            "schema_version": 1, "concepts": {
                "Day1-A": {"title": "基础一", "mastery": 0.0,
                           "evidence": [{"type": "quiz_wrong", "delta": -0.15,
                                         "ts": TODAY, "source_ref": "t:1"}],
                           "last_review_day": 1, "review_due": []},
                "Day1-B": {"title": "基础二", "mastery": 0.0,
                           "evidence": [{"type": "quiz_wrong", "delta": -0.15,
                                         "ts": TODAY, "source_ref": "t:2"}],
                           "last_review_day": 1, "review_due": []}}},
            ensure_ascii=False), encoding="utf-8")
        self.deps = make_deps(self.config, self.tmp / "session.json")
        self.orch = ChatOrchestrator(
            self.config, self.deps.stages, self.deps.quiz,
            self.deps.state_store, self.deps.memory, self.deps.templates)
        self.session = SessionContext(day_phase=DayPhase.STUDYING.value,
                                      current_unit_id="A")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _script_llm(self, responses: list[str]):
        self.deps.llm = MockLLM(script=list(responses))

    def _model(self) -> dict:
        return json.loads(
            (self.docx / "learner_model.json").read_text(encoding="utf-8"))

    # ---- 选题与开场 ----

    def test_run_picks_topological_targets_and_sets_phase(self):
        self._script_llm(["【Day1-A】什么是A？\n\n【Day1-B】什么是B？\n\n【Day1-C】什么是C？"])
        result = PrereqHandler().run(self.deps, self.session, "")
        self.assertEqual(self.session.day_phase, DayPhase.PREREQ.value)
        cids = [q["cid"] for q in self.session.prereq_targets]
        self.assertEqual(cids, ["Day1-A", "Day1-B", "Day1-C"])  # 拓扑序根基先补
        self.assertIn("先修诊断开始", result.messages[0])
        self.assertIn("【Day1-A】", result.messages[0])
        self.assertEqual(self.session.prereq_retry, 0)

    def test_run_no_targets_no_opening(self):
        # 上游全达标：每节点 6×quiz_right + code_verify_pass = 0.8 ≥ 0.7
        def evs(cid):
            out = [{"type": "quiz_right", "delta": 0.10, "ts": TODAY,
                    "source_ref": f"t:{cid}:{i}"} for i in range(6)]
            out.append({"type": "code_verify_pass", "delta": 0.20,
                        "ts": TODAY, "source_ref": f"t:{cid}:v"})
            return out

        (self.docx / "learner_model.json").write_text(json.dumps(
            {"schema_version": 1, "concepts": {
                cid: {"title": cid, "mastery": 0.8, "evidence": evs(cid),
                      "last_review_day": 1, "review_due": []}
                for cid in ("Day1-A", "Day1-B", "Day1-C")}},
            ensure_ascii=False), encoding="utf-8")
        result = PrereqHandler().run(self.deps, self.session, "")
        self.assertIn("无需先修诊断", result.messages[0])
        self.assertEqual(self.session.day_phase, DayPhase.STUDYING.value)
        self.assertFalse(self.session.prereq_targets)

    def test_gen_retry_on_missing_cid(self):
        self._script_llm([
            "【Day1-A】什么是A？\n\n【Day1-B】什么是B？",  # 缺 Day1-C
            "【Day1-A】什么是A？\n\n【Day1-B】什么是B？\n\n【Day1-C】什么是C？"])
        result = PrereqHandler().run(self.deps, self.session, "")
        self.assertEqual(self.session.day_phase, DayPhase.PREREQ.value)
        self.assertEqual(len(self.session.prereq_targets), 3)
        self.assertIn("先修诊断开始", result.messages[0])

    def test_gen_fail_closed_after_two_misses(self):
        self._script_llm(["【Day1-A】什么是A？", "【Day1-A】什么是A？"])
        result = PrereqHandler().run(self.deps, self.session, "")
        self.assertIn("未开始", result.messages[0])
        self.assertEqual(self.session.day_phase, DayPhase.STUDYING.value)
        self.assertFalse(self.session.prereq_targets)

    def test_gen_fail_closed_on_missing_card(self):
        from unittest import mock
        with mock.patch("backend.engine.tool_registry.render_pedagogy",
                        return_value=""):
            result = PrereqHandler().run(self.deps, self.session, "")
        self.assertIn("未开始", result.messages[0])
        self.assertEqual(self.session.day_phase, DayPhase.STUDYING.value)

    # ---- 评分与证据 ----

    def _enter_diagnosis(self):
        self.session.day_phase = DayPhase.PREREQ.value
        self.session.prereq_targets = [
            {"cid": "Day1-A", "title": "基础一", "question": "什么是A？"},
            {"cid": "Day1-C", "title": "基础三", "question": "什么是C？"}]
        self.session.prereq_retry = 0

    def test_grading_writes_pass_and_fail_evidence(self):
        self._enter_diagnosis()
        instruction = self.orch.instruction_for(self.session, "A是甲，C不知道")
        self.assertIn("【Day1-A】", instruction)      # 目标清单注入
        self.assertIn("【评分：X.X】", instruction)   # 评分格式契约
        extras = self.orch.post_process(
            self.session,
            "点评略。\nDay1-A：【评分：4.0】\nDay1-C：【评分：2.0】")
        self.assertEqual(self.session.day_phase, DayPhase.STUDYING.value)
        self.assertEqual(self.session.prereq_targets, [])
        evs = {cid: [e["type"] for e in c["evidence"]]
               for cid, c in self._model()["concepts"].items()}
        self.assertIn("prereq_pass", evs["Day1-A"])   # 4.0 ≥ 3.0
        self.assertIn("prereq_fail", evs["Day1-C"])   # 2.0 < 3.0
        joined = "\n".join(extras)
        self.assertIn("先修诊断完成", joined)
        self.assertIn("已置初始掌握度", joined)

    def test_grading_idempotent_same_day(self):
        self._enter_diagnosis()
        self.orch.post_process(
            self.session, "Day1-A：【评分：4.0】\nDay1-C：【评分：2.0】")
        self._enter_diagnosis()  # 同日再来一场
        extras = self.orch.post_process(
            self.session, "Day1-A：【评分：4.5】\nDay1-C：【评分：1.5】")
        self.assertIn("今日已记录过（幂等跳过）", "\n".join(extras))
        # 证据不重复
        evs = self._model()["concepts"]["Day1-A"]["evidence"]
        self.assertEqual(len([e for e in evs if e["type"] == "prereq_pass"]), 1)

    def test_grading_missing_score_retry_then_success(self):
        self._enter_diagnosis()
        extras = self.orch.post_process(
            self.session, "Day1-A：【评分：4.0】")  # 缺 Day1-C
        self.assertEqual(self.session.prereq_retry, 1)
        self.assertEqual(self.session.day_phase, DayPhase.PREREQ.value)
        self.assertIn("缺少", "\n".join(extras))
        extras = self.orch.post_process(
            self.session, "Day1-A：【评分：4.0】\nDay1-C：【评分：2.0】")
        self.assertEqual(self.session.day_phase, DayPhase.STUDYING.value)
        self.assertIn("先修诊断完成", "\n".join(extras))

    def test_grading_two_misses_cancels_without_evidence(self):
        self._enter_diagnosis()
        self.orch.post_process(self.session, "全都不会。")
        self.assertEqual(self.session.prereq_retry, 1)
        extras = self.orch.post_process(self.session, "还是不会。")
        self.assertEqual(self.session.day_phase, DayPhase.STUDYING.value)
        self.assertIn("已取消本场诊断", "\n".join(extras))
        evs_a = self._model()["concepts"]["Day1-A"]["evidence"]
        self.assertNotIn("prereq_pass", [e["type"] for e in evs_a])

    # ---- 行为矩阵 ----

    def test_fail_fast_matrix(self):
        h = PrereqHandler()
        for phase, expect in [
                (DayPhase.PREREQ.value, "已在进行中"),
                (DayPhase.REVIEWING.value, "复盘进行中"),
                (DayPhase.ENDED.value, "已结束"),
                (DayPhase.NOT_STARTED.value, "尚未开始"),
                (DayPhase.INTERVIEW.value, "面试进行中")]:
            s = SessionContext(day_phase=phase)
            stop = h.fail_fast(self.deps, s, "")
            self.assertIsNotNone(stop, phase)
            self.assertIn(expect, stop)
        s = SessionContext(day_phase=DayPhase.STUDYING.value)
        self.assertIsNone(h.fail_fast(self.deps, s, ""))

    def test_day_review_and_end_day_block_prereq(self):
        s = SessionContext(day_phase=DayPhase.PREREQ.value)
        stop = DayReviewHandler().fail_fast(self.deps, s, "")
        self.assertIn("先修诊断", stop)
        stop = EndDayHandler().fail_fast(self.deps, s, "")
        self.assertIn("先修诊断", stop)

    def test_f3_commands_block_during_prereq_and_interview(self):
        """F3：next_content/sync/verify_code/code_mode/jump_day 相位拦截。"""
        from backend.engine.commands.code_mode import CodeModeHandler
        from backend.engine.commands.jump_day import JumpDayHandler
        from backend.engine.commands.next_content import NextContentHandler
        from backend.engine.commands.sync import SyncHandler
        from backend.engine.commands.verify_code import VerifyCodeHandler
        handlers = (NextContentHandler(), SyncHandler(), VerifyCodeHandler(),
                    CodeModeHandler(), JumpDayHandler())
        for phase, expect in ((DayPhase.PREREQ.value, "先修诊断"),
                              (DayPhase.INTERVIEW.value, "模拟面试")):
            s = SessionContext(day_phase=phase, current_unit_id="A")
            for h in handlers:
                args = "卡壳 x" if h.name == "sync" else ""
                stop = h.fail_fast(self.deps, s, args)
                self.assertIsNotNone(stop, f"{h.name}@{phase}")
                self.assertIn(expect, stop, h.name)

    def test_extract_scores_by_cid(self):
        from backend.engine.quiz_engine import QuizEngine
        text = "点评：\n**Day1-A**：【评分：4.0】\nDay1-B：【评分：99】\nDay1-C 不错"
        out = QuizEngine.extract_scores_by_cid(
            text, ["Day1-A", "Day1-B", "Day1-C"])
        self.assertEqual(out["Day1-A"], 4.0)
        self.assertIsNone(out["Day1-B"])  # 越界视为无标记（铁律 6）
        self.assertIsNone(out["Day1-C"])  # 缺失

    def test_extract_scores_no_prefix_stealing(self):
        """F2：短 cid 不得窃取长 cid 的评分行（Day5-A vs Day5-AA）。"""
        from backend.engine.quiz_engine import QuizEngine
        text = "Day5-AA：【评分：4.0】"
        out = QuizEngine.extract_scores_by_cid(text, ["Day5-A", "Day5-AA"])
        self.assertIsNone(out["Day5-A"])      # 不窃取
        self.assertEqual(out["Day5-AA"], 4.0)


if __name__ == "__main__":
    unittest.main()
