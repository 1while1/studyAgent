"""bug 修复回归测试：评分正则变体 / 重新开始保留记录 / 指令别名 / unit_open 时长渲染。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.commands.registry import CommandRegistry
from backend.engine.commands.start_day import StartDayHandler
from backend.engine.quiz_engine import QuizEngine
from backend.llm.mock import MockLLM
from backend.services.config_service import ConfigService, WEB_ROOT
from backend.engine.commands.base import Deps
from backend.engine.hooks.pipeline import HookPipeline
from backend.engine.prompt_builder import PromptBuilder
from backend.engine.session_store import SessionStore
from backend.engine.stage_machine import StageMachine
from backend.services.backup_service import BackupService
from backend.services.memory_store import MemoryStore
from backend.services.state_store import StateStore
from backend.services.study_plan import StudyPlanStore
from backend.services.template_service import TemplateService


class TestScoreRegex(unittest.TestCase):
    def test_variants(self):
        cases = {
            "【评分：4.5】": 4.5,
            "【评分：4.5分】": 4.5,
            "**【评分：4.5】**": 4.5,
            "【评分： 3.0 】": 3.0,
            "【评分:4】": 4.0,
            "综上，给出终期评分【评分：3.5分】。" : 3.5,
        }
        for text, expected in cases.items():
            self.assertEqual(QuizEngine.extract_score(text), expected,
                             f"未识别: {text}")

    def test_no_match(self):
        self.assertIsNone(QuizEngine.extract_score("我觉得不错，4.5 分吧"))


class TestRestartAndAlias(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studyweb_fix_"))
        shutil.copytree(WEB_ROOT.parent / "docx", self.tmp / "docx")
        (self.tmp / "ragent原项目").mkdir()  # step2 仓库校验依赖该目录存在
        settings = (WEB_ROOT / "config" / "settings.toml").read_text(encoding="utf-8")
        settings = settings.replace(
            'docx_dir = "../docx"',
            f'docx_dir = "{(self.tmp / "docx").as_posix()}"')
        self.settings_path = self.tmp / "settings.toml"
        self.settings_path.write_text(settings, encoding="utf-8")
        self.config = ConfigService(self.settings_path)
        self.deps = self._make_deps()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_deps(self) -> Deps:
        cfg = self.config
        state_store = StateStore(cfg)
        memory = MemoryStore(cfg)
        stages = StageMachine(cfg)
        llm = MockLLM()
        return Deps(
            config=cfg, state_store=state_store, memory=memory,
            study_plan=StudyPlanStore(cfg), templates=TemplateService(cfg),
            backup=BackupService(cfg), stages=stages, llm=llm,
            quiz=QuizEngine(cfg, llm),
            prompts=PromptBuilder(cfg, state_store, memory, stages),
            hooks=HookPipeline(),
            session_store=SessionStore(self.tmp / "session.json"))

    def test_alias_match(self):
        registry = CommandRegistry(self.config)
        entry, args = registry.match("重新开始今日学习")
        self.assertIsNotNone(entry)
        self.assertEqual(args, "重新开始今日学习")
        entry, args = registry.match("恢复学习")
        self.assertIsNotNone(entry)
        self.assertIsNone(registry.match("今天天气怎么样"))

    def test_restart_preserves_sync_records(self):
        deps = self.deps
        day = 2
        # 先制造一份带 [同步] 记录和勾选的 Day_02.md
        mem_path = deps.memory.path_for(day)
        content = mem_path.read_text(encoding="utf-8")
        content = deps.memory.append_sync(content, "已掌握", "Prompt 结构化")
        content = deps.memory.set_unit_checked(content, "A", True)
        deps.backup.atomic_persist({mem_path: content},
                                   validator=None)

        session = deps.session_store.load()
        start = StartDayHandler()
        # FAIL-FAST 仍应拦截（未做选择时）
        stop = start.fail_fast(deps, session, "")
        self.assertIsNotNone(stop)
        self.assertIn("FAIL-FAST", stop)
        # 用户选择重新开始 → 不拦截
        self.assertIsNone(start.fail_fast(deps, session, "重新开始今日学习"))
        result = start.run(deps, session, "重新开始今日学习")

        new_content = mem_path.read_text(encoding="utf-8")
        # [同步] 记录保留、勾选重置
        self.assertIn("已掌握：Prompt 结构化", new_content)
        self.assertNotIn("- [x]", new_content)
        # unit_open 时长带 min
        opening = result.messages[-1]
        self.assertIn("预计时长：40min", opening)
        # step2 扫描结果已替换
        step2 = result.messages[1]
        self.assertIn("扫描结果：✅ 一致", step2)
        self.assertNotIn("<列表>", step2)


if __name__ == "__main__":
    unittest.main()
