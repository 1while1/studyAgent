"""Slash 系统指令测试（v2：/compact /clear /model + 客户端指令标记）。

覆盖：/compact 正常压缩（窗口留 4 条 + 摘要落档 + 原文不删）/ 历史不足保留线 /
校验失败原文全保留 + 冷却 / 窗口首条 user 对齐 / 续压；/clear 清空历史+归档层
并标记清屏；/model 查看/未知渠道/无需切换/切换成功/构建失败降级；
与 [指令] 路由隔离；未知指令提示；info_list 形状。
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


def _report(deps, session, text):
    return slash.execute(deps, session, text)["report"]


class TestSlashCompact(Base):
    def _session(self, pairs=10):
        return SessionContext(chat_history=_msgs(pairs, 30))

    def test_compact_normal_path(self):
        stub = StubLLM(outputs=[VALID_SUMMARY])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        session = self._session(10)  # 20 条
        report = _report(deps, session, "/compact")
        self.assertIn("压缩完成", report)
        self.assertEqual(session.archive_upto, 16)       # 保留最近 4 条
        self.assertEqual(session.archive_summary, VALID_SUMMARY)
        self.assertEqual(len(session.chat_history), 20)  # 原文不删（指针前移）
        self.assertIn("16", report)                      # 报告含归档条数

    def test_compact_too_small_noop(self):
        deps = self._deps()
        session = self._session(2)  # 4 条，压在保留线上无可压
        before = list(session.chat_history)
        report = _report(deps, session, "/compact")
        self.assertIn("无需压缩", report)
        self.assertEqual(session.archive_upto, 0)
        self.assertEqual(session.archive_summary, "")
        self.assertEqual(session.chat_history, before)

    def test_compact_validation_failure_keeps_original(self):
        stub = StubLLM(outputs=["坏输出一", "坏输出二"])
        deps = self._deps(llm=MockLLM(), llm_cheap=stub)
        session = self._session(6)  # 12 条
        report = _report(deps, session, "/compact")
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
        report = _report(deps, session, "/compact")
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
        report = _report(deps, session, "/compact")
        self.assertIn("压缩完成", report)
        self.assertEqual(session.archive_upto, 16)


class TestSlashClear(Base):
    def test_clear_wipes_history_and_archive(self):
        deps = self._deps()
        session = SessionContext(chat_history=_msgs(5, 30))
        session.archive_upto = 6
        session.archive_summary = VALID_SUMMARY
        session.compress_cooldown = 2
        result = slash.execute(deps, session, "/clear")
        self.assertTrue(result["clear_screen"])          # 前端清屏标记
        self.assertIn("10", result["report"])            # 报告含清空条数
        self.assertEqual(session.chat_history, [])
        self.assertEqual(session.archive_upto, 0)
        self.assertEqual(session.archive_summary, "")
        self.assertEqual(session.compress_cooldown, 0)


class TestSlashModel(Base):
    def test_model_bare_reports_current(self):
        deps = self._deps()
        report = _report(deps, SessionContext(), "/model")
        self.assertIn("主渠道", report)
        self.assertIn("mock", report)                    # 测试配置 provider=mock

    def test_model_unknown_provider(self):
        deps = self._deps()
        report = _report(deps, SessionContext(), "/model nope")
        self.assertIn("未知渠道", report)
        self.assertEqual(deps.config.llm_config.get("provider"), "mock")  # 未变

    def test_model_same_provider_noop(self):
        deps = self._deps()
        report = _report(deps, SessionContext(), "/model mock")
        self.assertIn("无需切换", report)

    def test_model_switch_missing_key_warns(self):
        # 切到无 key 的渠道：配置落盘 + 构建失败 warning，运行态保留旧渠道
        deps = self._deps()
        old_llm = deps.llm
        report = _report(deps, SessionContext(), "/model openai_compat")
        self.assertIn("构建失败", report)
        self.assertIs(deps.llm, old_llm)                 # 运行态不换
        deps.config.reload()
        self.assertEqual(deps.config.llm_config.get("provider"),
                         "openai_compat")                # 但配置已落盘

    def test_client_command_hint(self):
        deps = self._deps()
        report = _report(deps, SessionContext(), "/usage")
        self.assertIn("客户端", report)                  # 客户端指令不进 handler


class TestSlashRouting(Base):
    def test_bracket_registry_ignores_slash(self):
        reg = CommandRegistry(self.config)
        self.assertIsNone(reg.match("/compact"))  # / 不进 [指令] 路由

    def test_slash_rejects_bracket_and_unknown(self):
        deps = self._deps()
        session = SessionContext()
        self.assertIn("未知系统指令", _report(deps, session, "[下一内容]"))
        self.assertIn("未知系统指令", _report(deps, session, "/nonexistent"))
        self.assertIn("未知系统指令", _report(deps, session, "/"))

    def test_info_list_shape(self):
        info = slash.info_list()
        names = {c["name"] for c in info}
        self.assertEqual(names, {"compact", "clear", "model", "usage"})
        for c in info:
            self.assertIn("desc", c)
            self.assertIn("client", c)
        self.assertTrue(next(c for c in info if c["name"] == "usage")["client"])
        self.assertFalse(next(c for c in info if c["name"] == "compact")["client"])


if __name__ == "__main__":
    unittest.main()
