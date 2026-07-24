"""架构审计修复批回归测试（A 包：engine/api/resources 族，9 项）。

- Y1 资源去项目化：模板/预设/阶段指令占位符在消费处替换（模板单源不动）
- Y2 end_step1_sync 待解答警告行两态 + 已解决计数接 notes.json
- 🟡-1 销账 question 条目摘除 StudyMemory 疑问行「（待解答）」后缀
- 🟡-2 end_day 阶段复位 + ENDED/NOT_STARTED 相位短路 + 全完成护栏
- 🟡-5 配置非法值防御（trigger_ratio/_context_view/round_review_interval）
- 🟡-7 /api/doc memory 与 notes_distill 的 500 契约化
- 🟡-8 [同步] 子类型正则支持多行内容
- 🟡-4 persist_state 收紧（completed 不开放，schema 同步）
- Y11 UI 保存 mtime 冲突检测（一致通过/不一致拒写/不带兼容）
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.models import SessionContext
from backend.engine.commands.base import CommandHandler
from backend.engine.commands.end_day import EndDayHandler
from backend.engine.commands.next_content import NextContentHandler
from backend.engine.commands.start_day import StartDayHandler
from backend.engine.commands.sync import SyncHandler
from backend.engine.note_actions import resolve_note
from backend.engine.orchestrator import ChatOrchestrator
from backend.services.config_service import ConfigService
from backend.services.notes_service import NotesService
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


class ArchFixABase(unittest.TestCase):
    """A 包公共夹具（ArchFixBase 同款风格；replica=my-replica、total_days=5）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="archfixa_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        (self.docx / "Study.md").write_text(_STUDY_MD, encoding="utf-8")
        self.demo = self.tmp / "demo"
        self.demo.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed",'
            ' "postponed"]\n'
            'mastery_pass_score = 3.0\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\n'
            'instruction = "在 <复现名> 下编码，对照 <项目名> 源码"\n'
            '[[code_roots]]\nname = "demo"\n'
            f'path = "{self.demo.as_posix()}"\nworkspace = "t"\n'
            '[[workspaces]]\nslug = "t"\ntotal_days = 5\n'
            'replica_name = "my-replica"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s.json").as_posix()}"\n'
            f'demo_dir = "{self.demo.as_posix()}"\n'
            '[llm]\nprovider = "mock"\nfallback_provider = ""\n'
            'warmup_on_start = false\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.deps = make_deps(self.config, self.tmp / "s.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 夹具辅助 ----

    def _write_state(self, state: dict):
        (self.docx / "StudyState.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _state(self, units=None):
        return {
            "current_day": 1, "overall_completion_percentage": 0,
            "last_active_date": "2026-07-22",
            "days": {"1": {"date": "2026-07-22", "units":
                           units if units is not None else [
                               {"id": "A", "title": "基础一",
                                "status": "completed", "rating": 4.0}]}}}

    def _write_memory(self, day: int = 1, checked: bool = True,
                      score: float = 4.0, sync: dict | None = None):
        mem = self.deps.memory.render_new(
            "2026-07-22", [{"id": "A", "title": "基础一"}])
        if checked:
            mem = self.deps.memory.set_unit_checked(mem, "A", True)
            mem = self.deps.memory.set_unit_score(mem, "A", score)
        for field, value in (sync or {}).items():
            mem = self.deps.memory.append_sync(mem, field, value)
        (self.docx / "StudyMemory" / f"Day_{day:02d}.md").write_text(
            mem, encoding="utf-8")

    def _read_memory(self, day: int = 1) -> str:
        return (self.docx / "StudyMemory" / f"Day_{day:02d}.md") \
            .read_text(encoding="utf-8")

    def _validate(self):
        ok, out = self.deps.validator()()
        self.assertTrue(ok, f"validator 拒绝: {out}")

    def _orch(self):
        return ChatOrchestrator(self.config, self.deps.stages, self.deps.quiz,
                                self.deps.state_store, self.deps.memory,
                                self.deps.templates)

    def _routes(self):
        from backend.api import routes
        routes.init(self.deps, self._orch())
        return routes


class TestDeproject(ArchFixABase):
    """Y1：用户面模板/预设/阶段指令不含项目字面量，占位符在消费处替换。"""

    def test_step1_total_days_placeholder(self):
        text = StartDayHandler._render_step1(self.deps, {"days": {}}, 1, [])
        self.assertIn("Day 1 / 5", text)  # <总天数> → workspace.total_days
        self.assertNotIn("/ 25", text)
        self.assertNotIn("ragent", text.lower())

    def test_step3_replica_placeholder(self):
        plan = {"units": [{"id": "A", "title": "基础一", "duration": "40min",
                           "doc": "无"}],
                "goal": "目标", "code_goal": "骨架模块", "paper": "",
                "paper_sections": "", "qa_goal": "话题"}
        text = StartDayHandler._render_step3(self.deps, plan, 1, "2026-07-22")
        self.assertIn("my-replica 完成 骨架模块", text)
        self.assertNotIn("ragent", text.lower())

    def test_prompt_builder_stage_instruction_placeholder(self):
        session = SessionContext(current_stage="teaching",
                                 day_phase="studying")
        system = self.deps.prompts.build(session)
        # <复现名> → replica_name；<项目名> → project_dir 目录名
        self.assertIn(f"在 my-replica 下编码，对照 {self.tmp.name} 源码",
                      system)
        self.assertNotIn("<复现名>", system)
        self.assertNotIn("ragent", system.lower())

    def test_read_sop_card_placeholder(self):
        card = CommandHandler.read_sop_card(self.deps, "SOP_开始写代码.md")
        self.assertIn("my-replica 目标位置", card)
        self.assertNotIn("ragent-replica", card)
        self.assertNotIn("<复现名>", card)


class TestEndStep1Sync(ArchFixABase):
    """Y2：end_step1_sync 待解答警告行两态渲染 + 已解决计数接 notes.json。"""

    def test_pending_question_state(self):
        self._write_state(self._state())
        self._write_memory(sync={"疑问": "TCP为何三次握手（待解答）",
                                 "卡壳": "背压如何传导"})
        svc = NotesService(self.config)
        note = svc.add("stuck", "背压如何传导", day=1,
                       validator=self.deps.validator())
        svc.resolve(note["id"], day=1, validator=self.deps.validator())
        step1 = EndDayHandler().run(
            self.deps, SessionContext(), "跳过复盘").messages[0]
        self.assertIn("⚠️ 仍有 1 个待解答疑问", step1)
        self.assertIn("已解决 1 项", step1)
        self.assertNotIn("(如有「待解答」)", step1)
        self.assertNotIn("<Y>", step1)
        self.assertNotIn("<X>", step1)

    def test_no_pending_question_state(self):
        self._write_state(self._state())
        self._write_memory(sync={"疑问": "TCP为何三次握手"})
        step1 = EndDayHandler().run(
            self.deps, SessionContext(), "跳过复盘").messages[0]
        self.assertIn("待解答 0", step1)
        self.assertNotIn("⚠️", step1)
        self.assertNotIn("建议补充", step1)
        self.assertNotIn("<Y>", step1)


class TestResolveNotePendingSuffix(ArchFixABase):
    """🟡-1：销账 question 条目摘除 StudyMemory 疑问行的「（待解答）」后缀。"""

    def test_suffix_cleared_and_end_day_count_follows(self):
        self._write_state(self._state())
        self._write_memory(sync={"疑问": "TCP为何三次握手（待解答）"})
        svc = NotesService(self.config)
        note = svc.add("question", "TCP为何三次握手", day=1,
                       validator=self.deps.validator())
        result = resolve_note(self.config, self.deps.state_store,
                              note["id"], validator=self.deps.validator())
        self.assertTrue(result["ok"], result.get("error"))
        mem = self._read_memory()
        self.assertNotIn("（待解答）", mem)
        self.assertIn("TCP为何三次握手", mem)
        self._validate()
        # end_day 计数随之变化：无待解答 → 警告行消失
        step1 = EndDayHandler().run(
            self.deps, SessionContext(), "跳过复盘").messages[0]
        self.assertIn("待解答 0", step1)
        self.assertNotIn("⚠️", step1)


class TestEndDayPhaseReset(ArchFixABase):
    """🟡-2：end_day 阶段复位 + 相位短路 + ENDED 拦截 + 全完成护栏。"""

    def test_end_day_resets_stage(self):
        self._write_state(self._state())
        self._write_memory()
        session = SessionContext(current_stage="teaching",
                                 day_phase="studying", current_unit_id="A")
        EndDayHandler().run(self.deps, session, "跳过复盘")
        self.assertEqual(session.day_phase, "ended")
        self.assertEqual(session.current_stage, "")

    def test_orchestrator_phase_shortcircuit(self):
        orch = self._orch()
        for phase in ("ended", "not_started"):
            s = SessionContext(day_phase=phase, current_stage="teaching")
            self.assertEqual(orch.instruction_for(s, "你好"), "")
            self.assertEqual(orch.post_process(s, "继续讲解"), [])
            self.assertEqual(s.round_count, 0)  # 回合计数不推进

    def test_next_content_fail_fast_ended(self):
        self._write_state(self._state())
        stop = NextContentHandler().fail_fast(
            self.deps, SessionContext(day_phase="ended"), "")
        self.assertIn("已结束", stop)

    def test_all_completed_guard(self):
        self._write_state(self._state())  # 单元 A 已 completed
        self._write_memory()
        session = SessionContext(day_phase="studying", current_unit_id="A",
                                 current_stage="teaching")
        result = NextContentHandler().run(self.deps, session, "")
        self.assertIn("今日单元已全部完成", "\n".join(result.messages))
        self.assertIsNone(result.llm_instruction)
        state = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertEqual(state["days"]["1"]["units"][0]["status"],
                         "completed")  # 未被改回 in_progress


class TestConfigDefense(ArchFixABase):
    """🟡-5：非法配置值回退默认，不炸装配/视图/后处理。"""

    def test_invalid_trigger_ratio_assemble(self):
        from backend.engine.context_manager import ContextManager
        self.config.data["context"] = {"trigger_ratio": "oops"}
        session = SessionContext(day_phase="studying")
        session.chat_history = [{"role": "user", "content": "你好"}]
        messages, plan = ContextManager(self.deps).assemble(session, "sys")
        self.assertEqual(messages[0]["content"], "sys")
        self.assertIn("needs_compression", plan)

    def test_context_view_invalid_values(self):
        routes = self._routes()
        self.config.data["context"] = {"budget_tokens": "abc",
                                       "trigger_ratio": "oops"}
        view = routes._context_view()
        self.assertEqual(view["budget_tokens"], 256000)
        self.assertEqual(view["trigger_ratio"], 0.8)

    def test_round_review_interval_invalid(self):
        self.config.data["round_review_interval"] = "x"
        orch = self._orch()
        s = SessionContext(day_phase="studying", current_stage="teaching")
        extras = orch.post_process(s, "继续讲解")
        self.assertEqual(s.round_count, 1)  # 回退 [5,6]，未触发复习提示
        self.assertEqual(extras, [])


class TestEndpointContracts(ArchFixABase):
    """🟡-7：两个 500 端点改走 ok=False 契约。"""

    def test_api_doc_memory_without_state(self):
        routes = self._routes()
        r = routes.read_doc("memory")  # StudyState.json 未写
        self.assertFalse(r["ok"])
        self.assertIn("error", r)

    def test_notes_distill_bad_day_keys(self):
        routes = self._routes()
        self._write_state({"current_day": 1,
                           "overall_completion_percentage": 0,
                           "days": {"x": {"date": "2026-07-22",
                                          "units": []}}})
        r = routes.notes_distill({})  # 非法天数键
        self.assertFalse(r["ok"])
        self.assertIn("天数", r["error"])
        r2 = routes.notes_distill({"day": "abc"})  # 非法 body day
        self.assertFalse(r2["ok"])


class TestSyncMultiline(ArchFixABase):
    """🟡-8：[同步] 子类型正则支持多行内容（卡壳/疑问可换行提交）。"""

    def test_multiline_stuck(self):
        self._write_state(self._state())
        self._write_memory()
        handler = SyncHandler()
        args = "卡壳 背压第一行\n背压第二行"
        session = SessionContext(day_phase="studying", current_unit_id="A")
        self.assertIsNone(handler.fail_fast(self.deps, session, args))
        handler.run(self.deps, session, args)
        # 🟡-2 复核修复：行式契约文件内多行压平为 ` / ` 分隔（防 ### 截断
        # 小节状态机/伪造评分行/对计数蒸馏不可见）；notes.json 保留原文
        self.assertIn("背压第一行 / 背压第二行", self._read_memory())
        self.assertNotIn("背压第一行\n背压第二行", self._read_memory())
        self._validate()


class TestPersistStateTighten(ArchFixABase):
    """🟡-4：persist_state 的 set_unit_status 不再接受 completed。"""

    def setUp(self):
        super().setUp()
        from backend.engine.tool_registry import (ToolContext,
                                                  build_default_registry)
        self._write_state(self._state(units=[
            {"id": "A", "title": "基础一", "status": "not_started",
             "rating": 0}]))
        self.registry = build_default_registry()
        self.ctx = ToolContext(config=self.config,
                               state_store=self.deps.state_store)

    def test_completed_rejected(self):
        r = self.registry.invoke(
            "persist_state", {"op": "set_unit_status", "unit_id": "A",
                              "status": "completed"}, self.ctx)
        self.assertFalse(r.ok)
        self.assertIn("completed", r.error)
        state = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertEqual(state["days"]["1"]["units"][0]["status"],
                         "not_started")  # 未被改写
        spec = self.registry.get("persist_state")
        self.assertNotIn("completed",
                         spec.params["properties"]["status"]["enum"])

    def test_in_progress_still_ok(self):
        r = self.registry.invoke(
            "persist_state", {"op": "set_unit_status", "unit_id": "A",
                              "status": "in_progress"}, self.ctx)
        self.assertTrue(r.ok, r.error)
        state = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertEqual(state["days"]["1"]["units"][0]["status"],
                         "in_progress")


class TestSaveMtimeConflict(ArchFixABase):
    """Y11：/api/code/file 返回 mtime；/api/code/save 带 mtime 做冲突检测。"""

    def setUp(self):
        super().setUp()
        self.routes = self._routes()
        (self.demo / "a.txt").write_text("v1\n", encoding="utf-8")

    def test_file_response_has_mtime(self):
        r = self.routes.code_file(root="demo", path="a.txt")
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIsInstance(r["mtime"], float)

    def test_save_with_consistent_mtime(self):
        mtime = self.routes.code_file(root="demo", path="a.txt")["mtime"]
        r = self.routes.code_save({"root": "demo", "path": "a.txt",
                                   "content": "v2\n", "mtime": mtime})
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual((self.demo / "a.txt").read_text(encoding="utf-8"),
                         "v2\n")

    def test_save_with_stale_mtime_rejected(self):
        mtime = self.routes.code_file(root="demo", path="a.txt")["mtime"]
        r = self.routes.code_save({"root": "demo", "path": "a.txt",
                                   "content": "v2\n", "mtime": mtime + 100})
        self.assertFalse(r["ok"])
        self.assertTrue(r["conflict"])
        self.assertIn("外部修改", r["error"])
        self.assertEqual((self.demo / "a.txt").read_text(encoding="utf-8"),
                         "v1\n")  # 冲突拒写，磁盘内容不变

    def test_save_without_mtime_compatible(self):
        r = self.routes.code_save({"root": "demo", "path": "a.txt",
                                   "content": "v2\n"})
        self.assertTrue(r["ok"], r.get("error"))


if __name__ == "__main__":
    unittest.main()
