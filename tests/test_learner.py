"""学习者模型（domain/learner + services/learner_service + 写入路径）测试。"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.learner import (compute_mastery, concept_id, is_due,
                                    review_interval)
from backend.services.config_service import ConfigService
from backend.services.learner_service import LearnerService

TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


class TestDomain(unittest.TestCase):
    def test_concept_id_cast(self):
        self.assertEqual(concept_id(2, "A"), "Day2-A")
        self.assertEqual(concept_id(10, "AA"), "Day10-AA")

    def test_mastery_decay_exact(self):
        ev = [{"type": "quiz_right", "delta": 0.1, "ts": TODAY.isoformat()}]
        m, unc, capped = compute_mastery(ev, TODAY, 14, 0.6)
        self.assertAlmostEqual(m, 0.1, places=6)
        self.assertFalse(capped)
        # 半衰期 14 天前 → 减半
        old = (TODAY - timedelta(days=14)).isoformat()
        m2, _, _ = compute_mastery([{**ev[0], "ts": old}], TODAY, 14, 0.6)
        self.assertAlmostEqual(m2, 0.05, places=6)

    def test_mastery_clamp_zero(self):
        ev = [{"type": "quiz_wrong", "delta": -0.15, "ts": TODAY.isoformat()}]
        m, _, _ = compute_mastery(ev, TODAY, 14, 0.6)
        self.assertEqual(m, 0.0)

    def test_cap_without_code_verify(self):
        ev = [{"type": "quiz_right", "delta": 0.8, "ts": TODAY.isoformat()}]
        m, unc, capped = compute_mastery(ev, TODAY, 14, 0.6)
        self.assertEqual((m, unc, capped), (0.6, 0.8, True))
        ev2 = ev + [{"type": "code_verify_pass", "delta": 0.2,
                     "ts": TODAY.isoformat()}]
        m2, _, capped2 = compute_mastery(ev2, TODAY, 14, 0.6)
        self.assertEqual(m2, 1.0)  # 0.8+0.2 封顶上限 1.0
        self.assertFalse(capped2)

    def test_review_interval(self):
        self.assertEqual(review_interval(0.39), 1)
        self.assertEqual(review_interval(0.4), 3)
        self.assertEqual(review_interval(0.69), 3)
        self.assertEqual(review_interval(0.7), 7)

    def test_is_due(self):
        self.assertTrue(is_due([2], 3))
        self.assertFalse(is_due([5], 3))
        self.assertFalse(is_due([], 3))


class LearnerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="learner_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'mastery_pass_score = 3.0\n'
            'model_half_life_days = 14\n'
            'mastery_cap_without_code = 0.6\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\n'
            'quiz_right = 0.10\nquiz_wrong = -0.15\n'
            'teach_back_pass = 0.25\nteach_back_fail = -0.20\n'
            'code_verify_pass = 0.20\ncode_verify_fail = -0.10\n'
            'sync_mastered = 0.10\nsync_stuck = -0.10\n'
            'note_distilled = 0.05\nmark_wrong = -0.05\n'
            '[[stages]]\n'
            'name = "teaching"\nnext = "scored"\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[stages]]\n'
            'name = "scored"\nnext = "completed"\n'
            'sop_step = "评分"\ninstruction = "评"\n'
            '[[stages]]\n'
            'name = "completed"\nnext = ""\n'
            'sop_step = "完成"\ninstruction = "完"\n'
            '[[workspaces]]\n'
            'slug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.svc = LearnerService(self.config)
        self.state = {
            "current_day": 2,
            "days": {
                "1": {"date": YESTERDAY, "units": [
                    {"id": "A", "title": "单元甲", "status": "completed",
                     "rating": 4.0},
                    {"id": "B", "title": "单元乙", "status": "completed",
                     "rating": 2.0}]},
                "2": {"date": TODAY.isoformat(), "units": [
                    {"id": "A", "title": "单元丙", "status": "in_progress"}]},
            }}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestConcepts(LearnerTestBase):
    def test_ensure_concepts_cast_and_chain(self):
        self.assertTrue(self.svc.ensure_concepts(self.state))
        data = json.loads(self.svc.concepts_path.read_text(encoding="utf-8"))
        cmap = data["concepts"]
        self.assertEqual(set(cmap), {"Day1-A", "Day1-B", "Day2-A"})
        self.assertEqual(cmap["Day1-B"]["prerequisites"], ["Day1-A"])
        self.assertEqual(cmap["Day2-A"]["prerequisites"], ["Day1-B"])  # 跨天链
        # 幂等：二次扫描无变化
        self.assertFalse(self.svc.ensure_concepts(self.state))

    def test_materials_merge(self):
        self.svc.ensure_concepts(self.state, {"Day1-A": ["docs/x"]})
        self.svc.ensure_concepts(self.state, {"Day1-A": ["docs/y"]})
        data = json.loads(self.svc.concepts_path.read_text(encoding="utf-8"))
        self.assertEqual(data["concepts"]["Day1-A"]["materials"],
                         ["docs/x", "docs/y"])


class TestEvidence(LearnerTestBase):
    def test_add_evidence_idempotent_and_due(self):
        self.assertTrue(self.svc.add_evidence(
            "Day1-A", "quiz_right", "Day1-A:quiz", 1))
        # 同 source_ref 再写 → 跳过
        self.assertFalse(self.svc.add_evidence(
            "Day1-A", "quiz_right", "Day1-A:quiz", 1))
        model = json.loads(self.svc.model_path.read_text(encoding="utf-8"))
        entry = model["concepts"]["Day1-A"]
        self.assertEqual(len(entry["evidence"]), 1)
        self.assertEqual(entry["evidence"][0]["delta"], 0.10)
        # mastery 0.1 < 0.4 → 间隔 1 天 → due = 2
        self.assertEqual(entry["review_due"], [2])

    def test_review_due_recomputed_on_write(self):
        self.svc.add_evidence("Day1-A", "quiz_right", "r1", 1)
        for i in range(8):
            self.svc.add_evidence("Day1-A", "sync_mastered", f"r{i + 2}", 1)
        model = json.loads(self.svc.model_path.read_text(encoding="utf-8"))
        entry = model["concepts"]["Day1-A"]
        # 9×0.1=0.9 但无 code_verify_pass 封顶 0.6 → 间隔按封顶值 3 天
        self.assertEqual(entry["mastery"], 0.6)
        self.assertEqual(entry["review_due"], [4])

    def test_unknown_type_rejected(self):
        self.assertFalse(self.svc.add_evidence("Day1-A", "no_such", "r", 1))

    def test_record_quiz_threshold(self):
        self.assertTrue(self.svc.record_quiz(1, "A", 4.0))
        self.assertTrue(self.svc.record_quiz(1, "B", 2.0))
        model = json.loads(self.svc.model_path.read_text(encoding="utf-8"))
        self.assertEqual(model["concepts"]["Day1-A"]["evidence"][0]["type"],
                         "quiz_right")
        self.assertEqual(model["concepts"]["Day1-B"]["evidence"][0]["type"],
                         "quiz_wrong")

    def test_record_sync_dedupe_and_none_unit(self):
        self.assertFalse(self.svc.record_sync(2, None, "sync_mastered"))
        self.assertTrue(self.svc.record_sync(2, "A", "sync_mastered"))
        self.assertFalse(self.svc.record_sync(2, "A", "sync_mastered"))  # 幂等

    def test_record_verify_daily_dedupe(self):
        self.assertTrue(self.svc.record_verify(2, "A", True))
        self.assertFalse(self.svc.record_verify(2, "A", True))  # 同日不再记

    def test_get_model_due_and_cap(self):
        self.svc.ensure_concepts(self.state)
        self.svc.add_evidence("Day1-A", "quiz_right", "q1", 1)
        # 首条后 mastery 0.1 → 间隔 1 → due=[2]，current_day=2 已到期
        model = self.svc.get_model(current_day=2)
        a = next(c for c in model["concepts"] if c["id"] == "Day1-A")
        self.assertEqual(a["mastery"], 0.1)
        self.assertTrue(a["due"])
        # 5×0.1=0.5 未触顶
        for i in range(4):
            self.svc.add_evidence("Day1-A", "quiz_right", f"q{i + 2}", 1)
        model = self.svc.get_model(current_day=2)
        a = next(c for c in model["concepts"] if c["id"] == "Day1-A")
        self.assertEqual(a["mastery"], 0.5)
        self.assertFalse(a["capped"])
        # +0.25 → uncapped 0.75 > 0.6，无 code_verify_pass 封顶 0.6
        self.assertTrue(self.svc.add_evidence("Day1-A", "teach_back_pass", "q6", 1))
        model = self.svc.get_model(current_day=2)
        a = next(c for c in model["concepts"] if c["id"] == "Day1-A")
        self.assertTrue(a["capped"])
        self.assertEqual(a["mastery"], 0.6)
        self.assertEqual(a["uncapped"], 0.75)


class TestMigration(LearnerTestBase):
    def test_preview_and_apply(self):
        memory = {1: "### [同步] 记录\n- 卡壳：SSE 背压机制\n- 疑问：无\n"}
        summary = self.svc.migrate_preview(self.state, memory)
        self.assertEqual((summary["quiz_scores"], summary["notes"]), (2, 1))
        r = self.svc.migrate_apply()
        self.assertTrue(r["ok"])
        self.assertEqual((r["concepts"], r["notes"]), (2, 1))
        model = json.loads(self.svc.model_path.read_text(encoding="utf-8"))
        ev = model["concepts"]["Day1-A"]["evidence"][0]
        self.assertEqual(ev["type"], "quiz_score")
        self.assertEqual(ev["delta"], 0.8)  # rating 4.0/5 映射初值
        self.assertEqual(ev["ts"], YESTERDAY)
        notes = json.loads(self.svc.notes_path.read_text(encoding="utf-8"))
        self.assertEqual(notes["notes"][0]["kind"], "stuck")
        self.assertEqual(notes["notes"][0]["status"], "open")
        self.assertTrue(notes["notes"][0]["needs_review"])
        # 幂等：模型已存在拒绝重复迁移
        r2 = self.svc.migrate_apply()
        self.assertFalse(r2["ok"])

    def test_apply_without_draft_rejected(self):
        r = self.svc.migrate_apply()
        self.assertFalse(r["ok"])


class TestWritePathWiring(LearnerTestBase):
    """handler 接线：sync / next_content 落盘后 evidence 真实写入。"""

    def _deps(self):
        from tests.test_flows import make_deps
        # StudyMemory Day_02 骨架（validate 要求的段与行齐全）
        (self.docx / "StudyMemory").mkdir(exist_ok=True)
        (self.docx / "StudyMemory" / "Day_02.md").write_text(
            "## 2026-07-23\n\n### 今日导学单元\n- [ ] 单元A：测试单元\n\n"
            "### [同步] 记录\n- 已掌握：无\n- 卡壳：无\n- 疑问：无\n- 代码完成：无\n\n"
            "### 掌握度评分（1-5分）\n- 单元A：0分\n\n"
            "### replica 进度\n- 待完成：X\n\n### AI 拷打评语\n- 无\n",
            encoding="utf-8")
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY.isoformat(),
            "days": {"2": {"date": TODAY.isoformat(), "units": [
                {"id": "A", "title": "测试单元", "status": "in_progress"}],
                "sync_records": {"mastered": [], "stuck": [],
                                 "questions": [], "code_completed": []}}}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "Study.md").write_text(
            "# 计划\n\n当前天数：Day 2\n整体完成度：0%\n", encoding="utf-8")
        return make_deps(self.config, self.tmp / "session.json")

    def test_sync_writes_evidence(self):
        from backend.domain.models import SessionContext
        from backend.engine.commands.sync import SyncHandler
        deps = self._deps()
        session = SessionContext()
        session.current_unit_id = "A"
        SyncHandler().run(deps, session, "已掌握 测试内容")
        self.assertTrue(self.svc.model_path.exists())
        model = json.loads(self.svc.model_path.read_text(encoding="utf-8"))
        ev = model["concepts"]["Day2-A"]["evidence"][0]
        self.assertEqual(ev["type"], "sync_mastered")
        self.assertEqual(ev["source_ref"], "Day2-A:sync:mastered")

    def test_next_content_advance_writes_quiz_evidence(self):
        from backend.domain.models import SessionContext
        from backend.engine.commands.next_content import NextContentHandler
        deps = self._deps()
        session = SessionContext()
        session.current_unit_id = "A"
        session.current_stage = "scored"
        session.pending_score = 4.0
        NextContentHandler()._persist_and_advance(deps, session, 4.0, False)
        model = json.loads(self.svc.model_path.read_text(encoding="utf-8"))
        ev = model["concepts"]["Day2-A"]["evidence"][0]
        self.assertEqual(ev["type"], "quiz_right")
        self.assertEqual(ev["source_ref"], "Day2-A:quiz")


if __name__ == "__main__":
    unittest.main()
