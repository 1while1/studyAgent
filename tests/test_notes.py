"""笔记条目层（services/notes_service + engine/note_actions）测试。"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.note_actions import resolve_note
from backend.services.config_service import ConfigService
from backend.services.learner_service import LearnerService
from backend.services.notes_service import NotesService
from backend.services.state_store import StateStore

TODAY = date.today().isoformat()


class NotesTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="notes_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\n'
            'note_distilled = 0.05\nquiz_right = 0.10\n'
            '[[stages]]\n'
            'name = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[workspaces]]\n'
            'slug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.svc = NotesService(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _notes(self) -> list[dict]:
        return json.loads(self.svc.path.read_text(encoding="utf-8"))["notes"]


class TestCrud(NotesTestBase):
    def test_add_and_filter(self):
        a = self.svc.add("stuck", "SSE 背压机制", concept_id="Day1-A", day=1)
        self.assertEqual(a["status"], "open")
        self.svc.add("insight", "RAG 核心是两段式", day=1)
        self.assertEqual(len(self.svc.list()), 2)
        self.assertEqual(len(self.svc.list(kind="stuck")), 1)
        self.assertEqual(len(self.svc.list(status="open")), 2)
        counts = self.svc.counts()
        self.assertEqual((counts["total"], counts["open"]), (2, 2))

    def test_add_rejects_bad_kind_and_empty(self):
        with self.assertRaises(ValueError):
            self.svc.add("unknown", "x")
        self.assertIsNone(self.svc.add("stuck", "  "))
        self.assertFalse(self.svc.path.exists())

    def test_source_ref_idempotent(self):
        a = self.svc.add("stuck", "内容", source_ref="Day1-A:sync:stuck:abc123")
        self.assertIsNotNone(a)
        b = self.svc.add("stuck", "内容", source_ref="Day1-A:sync:stuck:abc123")
        self.assertIsNone(b)
        self.assertEqual(len(self._notes()), 1)

    def test_update_text_and_attach_concept(self):
        a = self.svc.add("question", "原始问题", needs_review=True)
        n = self.svc.update(a["id"], text="澄清后的问题")
        self.assertEqual(n["text"], "澄清后的问题")
        self.assertTrue(n["needs_review"])
        n = self.svc.update(a["id"], concept_id="Day2-B")
        self.assertEqual(n["concept_id"], "Day2-B")
        self.assertFalse(n["needs_review"])  # 挂接后清除
        self.assertIsNone(self.svc.update("n-不存在", text="x"))

    def test_delete(self):
        a = self.svc.add("insight", "x")
        self.assertTrue(self.svc.delete(a["id"]))
        self.assertFalse(self.svc.delete(a["id"]))
        self.assertEqual(self._notes(), [])


class TestResolve(NotesTestBase):
    def _write_state(self, day: int = 2):
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": day, "last_active_date": TODAY, "days": {}},
            ensure_ascii=False), encoding="utf-8")

    def test_resolve_idempotent(self):
        a = self.svc.add("stuck", "卡点", day=1)
        n1 = self.svc.resolve(a["id"], day=2)
        self.assertEqual(n1["status"], "resolved")
        self.assertEqual(n1["resolved_day"], 2)
        n2 = self.svc.resolve(a["id"], day=3)  # 已销账不覆写
        self.assertEqual(n2["resolved_day"], 2)
        self.assertIsNone(self.svc.resolve("n-不存在"))

    def test_resolve_note_writes_evidence_once(self):
        """销账单一路径：notes resolved + note_distilled 证据（source_ref 幂等）。"""
        self._write_state(day=2)
        a = self.svc.add("stuck", "SSE 背压机制", concept_id="Day2-A")
        r = resolve_note(self.config, StateStore(self.config), a["id"])
        self.assertTrue(r["ok"])
        self.assertTrue(r["evidence"])
        model = json.loads(LearnerService(self.config)
                           .model_path.read_text(encoding="utf-8"))
        ev = model["concepts"]["Day2-A"]["evidence"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["type"], "note_distilled")
        self.assertEqual(ev[0]["source_ref"], f"note:{a['id']}")
        # 重复销账：条目仍 ok，证据不重复
        r2 = resolve_note(self.config, StateStore(self.config), a["id"])
        self.assertTrue(r2["ok"])
        self.assertFalse(r2["evidence"])
        model = json.loads(LearnerService(self.config)
                           .model_path.read_text(encoding="utf-8"))
        self.assertEqual(len(model["concepts"]["Day2-A"]["evidence"]), 1)

    def test_resolve_without_concept_no_evidence(self):
        self._write_state(day=2)
        a = self.svc.add("insight", "无挂接笔记")
        r = resolve_note(self.config, StateStore(self.config), a["id"])
        self.assertTrue(r["ok"])
        self.assertFalse(r["evidence"])
        self.assertFalse(LearnerService(self.config).model_path.exists())

    def test_resolve_missing_note(self):
        self._write_state()
        r = resolve_note(self.config, StateStore(self.config), "n-不存在")
        self.assertFalse(r["ok"])


class TestMerge(NotesTestBase):
    def test_merge(self):
        a = self.svc.add("stuck", "背压机制不懂")
        b = self.svc.add("stuck", "SSE 背压是什么")
        c = self.svc.add("stuck", "独立条目")
        keep = self.svc.merge(a["id"], [b["id"]])
        self.assertIn("背压机制不懂", keep["text"])
        self.assertIn("SSE 背压是什么", keep["text"])
        notes = {n["id"]: n for n in self._notes()}
        self.assertEqual(notes[b["id"]]["status"], "resolved")
        self.assertEqual(notes[b["id"]]["merged_into"], a["id"])
        self.assertEqual(notes[c["id"]]["status"], "open")
        # 重复合并不再吸收
        self.svc.merge(a["id"], [b["id"]])
        notes2 = {n["id"]: n for n in self._notes()}
        self.assertEqual(notes2[a["id"]]["text"].count("SSE 背压是什么"), 1)
        self.assertIsNone(self.svc.merge("n-不存在", [b["id"]]))


class TestDistill(NotesTestBase):
    MEM = ("## 2026-05-24\n\n### [同步] 记录\n"
           "- 已掌握：大模型核心概念\n"
           "- 卡壳：SSE 背压机制\n"
           "- 疑问：无\n"
           "- 代码完成：Day01 模块\n")

    def test_distill_basic_and_dedupe(self):
        added = self.svc.distill_from_text(1, self.MEM)
        self.assertEqual(added, 1)
        n = self._notes()[0]
        self.assertEqual(n["kind"], "stuck")
        self.assertEqual(n["text"], "SSE 背压机制")
        self.assertTrue(n["needs_review"])
        self.assertEqual(n["concept_id"], "")
        self.assertEqual(n["source_ref"], "memory:Day1:stuck:0")
        # 重复蒸馏不再新增
        self.assertEqual(self.svc.distill_from_text(1, self.MEM), 0)

    def test_distill_strips_pending_suffix(self):
        mem = "### [同步] 记录\n- 疑问：背压如何传导（待解答）\n"
        self.assertEqual(self.svc.distill_from_text(2, mem), 1)
        self.assertEqual(self._notes()[0]["text"], "背压如何传导")

    def test_distill_multi_items_and_live_sync_dedupe(self):
        # live sync 已写入同文条目 → 蒸馏跳过（子串去重）
        self.svc.add("stuck", "背压机制", concept_id="Day2-A")
        mem = "### [同步] 记录\n- 卡壳：背压机制、滑动窗口\n"
        added = self.svc.distill_from_text(2, mem)
        self.assertEqual(added, 1)  # 只有「滑动窗口」
        texts = [n["text"] for n in self._notes()]
        self.assertIn("滑动窗口", texts)

    def test_distill_empty_and_none(self):
        self.assertEqual(self.svc.distill_from_text(1, "- 卡壳：无\n"), 0)
        self.assertEqual(self.svc.distill_from_text(1, "- 卡壳：\n"), 0)
        self.assertFalse(self.svc.path.exists())


class TestSyncWiring(NotesTestBase):
    """[同步] handler 接线（M4）：已掌握/卡壳/疑问进条目层；话术走 QaService。"""

    def _deps(self):
        from tests.test_flows import make_deps
        (self.docx / "StudyMemory").mkdir(exist_ok=True)
        (self.docx / "StudyMemory" / "Day_02.md").write_text(
            "## 2026-07-23\n\n### 今日导学单元\n- [ ] 单元A：测试单元\n\n"
            "### [同步] 记录\n- 已掌握：无\n- 卡壳：无\n- 疑问：无\n- 代码完成：无\n\n"
            "### 掌握度评分（1-5分）\n- 单元A：0分\n\n"
            "### replica 进度\n- 待完成：X\n\n### AI 拷打评语\n- 无\n",
            encoding="utf-8")
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {"2": {"date": TODAY, "units": [
                {"id": "A", "title": "测试单元", "status": "in_progress"}],
                "sync_records": {"mastered": [], "stuck": [],
                                 "questions": [], "code_completed": []}}}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "Study.md").write_text(
            "# 计划\n\n当前天数：Day 2\n整体完成度：0%\n", encoding="utf-8")
        return make_deps(self.config, self.tmp / "session.json")

    def test_sync_stuck_writes_note_idempotent(self):
        from backend.domain.models import SessionContext
        from backend.engine.commands.sync import SyncHandler
        session = SessionContext()
        session.current_unit_id = "A"
        SyncHandler().run(self._deps(), session, "卡壳 SSE 背压机制")
        notes = self._notes()
        self.assertEqual(len(notes), 1)
        n = notes[0]
        self.assertEqual(n["kind"], "stuck")
        self.assertEqual(n["concept_id"], "Day2-A")
        self.assertFalse(n["needs_review"])
        self.assertTrue(n["source_ref"].startswith("Day2-A:sync:stuck:"))
        self.assertEqual(n["created_day"], 2)
        # 同文重复 [同步] 不产生重复条目
        SyncHandler().run(self._deps(), session, "卡壳 SSE 背压机制")
        self.assertEqual(len(self._notes()), 1)

    def test_sync_question_without_unit_needs_review(self):
        from backend.domain.models import SessionContext
        from backend.engine.commands.sync import SyncHandler
        session = SessionContext()
        SyncHandler().run(self._deps(), session, "疑问 背压如何传导")
        n = self._notes()[0]
        self.assertEqual(n["kind"], "question")
        self.assertEqual(n["concept_id"], "")
        self.assertTrue(n["needs_review"])

    def test_sync_qa_strips_placeholder(self):
        from backend.domain.models import SessionContext
        from backend.engine.commands.sync import SyncHandler
        from backend.services.qa_service import QaService
        (self.docx / "InterviewQA.md").write_text(
            "# 面试话术库\n\n> 说明\n\n（待产生）\n", encoding="utf-8")
        SyncHandler().run(self._deps(), SessionContext(), "面试话术 什么是RAG")
        md = (self.docx / "InterviewQA.md").read_text(encoding="utf-8")
        self.assertNotIn("（待产生）", md)
        entries = QaService(self.config).entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "什么是RAG")
        self.assertEqual(entries[0]["source"], "Day 2 [同步] 面试话术")


if __name__ == "__main__":
    unittest.main()
