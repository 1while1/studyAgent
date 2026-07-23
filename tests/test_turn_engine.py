"""turn_engine 接口与引擎路由（M5a）测试。

断言动作契约：ChatOrchestrator 是 TurnEngine 第一实现；build_turn_engine 按
session.mode × agent_mode_enabled 二选一（同一 session 不混跑）；PlannerEngine
占位 stub 可调用；SessionContext.mode 字段向后兼容。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.models import SessionContext
from backend.engine.orchestrator import ChatOrchestrator
from backend.engine.turn_engine import (AGENT_COMMAND_HINT, PlannerEngine,
                                        TurnEngine, build_turn_engine)
from backend.services.config_service import ConfigService

_SETTINGS = (
    'active_workspace = "t"\n'
    '{flag}'
    'status_enum = ["not_started", "in_progress", "completed"]\n'
    '[evidence_delta]\nquiz_right = 0.10\n'
    '[[stages]]\nname = "teaching"\nnext = ""\n'
    'sop_step = "步骤一"\ninstruction = "讲"\n'
    '[[workspaces]]\nslug = "t"\n'
    'docx_dir = "{docx}"\n'
    'project_dir = "{tmp}"\n'
    'session_path = "{session}"\n'
)


class TestTurnEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="turneng_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, agent_flag: bool) -> ConfigService:
        flag = ("agent_mode_enabled = true\n" if agent_flag else "")
        path = self.tmp / ("settings_on.toml" if agent_flag
                           else "settings_off.toml")
        path.write_text(_SETTINGS.format(
            flag=flag, docx=self.docx.as_posix(), tmp=self.tmp.as_posix(),
            session=(self.tmp / "session.json").as_posix()), encoding="utf-8")
        return ConfigService(path)

    def _tutor(self, config: ConfigService) -> ChatOrchestrator:
        from tests.test_flows import make_deps
        deps = make_deps(config, self.tmp / "session.json")
        return ChatOrchestrator(config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)

    def test_orchestrator_is_turn_engine(self):
        tutor = self._tutor(self._config(False))
        self.assertIsInstance(tutor, TurnEngine)

    def test_route_study_mode_returns_tutor(self):
        config = self._config(False)
        deps = SimpleNamespace(config=config)
        tutor = self._tutor(config)
        session = SessionContext()  # 默认 mode="study"
        self.assertIs(build_turn_engine(session, deps, tutor), tutor)

    def test_route_code_mode_flag_off_returns_tutor(self):
        config = self._config(False)  # flag 默认关闭
        deps = SimpleNamespace(config=config)
        tutor = self._tutor(config)
        session = SessionContext(mode="code")
        self.assertIs(build_turn_engine(session, deps, tutor), tutor)

    def test_route_code_mode_flag_on_returns_planner(self):
        config = self._config(True)
        deps = SimpleNamespace(config=config)
        tutor = self._tutor(config)
        session = SessionContext(mode="code")
        engine = build_turn_engine(session, deps, tutor)
        self.assertIsInstance(engine, PlannerEngine)

    def test_planner_stub_callable(self):
        engine = PlannerEngine()
        session = SessionContext(mode="code")
        self.assertIsInstance(engine.instruction_for(session, "你好"), str)
        self.assertEqual(engine.post_process(session, "回复"), [])

    def test_agent_command_hint_fixed_text(self):
        self.assertEqual(AGENT_COMMAND_HINT, "该指令请在导学模式使用。")

    def test_session_mode_default_and_compat(self):
        self.assertEqual(SessionContext().mode, "study")
        # 旧 session.json 无 mode 键 → from_dict 过滤未知键，默认 study
        old = SessionContext.from_dict({"day_phase": "not_started",
                                        "round_count": 3})
        self.assertEqual(old.mode, "study")
        self.assertEqual(old.round_count, 3)
        # 新数据 round-trip
        s = SessionContext(mode="code")
        self.assertEqual(SessionContext.from_dict(s.to_dict()).mode, "code")


if __name__ == "__main__":
    unittest.main()
