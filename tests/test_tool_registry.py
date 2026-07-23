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

from backend.engine.tool_registry import (READONLY, SANDBOX, WRITE,
                                          ToolContext, build_default_registry)
from backend.services.code_browser import CodeBrowser
from backend.services.config_service import ConfigService
from backend.services.state_store import StateStore

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
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\nsync_mastered = 0.10\n'
            f'[[code_roots]]\nname = "projA"\npath = "{proj.as_posix()}"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
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
        result = self.registry.invoke(
            "persist_state", {"op": "set_unit_status", "unit_id": "A",
                              "status": "completed"}, self.ctx)
        self.assertTrue(result.ok, result.error)
        saved = json.loads(
            (self.docx / "StudyState.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["days"]["2"]["units"][0]["status"],
                         "completed")

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


if __name__ == "__main__":
    unittest.main()
