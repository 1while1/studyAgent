"""拷打反喂话术（engine/qa_capture + 触发接线）测试。"""

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
from backend.engine.qa_capture import run_capture
from backend.llm.mock import MockLLM
from backend.services.config_service import ConfigService
from backend.services.qa_service import QaService
from tests.test_qa import ENTRY1

TODAY = date.today().isoformat()


class CaptureTestBase(unittest.TestCase):
    EXTRA_SETTINGS = ""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qacap_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'mastery_pass_score = 3.0\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            + self.EXTRA_SETTINGS +
            '[evidence_delta]\nquiz_right = 0.10\nquiz_wrong = -0.15\n'
            'note_distilled = 0.05\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        (self.docx / "StudyMemory" / "Day_02.md").write_text(
            "## 2026-07-23\n\n### 今日导学单元\n- [x] 单元A：测试单元\n\n"
            "### [同步] 记录\n- 已掌握：无\n- 卡壳：无\n- 疑问：无\n- 代码完成：无\n\n"
            "### 掌握度评分（1-5分）\n- 单元A：4分\n\n"
            "### replica 进度\n- 待完成：X\n\n### AI 拷打评语\n- 无\n",
            encoding="utf-8")
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 4,
            "last_active_date": TODAY,
            "days": {"2": {"date": TODAY, "units": [
                {"id": "A", "title": "测试单元", "status": "completed",
                 "rating": 4.0}],
                "sync_records": {"mastered": [], "stuck": [],
                                 "questions": [], "code_completed": []}}}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "Study.md").write_text(
            "# 计划\n\n当前天数：Day 2\n整体完成度：4%\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deps(self, script: list[str] | None = None):
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.tmp / "session.json")
        deps.llm = MockLLM(script=script if script is not None else [])
        return deps

    def _session_with_transcript(self) -> SessionContext:
        s = SessionContext()
        s.chat_history = [
            {"role": "user", "content": "讲完"},
            {"role": "assistant", "content": "Q1: 什么是 RAG？"},
            {"role": "user", "content": "检索加生成两段式"},
            {"role": "assistant", "content": "> 用户答：检索加生成两段式\n"
             "> 我的判断：[✅ 准确]\n【评分：4.0】"},
        ]
        s.review_msg_start = 0
        return s


class TestRunCapture(CaptureTestBase):
    def test_writes_entries_with_forced_source(self):
        deps = self._deps(script=[ENTRY1])
        msgs = run_capture(deps, self._session_with_transcript())
        self.assertEqual(len(msgs), 1)
        self.assertIn("什么是 RAG", msgs[0])
        entries = QaService(self.config).entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "Day 2 复盘拷打")  # 服务端覆写
        md = (self.docx / "InterviewQA.md").read_text(encoding="utf-8")
        self.assertNotIn("[同步] 面试话术", md)

    def test_garbage_output_silent(self):
        deps = self._deps(script=["随意输出", "还是不合规"])
        msgs = run_capture(deps, self._session_with_transcript())
        self.assertEqual(msgs, [])
        self.assertFalse((self.docx / "InterviewQA.md").exists())

    def test_retry_consumes_second_attempt(self):
        deps = self._deps(script=["不合规的输出", ENTRY1])
        msgs = run_capture(deps, self._session_with_transcript())
        self.assertEqual(len(msgs), 1)  # 第一次失败后重试成功

    def test_empty_transcript_noop(self):
        deps = self._deps(script=[ENTRY1])
        s = SessionContext()
        s.review_msg_start = 5  # 超出 history 长度
        self.assertEqual(run_capture(deps, s), [])
        self.assertEqual(len(deps.llm._script), 1)  # LLM 未被调用

    def test_duplicate_title_skipped(self):
        QaService(self.config).add_entry(ENTRY1)  # 已有同名条目
        deps = self._deps(script=[ENTRY1])
        msgs = run_capture(deps, self._session_with_transcript())
        self.assertEqual(msgs, [])
        self.assertEqual(len(QaService(self.config).entries()), 1)


class TestCaptureDisabled(CaptureTestBase):
    EXTRA_SETTINGS = 'qa_capture_enabled = false\n'

    def test_disabled_noop(self):
        deps = self._deps(script=[ENTRY1])
        msgs = run_capture(deps, self._session_with_transcript())
        self.assertEqual(msgs, [])
        self.assertEqual(len(deps.llm._script), 1)
        self.assertFalse((self.docx / "InterviewQA.md").exists())


class TestTriggerWiring(CaptureTestBase):
    def test_post_process_sets_pending_flag(self):
        from backend.engine.orchestrator import ChatOrchestrator
        deps = self._deps()
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        session = SessionContext()
        session.day_phase = DayPhase.REVIEWING.value
        extras = orch.post_process(session, "评分表……\n【评分：4.0】")
        self.assertTrue(session.pending_qa_capture)
        self.assertEqual(session.day_phase, DayPhase.STUDYING.value)
        self.assertTrue(any("4.0" in e for e in extras))
        state = json.loads((self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertTrue(state["days"]["2"]["review_completed"])
        self.assertEqual(state["days"]["2"]["review_score"], 4.0)

    def test_day_review_marks_transcript_start(self):
        from backend.engine.commands.day_review import DayReviewHandler
        deps = self._deps()
        session = SessionContext()
        session.chat_history = [{"role": "user", "content": "x"},
                                {"role": "assistant", "content": "y"},
                                {"role": "user", "content": "z"}]
        handler = DayReviewHandler()
        self.assertIsNone(handler.fail_fast(deps, session, ""))
        handler.run(deps, session, "")
        self.assertEqual(session.review_msg_start, 3)
        self.assertEqual(session.day_phase, DayPhase.REVIEWING.value)


if __name__ == "__main__":
    unittest.main()
