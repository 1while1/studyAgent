"""断连不丢消息回归测试：/api/chat 先落盘用户消息再开始流式。

修复前：用户消息在流式完成后才随 session 落盘；客户端中途断连
（GeneratorExit 不走 except Exception 分支）→ 消息整轮丢失，
刷新后前端历史与后端分叉（走查「历史回填渲染卡片」超时的根因）。
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api import routes
from backend.engine.orchestrator import ChatOrchestrator
from backend.services.config_service import ConfigService

TODAY = date.today().isoformat()


class TestChatDisconnect(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chatdisc_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.session_path = self.tmp / "session.json"
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {"2": {"date": TODAY, "units": [
                {"id": "A", "title": "测试单元", "status": "in_progress"}]}}},
            ensure_ascii=False), encoding="utf-8")
        (self.docx / "StudyMemory" / "Day_02.md").write_text(
            "## 2026-07-23\n\n### [同步] 记录\n- 已掌握：无\n- 卡壳：无\n"
            "- 疑问：无\n- 代码完成：无\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_user_message_saved_before_stream(self):
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.session_path)
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        resp = routes.chat(routes.TextIn(text="断连前的用户消息"))

        async def drive():
            it = resp.body_iterator
            await it.__anext__()  # 读到首个 SSE 事件（此刻用户消息应已落盘）
            await it.aclose()     # 模拟客户端断连（GeneratorExit，不走 except）
        asyncio.run(drive())
        saved = json.loads(self.session_path.read_text(encoding="utf-8"))
        users = [m["content"] for m in saved["chat_history"]
                 if m["role"] == "user"]
        self.assertIn("断连前的用户消息", users)


if __name__ == "__main__":
    unittest.main()
