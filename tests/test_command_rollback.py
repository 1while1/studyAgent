# -*- coding: utf-8 -*-
"""指令 LLM 失败回滚快照回归测试（铁律 10：LLM 失败状态一致）。

/api/command 的 handler 已把磁盘数据推进（StudyState/StudyMemory 经
atomic_persist 落盘）之后，若 LLM 流式调用失败，路由必须把 session
整体回滚到指令前快照（routes.py snapshot = deepcopy(session)），
防「磁盘已推进 + session 阶段/chat_history 分裂」。

G12 双子审查加固：
- 🔴-1 变异防护：[同步] 不改 session，删掉 routes.py:257 的 save(snapshot)
  原测试照样绿——spy SessionStore.save，断言失败路径恰好一次、内容为快照；
- 🔴-2 Day 硬编码：从复制的 StudyState.json 读 current_day，不再写死
  Day_02.md（真实学习进度推进后假性变红）。

已知边界（G2 留档另立）：回滚只覆盖 session 对象，handler 的外部落盘
（StudyMemory [同步] 记录 / StudyState sync_records / notes.json /
learner 证据 / InterviewQA.md）不在回滚范围——本测试一并锁定该不对称性，
将来若扩展回滚范围，测试需同步更新。
"""
import asyncio
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api import routes
from backend.engine.orchestrator import ChatOrchestrator
from backend.llm.base import LLMClient
from backend.services.config_service import ConfigService

WEB_ROOT = Path(__file__).resolve().parents[1]


class _FailLLM(LLMClient):
    """首包即抛错的故障渠道。"""

    def chat_stream(self, messages, max_tokens=None):
        raise RuntimeError("模拟 LLM 故障")
        yield  # pragma: no cover - 保持生成器接口形态


class _MidFailLLM(LLMClient):
    """先吐两个 delta 再断流的故障渠道（部分输出同样须回滚）。"""

    def chat_stream(self, messages, max_tokens=None):
        yield "部分输出甲"
        yield "部分输出乙"
        raise RuntimeError("模拟中途断流")


def _consume(resp) -> list[dict]:
    """完整消费 SSE 流，返回事件列表。"""
    async def drive():
        events = []
        async for chunk in resp.body_iterator:
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events
    return asyncio.run(drive())


class TestCommandRollback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="cmdrollback_"))
        shutil.copytree(WEB_ROOT.parent / "docx", cls.tmp / "docx")
        settings_src = (WEB_ROOT / "config" / "settings.toml").read_text(encoding="utf-8")
        settings = settings_src.replace(
            'docx_dir = "../docx"',
            f'docx_dir = "{(cls.tmp / "docx").as_posix()}"')
        settings = re.sub(r'active_workspace = ".*?"',
                          'active_workspace = "ragent"', settings)
        cls.settings_path = cls.tmp / "settings.toml"
        cls.settings_path.write_text(settings, encoding="utf-8")
        cls.config = ConfigService(cls.settings_path)
        cls.session_path = cls.tmp / "session.json"
        # 🔴-2 修复：Day 文件名从复制的状态里读，不随真实学习进度漂移
        state = json.loads((cls.tmp / "docx" / "StudyState.json")
                           .read_text(encoding="utf-8"))
        cls.day = state["current_day"]
        cls.day_mem = cls.tmp / "docx" / "StudyMemory" / f"Day_{cls.day:02d}.md"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run_failing_command(self, llm):
        from tests.test_flows import make_deps
        from backend.engine.session_store import SessionContext, SessionStore
        # 先播种一条历史，让「回滚后 == 指令前」成为强断言（文件已存在）
        seeded = SessionContext()
        seeded.chat_history.append({"role": "user", "content": "指令前历史"})
        SessionStore(self.session_path).save(seeded)

        deps = make_deps(self.config, self.session_path)
        deps.llm = llm
        deps.llm_cheap = llm
        deps.quiz.set_llm(llm)
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)

        # 🔴-1 修复：spy save——回滚 save 删除（0 次）或误写 session
        # （内容含用户指令）都必然变红
        saves = []
        orig_save = deps.session_store.save
        def _spy(session):
            saves.append(session.to_dict())
            return orig_save(session)
        deps.session_store.save = _spy

        before = json.loads(self.session_path.read_text(encoding="utf-8"))
        events = _consume(routes.command(
            routes.TextIn(text="[同步] 卡壳 回滚测试内容")))
        return before, events, saves

    def _assert_rolled_back(self, before, events, saves):
        errors = [e.get("content", "") for e in events if e.get("type") == "error"]
        self.assertTrue(any("LLM 调用失败" in c for c in errors),
                        f"应报 LLM 调用失败，实际事件: {events}")
        self.assertEqual(len(saves), 1,
                         f"LLM 失败路径应恰好回滚 save 一次，实际 {len(saves)} 次")
        self.assertEqual(saves[0], before,
                         "回滚 save 的内容必须是指令前快照")
        after = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(before, after,
                         "LLM 失败后磁盘 session 必须等于指令前快照")
        users = [m["content"] for m in after.get("chat_history", [])
                 if m.get("role") == "user"]
        self.assertNotIn("[同步] 卡壳 回滚测试内容", users,
                         "chat_history 不得残留失败轮的用户指令")

    def test_llm_failure_rolls_back_session_snapshot(self):
        before, events, saves = self._run_failing_command(_FailLLM())
        self._assert_rolled_back(before, events, saves)

    def test_mid_stream_failure_rolls_back_too(self):
        before, events, saves = self._run_failing_command(_MidFailLLM())
        self._assert_rolled_back(before, events, saves)

    def test_external_persist_not_rolled_back(self):
        """已知边界锁定：handler 的外部落盘（StudyMemory sync 记录）不回滚。"""
        self._run_failing_command(_FailLLM())
        mem = self.day_mem.read_text(encoding="utf-8")
        self.assertIn("回滚测试内容", mem,
                      "外部落盘不回滚（G2 留档语义）——若此断言失效说明"
                      "回滚范围已扩展，请同步更新本测试与铁律 10 注释")


if __name__ == "__main__":
    unittest.main()
