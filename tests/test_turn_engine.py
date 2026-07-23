"""turn_engine 接口与引擎路由（M5a）测试。

断言动作契约：ChatOrchestrator 是 TurnEngine 第一实现；build_turn_engine 按
session.mode × agent_mode_enabled 二选一（同一 session 不混跑）；PlannerEngine
占位 stub 可调用；SessionContext.mode 字段向后兼容；command 路由 agent 会话
固定提示 guard（routes 级）。
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api import routes
from backend.domain.models import SessionContext
from backend.engine.orchestrator import ChatOrchestrator
from backend.engine.planner import PlannerEngine
from backend.engine.turn_engine import (AGENT_COMMAND_HINT, TurnEngine,
                                        build_turn_engine)
from backend.services.config_service import ConfigService

_SETTINGS = (
    'active_workspace = "t"\n'
    '{flag}'
    'status_enum = ["not_started", "in_progress", "completed"]\n'
    '[evidence_delta]\nquiz_right = 0.10\n'
    '[[stages]]\nname = "teaching"\nnext = ""\n'
    'sop_step = "步骤一"\ninstruction = "讲"\n'
    '{commands}'
    '[[workspaces]]\nslug = "t"\n'
    'docx_dir = "{docx}"\n'
    'project_dir = "{tmp}"\n'
    'session_path = "{session}"\n'
)


def _write_settings(tmp: Path, docx: Path, name: str, agent_flag: bool,
                    commands: str = "") -> ConfigService:
    flag = "agent_mode_enabled = true\n" if agent_flag else ""
    path = tmp / name
    path.write_text(_SETTINGS.format(
        flag=flag, commands=commands, docx=docx.as_posix(),
        tmp=tmp.as_posix(),
        session=(tmp / "session.json").as_posix()), encoding="utf-8")
    return ConfigService(path)


def _make(config: ConfigService, tmp: Path):
    """真实 deps + tutor（不用假命名空间：build_turn_engine 未来加依赖时测试不假绿）。"""
    from tests.test_flows import make_deps
    deps = make_deps(config, tmp / "session.json")
    tutor = ChatOrchestrator(config, deps.stages, deps.quiz,
                             deps.state_store, deps.memory, deps.templates)
    return deps, tutor


class TestTurnEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="turneng_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, agent_flag: bool) -> ConfigService:
        return _write_settings(
            self.tmp, self.docx,
            "settings_on.toml" if agent_flag else "settings_off.toml",
            agent_flag)

    def test_orchestrator_is_turn_engine(self):
        _, tutor = _make(self._config(False), self.tmp)
        self.assertIsInstance(tutor, TurnEngine)

    def test_route_study_mode_returns_tutor(self):
        config = self._config(False)
        deps, tutor = _make(config, self.tmp)
        session = SessionContext()  # 默认 mode="study"
        self.assertIs(build_turn_engine(session, deps, tutor), tutor)

    def test_route_code_mode_flag_off_returns_tutor(self):
        config = self._config(False)  # flag 默认关闭
        deps, tutor = _make(config, self.tmp)
        session = SessionContext(mode="code")
        self.assertIs(build_turn_engine(session, deps, tutor), tutor)

    def test_route_code_mode_flag_on_returns_planner(self):
        config = self._config(True)
        deps, tutor = _make(config, self.tmp)
        session = SessionContext(mode="code")
        engine = build_turn_engine(session, deps, tutor)
        self.assertIsInstance(engine, PlannerEngine)

    def test_route_study_mode_flag_on_returns_tutor(self):
        """第四象限：flag 打开后旧 study 会话仍走导学引擎（不混跑的关键保证）。"""
        config = self._config(True)
        deps, tutor = _make(config, self.tmp)
        session = SessionContext()  # study
        self.assertIs(build_turn_engine(session, deps, tutor), tutor)

    def test_planner_real_engine_callable(self):
        """M5c：PlannerEngine 真身——instruction_for 含 ACTION 契约与工具清单。"""
        config = self._config(True)
        deps, _ = _make(config, self.tmp)
        engine = PlannerEngine(deps)
        session = SessionContext(mode="code")
        instruction = engine.instruction_for(session, "你好")
        self.assertIsInstance(instruction, str)
        self.assertIn("[ACTION:", instruction)
        self.assertIn("read_model", instruction)  # 工具清单注入
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


class TestAgentCommandGuard(unittest.TestCase):
    """command 路由 guard（routes.py）：agent 会话收到导学指令 → 固定提示且不执行 handler。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="guard_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_agent_session_command_gets_fixed_hint(self):
        config = _write_settings(
            self.tmp, self.docx, "settings.toml", agent_flag=True,
            commands='[commands."开始今日学习"]\nhandler = "start_day"\n'
                     'sop_card = ""\n')
        deps, tutor = _make(config, self.tmp)
        # agent 会话（mode=code）落盘
        deps.session_store.save(SessionContext(mode="code"))
        routes.init(deps, tutor)

        resp = routes.command(routes.TextIn(text="[开始今日学习]"))

        async def drive():
            chunks = []
            async for chunk in resp.body_iterator:
                chunks.append(chunk)
            return chunks
        text = "".join(asyncio.run(drive()))
        self.assertIn(AGENT_COMMAND_HINT, text)
        self.assertIn('"done"', text)
        # handler 未执行：阶段未推进、无对话记录（guard 在 fail_fast/run 之前返回）
        saved = json.loads(
            (self.tmp / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(saved.get("day_phase"), "not_started")
        self.assertEqual(saved.get("chat_history", []), [])


class TestSessionModeApi(unittest.TestCase):
    """会话模式端点（M6 双轴之 agent 状态轴）：GET/POST /api/session/mode。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sessmode_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        config = _write_settings(self.tmp, self.docx, "settings.toml",
                                 agent_flag=True)
        self.deps, self.tutor = _make(config, self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_default_study(self):
        routes.init(self.deps, self.tutor)
        r = routes.get_session_mode()
        self.assertTrue(r["ok"])
        self.assertEqual(r["mode"], "study")

    def test_post_persists_and_routes_engine(self):
        routes.init(self.deps, self.tutor)
        r = routes.set_session_mode({"mode": "code"})
        self.assertTrue(r["ok"])
        self.assertEqual(routes.get_session_mode()["mode"], "code")
        # 落盘证实：引擎路由读取的正是该字段（flag on + code → planner）
        saved = json.loads(
            (self.tmp / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(saved.get("mode"), "code")
        session = self.deps.session_store.load()
        engine = build_turn_engine(session, self.deps, tutor=self.tutor)
        self.assertIsInstance(engine, PlannerEngine)
        # 切回 study → tutor
        r = routes.set_session_mode({"mode": "study"})
        self.assertTrue(r["ok"])
        session = self.deps.session_store.load()
        self.assertIs(build_turn_engine(session, self.deps,
                                        tutor=self.tutor), self.tutor)

    def test_post_invalid_mode_rejected(self):
        routes.init(self.deps, self.tutor)
        r = routes.set_session_mode({"mode": "agent"})
        self.assertFalse(r["ok"])
        self.assertIn("非法模式", r["error"])
        r = routes.set_session_mode({})
        self.assertFalse(r["ok"])
        self.assertEqual(routes.get_session_mode()["mode"], "study")  # 未变


if __name__ == "__main__":
    unittest.main()
