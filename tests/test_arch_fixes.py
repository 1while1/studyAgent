"""架构审计修复批回归测试（C1）：超前学习 / 跳转天数 / 纯消息指令路由尾段。

三个 🔴 均为「代码路径 vs validator/确认协议」的契约断裂且曾是测试盲区：
- 超前插入行后缀位置（id 必须紧跟冒号）
- 跳转天数确认死循环/取消死端/StudyMemory 时序死锁
- /api/command 无 llm_instruction 时 UnboundLocalError（驱动完整 SSE 生成器断言）
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.models import SessionContext
from backend.engine.commands.jump_day import JumpDayHandler
from backend.engine.commands.next_content import NextContentHandler
from backend.services.config_service import ConfigService
from tests.test_flows import make_deps

_STUDY_MD = """# 学习计划

当前天数：Day 1
整体完成度：0%

## Day 1 | 2026-07-22（星期三）
**目标**：基础
**导学单元**：
1. [ ] 单元A：基础一（预计 40min）
   - 文档：无
**编码目标**：无
**推荐论文**：无
**面试话术目标**：无

## Day 2 | 2026-07-23（星期四）
**目标**：进阶
**导学单元**：
1. [ ] 单元A：进阶一（预计 40min）
   - 文档：无
**编码目标**：无
**推荐论文**：无
**面试话术目标**：无
"""


class ArchFixBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="archfix_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        (self.docx / "Study.md").write_text(_STUDY_MD, encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            'mastery_pass_score = 3.0\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[workspaces]]\nslug = "t"\ntotal_days = 5\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s.json").as_posix()}"\n'
            '[commands."跳转天数"]\nhandler = "jump_day"\nsop_card = ""\n'
            '[commands."超前学习"]\nhandler = "next_content"\n'
            'mode = "ahead"\nsop_card = ""\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.deps = make_deps(self.config, self.tmp / "s.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_state(self, state: dict):
        (self.docx / "StudyState.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _validate(self):
        ok, out = self.deps.validator()()
        self.assertTrue(ok, f"validator 拒绝: {out}")


class TestAheadFlow(ArchFixBase):
    """超前学习：插入行格式必须同时过 validator 与 memory_store 正则族。"""

    def setUp(self):
        super().setUp()
        self._write_state({
            "current_day": 1, "overall_completion_percentage": 0,
            "last_active_date": "2026-07-22",
            "days": {"1": {"date": "2026-07-22", "units": [
                {"id": "A", "title": "基础一", "status": "completed",
                 "rating": 4.0}]}}})
        (self.docx / "StudyMemory" / "Day_01.md").write_text(
            "## 2026-07-22\n\n### 今日导学单元\n"
            "- [x] 单元A：基础一\n\n### [同步] 记录\n"
            "- 已掌握：\n- 卡壳：\n- 疑问：\n- 面试话术：\n- 代码完成：\n"
            "\n### 掌握度评分（1-5分）\n- 单元A：4.0分\n"
            "\n### replica 进度\n- 已完成模块：\n- 今日新增代码：\n- 待完成：\n"
            "\n### AI 拷打评语\n- 强项：\n- 风险点：\n- 建议：\n"
            "\n### 推荐论文/文章阅读情况\n- 无\n\n### 明日优先项\n- 待生成\n",
            encoding="utf-8")

    def test_ahead_insert_and_complete_unit(self):
        session = SessionContext(current_unit_id="A",
                                 day_phase="studying")
        handler = NextContentHandler()
        # 今日单元已全部完成 → 超前分支
        result = handler.run(self.deps, session, "", mode="ahead")
        self.assertIn("已超前加载 Day 2", "\n".join(result.messages))
        # 落盘过 validator（修复前此处 100% PersistError）
        self._validate()
        state = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        ahead = next(u for u in state["days"]["1"]["units"] if u.get("ahead"))
        self.assertEqual(ahead["id"], "AA")  # A 冲突 → AA
        # StudyMemory 行可被 memory_store 解析（后缀在标题后）
        from backend.services.memory_store import MemoryStore
        content = (self.docx / "StudyMemory" / "Day_01.md") \
            .read_text(encoding="utf-8")
        checks = MemoryStore.unit_checks(content)
        self.assertIn("AA", checks)
        self.assertFalse(checks["AA"])
        # 完成超前单元（scored 确认推进）→ 勾选+评分落盘再过 validator
        session.current_stage = "scored"
        session.pending_score = 4.5
        handler.run(self.deps, session, "")
        self._validate()
        content = (self.docx / "StudyMemory" / "Day_01.md") \
            .read_text(encoding="utf-8")
        checks = MemoryStore.unit_checks(content)
        self.assertTrue(checks["AA"])
        self.assertIn("单元AA：4.5分", content)


class TestJumpDayFix(ArchFixBase):
    def _state(self):
        return {
            "current_day": 1, "overall_completion_percentage": 0,
            "last_active_date": "2026-07-22",
            "days": {"1": {"date": "2026-07-22", "units": []}}}

    def test_jump_to_day_without_memory_creates_skeleton(self):
        self._write_state(self._state())
        result = JumpDayHandler().run(self.deps, SessionContext(), "Day 3")
        self.assertIn("Day 3", "\n".join(result.messages))
        # StudyMemory 骨架已补建（修复前 validator 时序死锁）
        self.assertTrue(self.deps.memory.exists(3))
        self._validate()
        state = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_day"], 3)

    def test_confirm_flow_no_dead_loop(self):
        state = self._state()
        state["days"]["2"] = {"date": "2026-07-23", "units": [
            {"id": "A", "title": "进阶一", "status": "in_progress",
             "rating": 0}]}
        self._write_state(state)
        h = JumpDayHandler()
        s = SessionContext()
        stop = h.fail_fast(self.deps, s, "Day 2")
        self.assertIn("确认重置", stop)  # 有进度 → 确认提示（含可操作措辞）
        # 确认形态「Day 2 是」放行（修复前永远落空死循环）
        self.assertIsNone(h.fail_fast(self.deps, s, "Day 2 是"))
        result = h.run(self.deps, s, "Day 2 是")
        self.assertIn("Day 2", "\n".join(result.messages))
        self._validate()
        state = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_day"], 2)
        self.assertEqual(state["days"]["2"]["units"], [])  # 已重置
        # 无数字的「是」不再落入死端 → 用法提示
        stop = h.fail_fast(self.deps, SessionContext(), "是")
        self.assertIn("用法", stop)


class TestCommandTailNoStreamer(ArchFixBase):
    """R3：纯消息指令（无 llm_instruction）驱动完整 SSE 生成器不再抛异常。"""

    def _drive(self, text: str) -> str:
        from backend.api import routes
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, self.deps.stages,
                                self.deps.quiz, self.deps.state_store,
                                self.deps.memory, self.deps.templates)
        routes.init(self.deps, orch)
        resp = routes.command(routes.TextIn(text=text))

        async def drive():
            chunks = []
            async for chunk in resp.body_iterator:
                chunks.append(chunk)
            return "".join(chunks)
        return asyncio.run(asyncio.wait_for(drive(), timeout=15))

    def test_fail_fast_stop_message_only(self):
        self._write_state({
            "current_day": 1, "overall_completion_percentage": 0,
            "days": {"1": {"date": "2026-07-22", "units": []}}})
        out = self._drive("[跳转天数] Day 9")  # 超范围 → fail_fast 纯消息
        self.assertIn("超出范围", out)
        self.assertIn('"done"', out)  # 修复前 done 后 UnboundLocalError

    def test_handler_messages_only(self):
        self._write_state({
            "current_day": 1, "overall_completion_percentage": 0,
            "days": {"1": {"date": "2026-07-22", "units": [
                {"id": "A", "title": "基础一", "status": "in_progress",
                 "rating": 0}]}}})
        (self.docx / "StudyMemory" / "Day_01.md").write_text(
            "## 2026-07-22\n\n### 今日导学单元\n- [ ] 单元A：基础一\n"
            "\n### [同步] 记录\n- 已掌握：\n- 卡壳：\n- 疑问：\n"
            "- 面试话术：\n- 代码完成：\n\n### 掌握度评分（1-5分）\n- 单元A：\n"
            "\n### replica 进度\n- 已完成模块：\n- 今日新增代码：\n- 待完成：\n"
            "\n### AI 拷打评语\n- 强项：\n- 风险点：\n- 建议：\n"
            "\n### 推荐论文/文章阅读情况\n- 无\n\n### 明日优先项\n- 待生成\n",
            encoding="utf-8")
        out = self._drive("[超前学习]")  # 单元未完成 → handler 纯消息分支
        self.assertIn("不能超前学习", out)
        self.assertIn('"done"', out)


if __name__ == "__main__":
    unittest.main()
