"""缺陷修复批回归测试：敏感文件过滤 / end_day 死循环 / jump_day / 原子写 / 评分范围。"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.quiz_engine import QuizEngine
from backend.services.backup_service import atomic_write
from backend.services.code_browser import CodeBrowser, CodeBrowserError
from backend.services.config_service import ConfigService


def _config(tmp: Path, extra_settings: str = "") -> ConfigService:
    docx = tmp / "docx"
    (docx / "StudyMemory").mkdir(parents=True, exist_ok=True)
    (docx / "StudyState.json").write_text(json.dumps({
        "current_day": 1, "overall_completion_percentage": 0,
        "days": {"1": {"date": "2026-07-22", "units": []}},
    }, ensure_ascii=False), encoding="utf-8")
    settings = tmp / "settings.toml"
    settings.write_text(
        f'docx_dir = "{docx.as_posix()}"\n'
        'active_workspace = "t"\n'
        '[[stages]]\nname = "teaching"\nnext = ""\n'
        '[[workspaces]]\nslug = "t"\ntitle = "t"\ntotal_days = 5\n'
        f'docx_dir = "{docx.as_posix()}"\n'
        f'project_dir = "{tmp.as_posix()}"\n'
        f'session_path = "{(tmp / "s.json").as_posix()}"\n' + extra_settings,
        encoding="utf-8")
    return ConfigService(settings)


class TestSensitiveFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sens_"))
        proj = self.tmp / "proj"
        proj.mkdir()
        (proj / ".env").write_text("SECRET=abc", encoding="utf-8")
        (proj / "server.pem").write_text("PEM", encoding="utf-8")
        (proj / "app.py").write_text("x = 1", encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(
            f'[[code_roots]]\nname = "proj"\npath = "{proj.as_posix()}"\n',
            encoding="utf-8")
        self.cb = CodeBrowser(ConfigService(settings))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_env_read_blocked(self):
        with self.assertRaises(CodeBrowserError):
            self.cb.read_file("proj", ".env")

    def test_pem_read_blocked(self):
        with self.assertRaises(CodeBrowserError):
            self.cb.read_file("proj", "server.pem")

    def test_normal_file_ok(self):
        self.assertEqual(self.cb.read_file("proj", "app.py")["content"], "x = 1")

    def test_index_excludes_sensitive(self):
        self.assertIsNone(self.cb.resolve(".env"))
        self.assertIsNotNone(self.cb.resolve("app.py"))


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aw_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_content_and_no_tmp_left(self):
        p = self.tmp / "x.toml"
        atomic_write(p, "a = 1\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "a = 1\n")
        self.assertFalse((self.tmp / "x.toml.tmp").exists())


class TestScoreRange(unittest.TestCase):
    def test_out_of_range_rejected(self):
        self.assertIsNone(QuizEngine.extract_score("【评分：99】"))
        self.assertIsNone(QuizEngine.extract_score("【评分：0.5】"))
        self.assertEqual(QuizEngine.extract_score("【评分：4.5】"), 4.5)


class TestEndDayZeroUnits(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="endd_"))
        self.config = _config(self.tmp)
        from backend.services.memory_store import MemoryStore
        from backend.services.state_store import StateStore
        mem = MemoryStore(self.config)
        # 当日 memory：全部单元未勾选
        mem.path_for(1).write_text(
            "## 2026-07-22\n\n### 今日导学单元\n- [ ] 单元A：X\n",
            encoding="utf-8")
        from backend.engine.commands.base import Deps
        from backend.services.study_plan import StudyPlanStore
        from backend.services.template_service import TemplateService
        from backend.services.backup_service import BackupService
        from backend.engine.session_store import SessionStore
        from backend.engine.stage_machine import StageMachine
        from backend.llm.mock import MockLLM
        from backend.engine.quiz_engine import QuizEngine
        from backend.engine.prompt_builder import PromptBuilder
        from backend.engine.hooks.pipeline import HookPipeline
        self.deps = Deps(
            config=self.config, state_store=StateStore(self.config),
            memory=mem, study_plan=StudyPlanStore(self.config),
            templates=TemplateService(self.config),
            backup=BackupService(self.config), stages=StageMachine(self.config),
            llm=MockLLM(), quiz=QuizEngine(self.config, MockLLM()),
            prompts=PromptBuilder(self.config, StateStore(self.config), mem,
                                  StageMachine(self.config)),
            hooks=HookPipeline(),
            session_store=SessionStore(self.tmp / "s.json"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_zero_units_confirm_breaks_dead_loop(self):
        from backend.engine.commands.end_day import EndDayHandler
        h = EndDayHandler()
        from backend.domain.models import SessionContext
        session = SessionContext()
        # 零完成单元：首次提示确认
        stop = h.fail_fast(self.deps, session, "")
        self.assertIsNotNone(stop)
        # 用户回「确定」→ 放行（修复前死循环）
        self.assertIsNone(h.fail_fast(self.deps, session, "确定"))


class TestJumpDay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jump_"))
        self.config = _config(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _handler_deps(self):
        from backend.engine.commands.base import Deps
        from backend.services.memory_store import MemoryStore
        from backend.services.state_store import StateStore
        from backend.services.study_plan import StudyPlanStore
        from backend.services.template_service import TemplateService
        from backend.services.backup_service import BackupService
        from backend.engine.session_store import SessionStore
        from backend.engine.stage_machine import StageMachine
        from backend.llm.mock import MockLLM
        from backend.engine.quiz_engine import QuizEngine
        from backend.engine.prompt_builder import PromptBuilder
        from backend.engine.hooks.pipeline import HookPipeline
        mem = MemoryStore(self.config)
        return Deps(
            config=self.config, state_store=StateStore(self.config),
            memory=mem, study_plan=StudyPlanStore(self.config),
            templates=TemplateService(self.config),
            backup=BackupService(self.config), stages=StageMachine(self.config),
            llm=MockLLM(), quiz=QuizEngine(self.config, MockLLM()),
            prompts=PromptBuilder(self.config, StateStore(self.config), mem,
                                  StageMachine(self.config)),
            hooks=HookPipeline(),
            session_store=SessionStore(self.tmp / "s.json"))

    def test_workspace_total_days_used(self):
        from backend.domain.models import SessionContext
        from backend.engine.commands.jump_day import JumpDayHandler
        deps = self._handler_deps()
        h = JumpDayHandler()
        # 工作区 total_days=5：Day 6 应被拒（修复前用全局 25 放行）
        stop = h.fail_fast(deps, SessionContext(), "Day 6")
        self.assertIn("1-5", stop)
        self.assertIsNone(h.fail_fast(deps, SessionContext(), "Day 5"))

    def test_run_without_number_no_crash(self):
        from backend.domain.models import SessionContext
        from backend.engine.commands.jump_day import JumpDayHandler
        deps = self._handler_deps()
        result = JumpDayHandler().run(deps, SessionContext(), "是")
        self.assertIn("未识别到天数", result.messages[0])


if __name__ == "__main__":
    unittest.main()
