"""端到端流程测试：MockLLM 跑通 开始→下一内容(2回合)→同步→结束，终态 validate 全绿。

在 docx 的临时副本上运行，不触碰真实数据。
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.commands.base import Deps
from backend.engine.commands.next_content import NextContentHandler
from backend.engine.commands.start_day import StartDayHandler
from backend.engine.commands.sync import SyncHandler
from backend.engine.commands.end_day import EndDayHandler
from backend.engine.hooks.pipeline import HookPipeline
from backend.engine.hooks.validate_hook import make_validator
from backend.engine.orchestrator import ChatOrchestrator
from backend.engine.prompt_builder import PromptBuilder
from backend.engine.quiz_engine import QuizEngine
from backend.engine.session_store import SessionStore
from backend.engine.stage_machine import StageMachine
from backend.llm.mock import MockLLM
from backend.services.backup_service import BackupService
from backend.services.config_service import ConfigService, WEB_ROOT
from backend.services.memory_store import MemoryStore
from backend.services.state_store import StateStore
from backend.services.study_plan import StudyPlanStore
from backend.services.template_service import TemplateService


def make_deps(config: ConfigService, session_path: Path) -> Deps:
    state_store = StateStore(config)
    memory = MemoryStore(config)
    stages = StageMachine(config)
    llm = MockLLM()
    return Deps(
        config=config, state_store=state_store, memory=memory,
        study_plan=StudyPlanStore(config), templates=TemplateService(config),
        backup=BackupService(config), stages=stages, llm=llm,
        llm_cheap=llm,
        quiz=QuizEngine(config, llm),
        prompts=PromptBuilder(config, state_store, memory, stages),
        hooks=HookPipeline(), session_store=SessionStore(session_path))


class TestFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="studyweb_test_"))
        shutil.copytree(WEB_ROOT.parent / "docx", cls.tmp / "docx")
        settings_src = (WEB_ROOT / "config" / "settings.toml").read_text(encoding="utf-8")
        settings = settings_src.replace(
            'docx_dir = "../docx"',
            f'docx_dir = "{(cls.tmp / "docx").as_posix()}"')
        # 固定激活工作区为 ragent（其 docx_dir 已被替换为临时副本），
        # 与当前用户实际激活的工作区解耦
        settings = re.sub(r'active_workspace = ".*?"',
                          'active_workspace = "ragent"', settings)
        cls.settings_path = cls.tmp / "settings.toml"
        cls.settings_path.write_text(settings, encoding="utf-8")
        cls.config = ConfigService(cls.settings_path)
        cls.deps = make_deps(cls.config, cls.tmp / "session.json")
        cls.orch = ChatOrchestrator(
            cls.config, cls.deps.stages, cls.deps.quiz,
            cls.deps.state_store, cls.deps.memory, cls.deps.templates)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _validate_tmp(self):
        rc = subprocess.run(
            [sys.executable, str(self.tmp / "docx" / "hooks" / "validate_study.py")],
            capture_output=True, text=True)
        self.assertEqual(rc.returncode, 0, f"validate 失败: {rc.stderr}")

    def test_full_day_flow(self):
        deps, orch = self.deps, self.orch
        session = deps.session_store.load()

        # 1. [开始今日学习] FAIL-FAST：Day_02.md 已存在 → 双选项 STOP
        start = StartDayHandler()
        stop = start.fail_fast(deps, session, "")
        self.assertIsNotNone(stop)
        self.assertIn("FAIL-FAST", stop)

        # 2. 用户选择重新开始 → run：4 步模板 + 落盘 + 进入 teaching
        result = start.run(deps, session, "")
        joined = "\n".join(result.messages)
        self.assertIn("---【Step 1：历史分析】---", joined)
        self.assertIn("---【Step 3：今日计划】---", joined)
        self.assertIn("---【Step 4：开始 AI 导学】---", joined)
        self.assertIn("---【单元 1 开始】---", joined)
        self.assertEqual(session.current_stage, "teaching")
        self.assertEqual(session.current_unit_id, "A")
        # M5b：新开始同步重置归档层（防 archive_upto 越界）
        self.assertEqual(session.archive_summary, "")
        self.assertEqual(session.archive_upto, 0)
        self._validate_tmp()

        # 3. [下一内容] → 掌握情况检查（默认需巩固）+ 进入 quiz_r1
        nxt = NextContentHandler()
        result = nxt.run(deps, session, "")
        self.assertIn("---【掌握情况检查】---", result.messages[0])
        self.assertIn("[需巩固]", result.messages[0])
        self.assertEqual(session.current_stage, "quiz_r1")

        # 4. 用户答第一轮 → orchestrator 推进 quiz_r2
        instruction = orch.instruction_for(session, "SSE 是服务端推送协议")
        self.assertIn("第二轮", instruction)
        orch.post_process(session, "【Mock 点评】第一轮回答正确。")
        self.assertEqual(session.current_stage, "quiz_r2")

        # 5. 用户答第二轮，LLM 给出【评分：4.5】→ scored + 跳转预告
        extras = orch.post_process(
            session, "【Mock 点评】回答正确。综合两轮：【评分：4.5】")
        self.assertEqual(session.current_stage, "scored")
        self.assertEqual(session.pending_score, 4.5)
        self.assertIn("我判断你已基本掌握", extras[0])

        # 6. 用户确认 [下一内容] → 落盘 completed 4.5 + 下一单元开场
        result = nxt.run(deps, session, "")
        state = deps.state_store.load()
        unit_a = deps.state_store.set_unit(state, "A")
        self.assertEqual(unit_a["status"], "completed")
        self.assertEqual(unit_a["rating"], 4.5)
        self.assertIn("---【单元 1 开始】---", "\n".join(result.messages))
        self.assertEqual(session.current_unit_id, "B")
        self._validate_tmp()

        # 7. [同步] 已掌握 → StudyMemory + JSON 落盘
        sync = SyncHandler()
        self.assertIsNone(sync.fail_fast(deps, session, "已掌握 RAG 三阶段"))
        sync.run(deps, session, "已掌握 RAG 三阶段")
        state = deps.state_store.load()
        self.assertIn("RAG 三阶段",
                      deps.state_store.day(state)["sync_records"]["mastered"])
        self._validate_tmp()

        # 8. [结束今日学习] 跳过复盘 → 6 步产出 + 校验全绿
        end = EndDayHandler()
        self.assertIsNone(end.fail_fast(deps, session, "跳过复盘"))
        result = end.run(deps, session, "跳过复盘")
        joined = "\n".join(result.messages)
        self.assertIn("---【Step 1：[同步] 汇总】---", joined)
        self.assertIn("---【今日学习结束】---", joined)
        state = deps.state_store.load()
        day2 = deps.state_store.day(state)
        self.assertTrue(day2["active_day_completed"])
        self.assertEqual(state["overall_completion_percentage"], 8)
        unit_b = deps.state_store.set_unit(state, "B")
        self.assertEqual(unit_b["status"], "postponed")
        study_md = (self.tmp / "docx" / "Study.md").read_text(encoding="utf-8")
        self.assertIn("## Day 2 | 2026-05-25（周一） ✅", study_md)
        reviews = list((self.tmp / "docx" / "StudyReview").glob("Day_02-*.md"))
        self.assertTrue(reviews, "StudyReview 未生成")
        # 8b. 滚动细化：Day 3 粗纲（ragent 旧数据无细化小节）已由 MockLLM 自动细化
        day3 = deps.study_plan.parse_day(3)
        self.assertTrue(day3["units"], "end_day 未自动细化 Day 3")
        self._validate_tmp()

        # 9. 跨日递进：[开始今日学习] → current_day=3 原子落盘（Day 3 已自动细化）
        self.assertIsNone(start.fail_fast(deps, session, ""))  # 前一天已结束，不 FAIL-FAST
        result = start.run(deps, session, "")
        state = deps.state_store.load()
        self.assertEqual(state["current_day"], 3)
        self.assertNotIn("active_day_completed", state)  # 顶层不得有游离键
        self.assertTrue((self.tmp / "docx" / "StudyMemory" / "Day_03.md").exists())
        smd = (self.tmp / "docx" / "Study.md").read_text(encoding="utf-8")
        self.assertIn("当前天数：Day 3", smd)
        self.assertIn("---【单元 1 开始】---", "\n".join(result.messages))
        self.assertEqual(session.current_unit_id, "A")
        self._validate_tmp()


if __name__ == "__main__":
    unittest.main()
