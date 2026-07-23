"""validate_study.py 的 M3/M4 JSON schema 校验（check_json_schemas）测试。"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import HOOKS_DIR


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "validate_study", HOOKS_DIR / "validate_study.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestJsonSchemas(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vschema_"))
        self.mod = _load_module()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self) -> list[str]:
        self.mod.errors, self.mod.warnings = [], []
        self.mod.check_json_schemas(str(self.tmp))
        return self.mod.errors

    def _write(self, name: str, data):
        (self.tmp / name).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_missing_files_skipped(self):
        self.assertEqual(self._run(), [])

    def test_valid_files_pass(self):
        self._write("concepts.json", {"schema_version": 1, "concepts": {
            "Day1-A": {"id": "Day1-A", "title": "x", "prerequisites": [],
                       "materials": [], "code_refs": []}}})
        self._write("learner_model.json", {"schema_version": 1, "concepts": {
            "Day1-A": {"title": "x", "mastery": 0.1, "evidence": [
                {"type": "quiz_right", "source_ref": "r", "delta": 0.1,
                 "ts": "2026-01-01"}],
                "last_review_day": 1, "review_due": [2]}}})
        self._write("notes.json", {"schema_version": 1, "notes": [
            {"id": "n-1", "kind": "stuck", "text": "x", "status": "open",
             "concept_id": "", "needs_review": True, "source_ref": "r",
             "created_day": 1, "merged_into": None}]})
        self.assertEqual(self._run(), [])

    def test_bad_schema_version(self):
        self._write("notes.json", {"schema_version": 2, "notes": []})
        self.assertTrue(any("schema_version" in e for e in self._run()))

    def test_bad_note_fields(self):
        self._write("notes.json", {"schema_version": 1, "notes": [
            {"id": "n-1", "kind": "bad", "text": "", "status": "weird"},
            {"id": "n-1", "kind": "stuck", "text": "x", "status": "open",
             "source_ref": "r"},
        ]})
        errs = self._run()
        self.assertTrue(any("invalid kind" in e for e in errs))
        self.assertTrue(any("text empty" in e for e in errs))
        self.assertTrue(any("invalid status" in e for e in errs))
        self.assertTrue(any("duplicate" in e for e in errs))
        self.assertTrue(any("source_ref" in e for e in errs))

    def test_bad_model_evidence(self):
        self._write("learner_model.json", {"schema_version": 1, "concepts": {
            "Day1-A": {"evidence": [{"type": "quiz_right"}]}}})
        self.assertTrue(any("missing" in e for e in self._run()))

    def test_bad_concepts_entry(self):
        self._write("concepts.json", {"schema_version": 1, "concepts": {
            "Day1-A": {"id": "Day1-A", "prerequisites": "not-a-list"}}})
        self.assertTrue(any("prerequisites" in e for e in self._run()))

    def test_unparseable_json(self):
        (self.tmp / "notes.json").write_text("{bad json", encoding="utf-8")
        self.assertTrue(any("parse failed" in e for e in self._run()))


if __name__ == "__main__":
    unittest.main()
