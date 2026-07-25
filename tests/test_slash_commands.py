"""Slash 系统指令（/compact）测试。

覆盖：正常压缩（窗口留 4 条 + 摘要落档 + 原文不删）/ 历史不足保留线 /
校验失败原文全保留 + 冷却 / 窗口首条 user 对齐 / 与 [指令] 路由隔离 /
未知指令提示。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.models import SessionContext
from backend.engine.commands import slash
from backend.engine.commands.registry import CommandRegistry
from backend.llm.mock import MockLLM
from tests.test_context_manager import Base, StubLLM, VALID_SUMMARY, _msgs


class TestSlashCompact(Base):
    def _session(self, pairs=10):
        return SessionContext(chat_history=_msgs(pairs, 30))

    def test_compact_normal_path(self):
        stub = StubLLM(outputs=[VALID_SUMMARY])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        session = self._session(10)  # 20 条
        report = slash.execute(deps, session, "/compact")
        self.assertIn("压缩完成", report)
        self.assertEqual(session.archive_upto, 16)       # 保留最近 4 条
        self.assertEqual(session.archive_summary, VALID_SUMMARY)
        self.assertEqual(len(session.chat_history), 20)  # 原文不删（指针前移）
        self.assertIn("16", report)                      # 报告含归档条数

    def test_compact_too_small_noop(self):
        deps = self._deps()
        session = self._session(2)  # 4 条，压在保留线上无可压
        before = list(session.chat_history)
        report = slash.execute(deps, session, "/compact")
        self.assertIn("无需压缩", report)
        self.assertEqual(session.archive_upto, 0)
        self.assertEqual(session.archive_summary, "")
        self.assertEqual(session.chat_history, before)

    def test_compact_validation_failure_keeps_original(self):
        stub = StubLLM(outputs=["坏输出一", "坏输出二"])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        session = self._session(6)  # 12 条
        report = slash.execute(deps, session, "/compact")
        self.assertIn("压缩失败", report)
        self.assertEqual(session.archive_upto, 0)
        self.assertEqual(session.archive_summary, "")
        self.assertEqual(len(session.chat_history), 12)  # 原文全保留不丢数据
        self.assertGreater(session.compress_cooldown, 0)  # 失败仍写冷却

    def test_compact_window_aligns_to_user(self):
        # 21 条（末尾孤立 user 消息）：len-4=17 指向 assistant → 回退对齐 16
        stub = StubLLM(outputs=[VALID_SUMMARY])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        session = self._session(10)
        session.chat_history.append({"role": "user", "content": "追问？"})
        report = slash.execute(deps, session, "/compact")
        self.assertIn("压缩完成", report)
        self.assertEqual(session.archive_upto, 16)
        window = session.chat_history[session.archive_upto:]
        self.assertEqual(window[0]["role"], "user")      # 窗口首条必为 user
        self.assertEqual(len(window), 5)

    def test_compact_respects_existing_archive(self):
        # 已归档 8 条再压：从 archive_upto 续压，不重复归档
        stub = StubLLM(outputs=[VALID_SUMMARY])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        session = self._session(10)
        session.archive_upto = 8
        session.archive_summary = VALID_SUMMARY
        report = slash.execute(deps, session, "/compact")
        self.assertIn("压缩完成", report)
        self.assertEqual(session.archive_upto, 16)


class TestSlashRouting(Base):
    def test_bracket_registry_ignores_slash(self):
        reg = CommandRegistry(self.config)
        self.assertIsNone(reg.match("/compact"))  # / 不进 [指令] 路由

    def test_slash_rejects_bracket_and_unknown(self):
        deps = self._deps()
        session = SessionContext()
        self.assertIn("未知系统指令", slash.execute(deps, session, "[下一内容]"))
        self.assertIn("未知系统指令", slash.execute(deps, session, "/nonexistent"))
        self.assertIn("未知系统指令", slash.execute(deps, session, "/"))

    def test_info_list_shape(self):
        info = slash.info_list()
        self.assertTrue(any(c["name"] == "compact" for c in info))
        for c in info:
            self.assertIn("desc", c)


if __name__ == "__main__":
    unittest.main()
