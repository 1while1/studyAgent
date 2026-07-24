"""tool_registry 注册表与权限分级（M5a）测试。

断言动作契约（不断言自由文本）：9 个 v1 工具、权限四级正确、marker/native
两种传输暴露同名同参 schema、各工具 invoke 的行为边界（含拒绝路径）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.tool_registry import (LLM_LEVEL, READONLY, SANDBOX, WRITE,
                                          ToolContext, ToolRegistry, ToolSpec,
                                          build_default_registry)
from backend.domain.models import SessionContext
from backend.services import code_runner
from backend.services.code_browser import CodeBrowser
from backend.services.config_service import ConfigService
from backend.services.state_store import StateStore
from unittest import mock

TODAY = date.today().isoformat()

_EXPECTED = {
    "read_code": READONLY,
    "read_doc": READONLY,
    "search_notes": READONLY,
    "read_model": READONLY,
    "run_build": SANDBOX,
    "write_note": WRITE,
    "resolve_note": WRITE,
    "update_model": WRITE,
    "persist_state": WRITE,
    "quiz_generate": LLM_LEVEL,
    "retell_assess": LLM_LEVEL,
    "scaffold_create": WRITE,     # M6 实战工坊
    "edit_file": WRITE,           # M6
    "process_start": SANDBOX,     # M6
    "process_stop": SANDBOX,      # M6
    "process_logs": SANDBOX,      # M6
}


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="toolreg_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        proj = self.tmp / "projA"
        proj.mkdir()
        (proj / "a.txt").write_text("l1\nl2\nl3\nl4\nl5", encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed", "postponed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\nsync_mastered = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            f'[[code_roots]]\nname = "projA"\npath = "{proj.as_posix()}"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n'
            # M6：demo_dir 必须指向 tmp（默认会落到真实 study-web/workspaces/）
            f'demo_dir = "{(self.tmp / "demo").as_posix()}"\n'
            'replica_name = ""\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {"2": {"date": TODAY, "units": [
                {"id": "A", "title": "测试单元", "status": "in_progress"}]}}},
            ensure_ascii=False), encoding="utf-8")
        self.state_store = StateStore(self.config)
        self.registry = build_default_registry()
        self.ctx = ToolContext(config=self.config,
                               browser=CodeBrowser(self.config),
                               state_store=self.state_store)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 注册表构成与权限 ----

    def test_v1_tools_and_permissions(self):
        self.assertEqual(set(self.registry.names()), set(_EXPECTED))
        for name, perm in _EXPECTED.items():
            self.assertEqual(self.registry.get(name).permission, perm, name)

    def test_schemas_same_across_transports(self):
        marker = {s["name"]: s["params"]
                  for s in self.registry.schemas("marker")}
        native = {s["function"]["name"]: s["function"]["parameters"]
                  for s in self.registry.schemas("native")}
        self.assertEqual(set(marker), set(_EXPECTED))
        self.assertEqual(set(native), set(_EXPECTED))
        for name in _EXPECTED:
            self.assertEqual(marker[name], native[name], name)

    def test_invoke_unknown_tool(self):
        result = self.registry.invoke("no_such_tool", {}, self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("未知工具", result.error)

    # ---- read_code ----

    def test_read_code_ok(self):
        result = self.registry.invoke(
            "read_code", {"path": "projA/a.txt", "start": "2", "end": "3"},
            self.ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.event["lines"], "L2-L3")
        self.assertTrue(result.event["ok"])
        self.assertIn("l2\nl3", result.injection)

    def test_read_code_not_found(self):
        result = self.registry.invoke(
            "read_code", {"path": "projA/nope.txt"}, self.ctx)
        self.assertFalse(result.ok)
        self.assertFalse(result.event["ok"])
        self.assertIn("未找到文件", result.injection)

    def test_read_code_missing_browser(self):
        ctx = ToolContext(config=self.config)  # 无 browser
        result = self.registry.invoke(
            "read_code", {"path": "projA/a.txt"}, ctx)
        self.assertFalse(result.ok)
        self.assertIn("CodeBrowser", result.error)

    # ---- update_model ----

    def test_update_model_rejects_unregistered_type(self):
        result = self.registry.invoke(
            "update_model", {"concept_id": "Day2-A", "type": "bogus_type",
                             "source_ref": "t:1"}, self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("未登记", result.error)

    def test_update_model_writes_evidence(self):
        result = self.registry.invoke(
            "update_model", {"concept_id": "Day2-A", "type": "quiz_right",
                             "source_ref": "test:reg:1"}, self.ctx)
        self.assertTrue(result.ok)
        self.assertTrue(result.data["written"])
        model = json.loads(
            (self.docx / "learner_model.json").read_text(encoding="utf-8"))
        evs = model["concepts"]["Day2-A"]["evidence"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["type"], "quiz_right")
        # source_ref 幂等：重复写不产生第二条
        again = self.registry.invoke(
            "update_model", {"concept_id": "Day2-A", "type": "quiz_right",
                             "source_ref": "test:reg:1"}, self.ctx)
        self.assertTrue(again.ok)
        self.assertFalse(again.data["written"])

    # ---- persist_state ----

    def test_persist_state_rejects_unknown_op(self):
        result = self.registry.invoke(
            "persist_state", {"op": "delete_everything"}, self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("白名单", result.error)

    def test_persist_state_rejects_bad_status(self):
        result = self.registry.invoke(
            "persist_state", {"op": "set_unit_status", "unit_id": "A",
                              "status": "bogus"}, self.ctx)
        self.assertFalse(result.ok)

    def test_persist_state_set_unit_status(self):
        # 🟡-4 起 completed 不开放（见 test_arch_fixes_a），此处用 postponed 走通落盘
        result = self.registry.invoke(
            "persist_state", {"op": "set_unit_status", "unit_id": "A",
                              "status": "postponed"}, self.ctx)
        self.assertTrue(result.ok, result.error)
        saved = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["days"]["2"]["units"][0]["status"],
                         "postponed")

    # ---- write_note ----

    def test_write_note_ok(self):
        result = self.registry.invoke(
            "write_note", {"kind": "stuck", "text": "测试卡壳条目"}, self.ctx)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["note"]["kind"], "stuck")
        notes = json.loads(
            (self.docx / "notes.json").read_text(encoding="utf-8"))
        self.assertEqual(len(notes["notes"]), 1)

    def test_write_note_rejects_bad_kind(self):
        result = self.registry.invoke(
            "write_note", {"kind": "bogus", "text": "x"}, self.ctx)
        self.assertFalse(result.ok)

    def test_write_note_rejects_empty_text(self):
        result = self.registry.invoke(
            "write_note", {"kind": "insight", "text": "  "}, self.ctx)
        self.assertFalse(result.ok)

    # ---- 只读工具 ----

    def test_search_notes(self):
        self.registry.invoke(
            "write_note", {"kind": "question", "text": "疑问条目"}, self.ctx)
        result = self.registry.invoke(
            "search_notes", {"kind": "question"}, self.ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["total"], 1)
        self.assertEqual(result.data["notes"][0]["kind"], "question")

    def test_read_model(self):
        result = self.registry.invoke("read_model", {}, self.ctx)
        self.assertTrue(result.ok)
        self.assertIn("concepts", result.data)

    def test_resolve_note_missing_state_store(self):
        ctx = ToolContext(config=self.config)  # 无 state_store
        result = self.registry.invoke("resolve_note", {"id": "x"}, ctx)
        self.assertFalse(result.ok)
        self.assertIn("StateStore", result.error)

    # ---- invoke 异常契约（防假绿核心防线） ----

    def test_invoke_handler_exception_returns_contract(self):
        def boom(ctx, args):
            raise RuntimeError("模拟 handler 爆炸")
        reg = ToolRegistry()
        reg.register(ToolSpec(name="boom", permission=READONLY,
                              description="x", params={}, handler=boom))
        result = reg.invoke("boom", {}, self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("执行异常", result.error)

    # ---- run_build ----

    def test_run_build_missing_state_store(self):
        ctx = ToolContext(config=self.config)  # 无 state_store
        result = self.registry.invoke("run_build", {}, ctx)
        self.assertFalse(result.ok)
        self.assertIn("StateStore", result.error)

    def test_run_build_no_build_files(self):
        # project_dir（tmp）及其一级子目录均无构建文件
        result = self.registry.invoke("run_build", {}, self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("未发现构建文件", result.error)

    def test_run_build_multiple_candidates(self):
        for name in ("day01", "day03"):  # 当日=Day2，均不匹配 day02/day2
            d = self.tmp / name
            d.mkdir()
            (d / "pom.xml").write_text("<xml/>", encoding="utf-8")
        result = self.registry.invoke("run_build", {}, self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("多个可验证目录", result.error)

    def test_run_build_success_passes_params(self):
        (self.tmp / "pom.xml").write_text("<xml/>", encoding="utf-8")
        fake = {"code": 0, "cmd": "mvn test", "seconds": 1.2, "tail": "ok"}
        with mock.patch.object(code_runner, "run_build",
                               return_value=fake) as m:
            result = self.registry.invoke(
                "run_build", {"kind": "test"}, self.ctx)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["kind"], "test")
        self.assertEqual(result.data["code"], 0)
        chosen, tool = m.call_args.args[:2]
        self.assertEqual(tool, "maven")
        self.assertTrue((Path(str(chosen)) / "pom.xml").is_file())
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["kind"], "test")
        self.assertEqual(kwargs["timeout"], 300)   # 夹具未配置 → 默认
        self.assertEqual(kwargs["offline"], False)

    def test_run_build_target_selection(self):
        for name in ("day01", "day03"):
            d = self.tmp / name
            d.mkdir()
            (d / "pom.xml").write_text("<xml/>", encoding="utf-8")
        fake = {"code": 1, "cmd": "mvn compile", "seconds": 0.5, "tail": "err"}
        with mock.patch.object(code_runner, "run_build",
                               return_value=fake) as m:
            result = self.registry.invoke(
                "run_build", {"target": "day03"}, self.ctx)
        self.assertFalse(result.ok)  # 退出码非 0 → ok=False
        chosen = m.call_args.args[0]
        self.assertEqual(Path(str(chosen)).name, "day03")

    # ---- update_model fail-closed（写路径天数不可解析即拒绝） ----

    def test_update_model_rejects_when_day_unresolvable(self):
        ctx = ToolContext(config=self.config)  # 无 state_store → 天数不可解析
        result = self.registry.invoke(
            "update_model", {"concept_id": "Day2-A", "type": "quiz_right",
                             "source_ref": "t:1"}, ctx)
        self.assertFalse(result.ok)
        self.assertIn("无法确定当前天数", result.error)
        self.assertFalse((self.docx / "learner_model.json").exists())

    # ---- M6 实战工坊工具 ----

    def _m6_ctx(self):
        from backend.services.process_mgr import ProcessManager
        from backend.services.workshop_service import WorkshopService
        return ToolContext(config=self.config,
                           workshop=WorkshopService(self.config),
                           process_mgr=ProcessManager(self.config))

    def test_scaffold_create_tool(self):
        result = self.registry.invoke(
            "scaffold_create", {"type": "npm", "name": "tool-demo"},
            self._m6_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["path"], "demo/tool-demo")
        self.assertTrue((self.tmp / "demo" / "tool-demo" / "package.json")
                        .is_file())
        result = self.registry.invoke(
            "scaffold_create", {"type": "ghost", "name": "x"}, self._m6_ctx())
        self.assertFalse(result.ok)
        result = self.registry.invoke(
            "scaffold_create", {"type": "npm", "name": "y"},
            ToolContext(config=self.config))
        self.assertFalse(result.ok)
        self.assertIn("WorkshopService", result.error)

    def test_edit_file_tool(self):
        result = self.registry.invoke(
            "edit_file", {"path": "demo/notes/a.md", "content": "# hi\n"},
            self._m6_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual((self.tmp / "demo" / "notes" / "a.md")
                         .read_text(encoding="utf-8"), "# hi\n")
        result = self.registry.invoke(
            "edit_file", {"path": "projA/a.txt", "content": "hack"},
            self._m6_ctx())
        self.assertFalse(result.ok)  # 非白名单别名
        result = self.registry.invoke(
            "edit_file", {"path": "demo/.env", "content": "K=V"},
            self._m6_ctx())
        self.assertFalse(result.ok)  # 敏感文件
        result = self.registry.invoke(
            "edit_file", {"path": "demo/x", "content": None}, self._m6_ctx())
        self.assertFalse(result.ok)  # content 缺失
        result = self.registry.invoke(
            "edit_file", {"path": "demo/x", "content": "y"},
            ToolContext(config=self.config))
        self.assertFalse(result.ok)
        self.assertIn("WorkshopService", result.error)

    def test_process_tools(self):
        ctx = self._m6_ctx()
        result = self.registry.invoke(
            "process_start",
            {"cwd": str(self.tmp / "projA"),
             "cmd": [sys.executable, "-c",
                     "import time;time.sleep(30)"], "name": "t"},
            ctx)
        self.assertTrue(result.ok, result.error)
        pid_id = result.data["id"]
        try:
            self.assertIn("已启动", result.data["hint"])
            logs = self.registry.invoke(
                "process_logs", {"id": pid_id}, ctx)
            self.assertTrue(logs.ok)
            self.assertEqual(logs.data["status"], "running")
        finally:
            stopped = self.registry.invoke(
                "process_stop", {"id": pid_id}, ctx)
        self.assertTrue(stopped.ok)
        self.assertTrue(stopped.data["stopped"])
        again = self.registry.invoke("process_stop", {"id": pid_id}, ctx)
        self.assertTrue(again.ok)  # 幂等：已停止不报错、不 kill
        for tool in ("process_start", "process_stop", "process_logs"):
            r = self.registry.invoke(
                tool, {"id": "x", "cwd": "d", "cmd": "c"},
                ToolContext(config=self.config))
            self.assertFalse(r.ok)
            self.assertIn("ProcessManager", r.error)

    def test_planner_instruction_lists_m6_tools(self):
        """planner 工具清单自动包含 M6 新工具（schemas 遍历，无需改 planner）。"""
        from backend.engine.planner import PlannerEngine
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.tmp / "session.json")
        text = PlannerEngine(deps).instruction_for(
            SessionContext(mode="code"), "建 demo")
        for name in ("scaffold_create", "edit_file", "process_start",
                     "process_stop", "process_logs"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
