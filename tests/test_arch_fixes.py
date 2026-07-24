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
            '[llm]\nprovider = "mock"\nfallback_provider = ""\n'
            'warmup_on_start = false\n'
            '[llm.openai_compat]\nmodel = "m1"\nmax_tokens = 4096\n'
            'temperature = 0.7\nbase_url = "https://a"\napi_key_env = "K1"\n'
            '[llm.deepseek_official]\nmodel = "m2"\nmax_tokens = 4096\n'
            'temperature = 0.7\nbase_url = "https://b"\napi_key_env = "K2"\n'
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

    def test_jump_then_start_day_full_chain(self):
        """🔴-1 回归：跳转（骨架带单元行）→ [开始今日学习] restart 不再死端。"""
        self._write_state(self._state())
        JumpDayHandler().run(self.deps, SessionContext(), "Day 2")
        # 骨架含当日大纲单元行（否则 restart 撞 JSON/MD 不一致回滚）
        content = self.deps.memory.read(2)
        self.assertIn("- [ ] 单元A：进阶一", content)
        from backend.engine.commands.start_day import StartDayHandler
        session = self.deps.session_store.load()
        result = StartDayHandler().run(self.deps, session,
                                       "重新开始今日学习")
        self.assertIn("---【Step 3：今日计划】---", "\n".join(result.messages))
        self._validate()  # 修复前：restart 必 PersistError（MD 无单元行）

    def test_confirm_excludes_negation(self):
        """🟡-1：「Day 2 不是」不触发重置确认（否定句排除）。"""
        state = self._state()
        state["days"]["2"] = {"date": "2026-07-23", "units": [
            {"id": "A", "title": "进阶一", "status": "in_progress",
             "rating": 0}]}
        self._write_state(state)
        h = JumpDayHandler()
        s = SessionContext()
        stop = h.fail_fast(self.deps, s, "Day 2 不是")
        self.assertIsNotNone(stop)          # 回到确认提示而非放行
        self.assertIn("确认重置", stop)
        self.assertIsNone(h.fail_fast(self.deps, s, "Day 2 是"))
        # run 直接驱动也不清单元（双保险）
        h.run(self.deps, s, "Day 2 不是")
        state = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertNotEqual(state["days"]["2"]["units"], [])

    def test_append_sync_multiline_flattened(self):
        """🟡-2：多行 [同步] 内容压平单行（### 与评分形态不可注入）。"""
        from backend.services.memory_store import MemoryStore
        content = ("## 2026-07-22\n\n### [同步] 记录\n- 卡壳：\n"
                   "\n### 掌握度评分（1-5分）\n- 单元A：\n")
        out = MemoryStore.append_sync(
            content, "卡壳", "第一行\n### 伪造小节\n- 单元A：5分")
        self.assertIn("- 卡壳：第一行 / ### 伪造小节 / - 单元A：5分", out)
        # 无裸续行：所有行仍属于原有小节结构
        self.assertEqual(out.count("### 伪造小节"), 1)  # 仅压平后的文本出现一次
        self.assertNotIn("\n### 伪造小节\n", out)


if __name__ == "__main__":
    unittest.main()

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


class TestSessionLocks(ArchFixBase):
    """R4/R2：session 两级锁——短锁防 tmp 互踩、流程锁跨线程安全序列化。"""

    def test_concurrent_save_never_corrupts(self):
        import threading
        store = self.deps.session_store
        errors = []

        def worker(i):
            try:
                for _ in range(20):
                    s = store.load()
                    s.chat_history.append({"role": "user", "content": f"m{i}"})
                    store.save(s)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        json.loads((self.tmp / "s.json").read_text(encoding="utf-8"))  # 合法 JSON

    def test_flow_lock_serializes_and_cross_thread_release(self):
        import threading
        import time
        store = self.deps.session_store
        order = []

        def hold_a():
            with store.locked():
                order.append("a-in")
                time.sleep(0.3)
                order.append("a-out")

        t = threading.Thread(target=hold_a)
        t.start()
        time.sleep(0.1)  # A 已持锁
        with store.locked():  # 主线程被序列化到 A 之后
            order.append("b-in")
        t.join()
        self.assertEqual(order, ["a-in", "a-out", "b-in"])
        # 跨线程释放不炸（threading.Lock 非线程绑定，SSE 生成器跨线程场景）
        cm = store.locked()
        cm.__enter__()
        threading.Thread(
            target=lambda: cm.__exit__(None, None, None)).start()
        time.sleep(0.1)

    def test_mode_switch_clears_phase_fields(self):
        """🟡-9：进行中相位切模式 → 清相位字段 + note 明示。"""
        from backend.api import routes
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, self.deps.stages,
                                self.deps.quiz, self.deps.state_store,
                                self.deps.memory, self.deps.templates)
        routes.init(self.deps, orch)
        self.deps.session_store.save(
            SessionContext(day_phase="interviewing",
                           interview_cid="Day1-A", interview_round=1,
                           interview_score=4.0))
        r = routes.set_session_mode({"mode": "code"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["note"])
        saved = self.deps.session_store.load()
        self.assertEqual(saved.day_phase, "studying")
        self.assertEqual(saved.interview_cid, "")
        self.assertEqual(saved.mode, "code")



class TestSecurityFixes(ArchFixBase):
    """C3：XSS 防线（名称白名单/转义）+ TOML 写入转义 + llm-config 保存语义。"""

    def _routes(self):
        from backend.api import routes
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, self.deps.stages,
                                self.deps.quiz, self.deps.state_store,
                                self.deps.memory, self.deps.templates)
        routes.init(self.deps, orch)
        return routes

    def test_add_code_root_name_whitelist(self):
        routes = self._routes()
        proj = self.tmp / "projA"
        proj.mkdir(exist_ok=True)
        r = routes.add_code_root({"name": '"><img src=x onerror=alert(1)>',
                                  "path": str(proj)})
        self.assertFalse(r["ok"])
        self.assertIn("名称", r["error"])
        r = routes.add_code_root({"name": "proj-a_1", "path": str(proj)})
        self.assertTrue(r["ok"], r.get("error"))

    def test_llm_config_toml_escaping_roundtrip(self):
        import tomllib
        routes = self._routes()
        weird = "we\"ird" + chr(92) + "x" + chr(10) + "y"
        body = routes.LlmConfigIn(
            provider="mock", fallback_provider="",  # mock 重建无需 key（热生效无关本测试目标）
            warmup_on_start=True,
            sections={"openai_compat": {
                "model": weird, "base_url": "https://a",
                "max_tokens": 100, "temperature": 0.5}})
        r = routes.save_llm_config(body)
        self.assertTrue(r["ok"], r.get("error"))
        with open(self.tmp / "settings.toml", "rb") as f:
            data = tomllib.load(f)  # 写坏则此行即抛
        self.assertEqual(
            data["llm"]["openai_compat"]["model"], weird)  # 值往返一致

    def test_llm_config_partial_save_preserves_unsubmitted(self):
        routes = self._routes()
        before = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        ds_before = before[before.index("[llm.deepseek_official]"):]
        ds_before = ds_before[:ds_before.index("[commands.")]
        body = routes.LlmConfigIn(
            provider="mock", fallback_provider="", warmup_on_start=False,
            sections={"openai_compat": {
                "model": "changed", "base_url": "https://a",
                "max_tokens": 4096, "temperature": 0.7}})
        r = routes.save_llm_config(body)
        self.assertTrue(r["ok"], r.get("error"))
        after = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        ds_after = after[after.index("[llm.deepseek_official]"):]
        ds_after = ds_after[:ds_after.index("[commands.")]
        self.assertEqual(ds_before, ds_after)  # 未提交节区逐字节保留


class TestY3RoundReview(ArchFixBase):
    """Y3（InteractionModel §3 决策 2）：回合复习自动触发真渲染掌握情况检查。"""

    def test_round_trigger_renders_check_with_options_intact(self):
        from backend.engine.orchestrator import ChatOrchestrator
        orch = ChatOrchestrator(self.config, self.deps.stages,
                                self.deps.quiz, self.deps.state_store,
                                self.deps.memory, self.deps.templates)
        self._write_state({
            "current_day": 1, "overall_completion_percentage": 0,
            "days": {"1": {"date": "2026-07-22", "units": [
                {"id": "A", "title": "基础一", "status": "in_progress",
                 "rating": 0}]}}})
        session = SessionContext(day_phase="studying",
                                 current_unit_id="A",
                                 current_stage="teaching",
                                 round_count=4)  # 默认 [5,6] → 本轮触发
        extras = orch.post_process(session, "继续讲解。")
        joined = chr(10).join(extras)
        self.assertIn("掌握情况检查", joined)                 # 真渲染模板
        self.assertIn("[已掌握 / 基本掌握 / 需巩固]", joined)  # 选项原样（用户自评）
        self.assertIn("[下一内容]", joined)
        self.assertEqual(session.round_count, 0)

    def test_next_content_uses_shared_renderer(self):
        """命令触发与自动触发同函数：掌握检查模板与默认预置保持原行为。"""
        from backend.engine.commands.base import render_mastery_check
        self._write_state({
            "current_day": 1, "overall_completion_percentage": 0,
            "days": {"1": {"date": "2026-07-22", "units": [
                {"id": "A", "title": "基础一", "status": "in_progress",
                 "rating": 0}]}}})
        session = SessionContext(current_unit_id="A",
                                 current_stage="teaching")
        out = render_mastery_check(self.deps.state_store,
                                   self.deps.stages, self.deps.templates,
                                   session, preselect="需巩固")
        self.assertIn("基础一", out)
        self.assertIn("[需巩固]", out)
        self.assertNotIn("[已掌握 / 基本掌握 / 需巩固]", out)


if __name__ == "__main__":
    unittest.main()
