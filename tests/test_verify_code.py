"""[验证代码]（P1-1 编码验证闭环）测试：构建工具检测 / 验证根回退 / handler 流程。"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.commands.verify_code import VerifyCodeHandler
from backend.services import code_runner
from backend.services.config_service import ConfigService


def _make_config(tmp: Path, project_dir: Path) -> ConfigService:
    docx = tmp / "docx"
    (docx / "StudyMemory").mkdir(parents=True, exist_ok=True)
    (docx / "StudyState.json").write_text(json.dumps({
        "current_day": 1, "overall_completion_percentage": 0,
        "days": {"1": {"date": "2026-07-22", "units": []}},
    }, ensure_ascii=False), encoding="utf-8")
    settings = tmp / "settings.toml"
    settings.write_text(
        f'docx_dir = "{docx.as_posix()}"\n'
        'active_workspace = "t"\n'
        '[[workspaces]]\nslug = "t"\ntitle = "t"\n'
        f'docx_dir = "{docx.as_posix()}"\n'
        f'project_dir = "{project_dir.as_posix()}"\n'
        f'session_path = "{(tmp / "s.json").as_posix()}"\n'
        'replica_name = "t-replica"\n',
        encoding="utf-8")
    return ConfigService(settings)


class FakeDeps:
    """handler 需要的最小 deps（不碰落盘/LLM）。"""

    def __init__(self, config):
        self.config = config
        from backend.services.state_store import StateStore
        self.state_store = StateStore(config)


class TestDetectBuildTool(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_maven(self):
        (self.tmp / "pom.xml").write_text("<xml/>", encoding="utf-8")
        self.assertEqual(code_runner.detect_build_tool(self.tmp), "maven")

    def test_gradle(self):
        (self.tmp / "build.gradle").write_text("apply plugin: 'java'",
                                               encoding="utf-8")
        self.assertEqual(code_runner.detect_build_tool(self.tmp), "gradle")

    def test_npm(self):
        (self.tmp / "package.json").write_text("{}", encoding="utf-8")
        self.assertEqual(code_runner.detect_build_tool(self.tmp), "npm")

    def test_none(self):
        self.assertIsNone(code_runner.detect_build_tool(self.tmp))


class TestVerifyCodeHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verifyh_"))
        self.proj = self.tmp / "proj"
        self.proj.mkdir()
        (self.proj / "pom.xml").write_text("<xml/>", encoding="utf-8")
        self.config = _make_config(self.tmp, self.proj)
        self.deps = FakeDeps(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fail_fast_ok_with_build_file(self):
        h = VerifyCodeHandler()
        self.assertIsNone(h.fail_fast(self.deps, None, ""))

    def test_fail_fast_no_build_file(self):
        (self.proj / "pom.xml").unlink()
        h = VerifyCodeHandler()
        stop = h.fail_fast(self.deps, None, "")
        self.assertIn("未发现构建文件", stop)

    def test_run_compile_with_mocked_runner(self):
        h = VerifyCodeHandler()
        fake = {"cmd": "mvn -q -DskipTests compile", "code": 1,
                "tail": "ERROR: 找不到符号", "seconds": 3.2, "timed_out": False}
        with mock.patch.object(code_runner, "run_build", return_value=fake) as m:
            result = h.run(self.deps, None, "")
        self.assertEqual(m.call_args.kwargs["kind"], "compile")
        self.assertIn("❌ 失败", result.messages[0])
        self.assertIn("找不到符号", result.llm_instruction)
        self.assertEqual(result.sop_card, "")

    def test_run_test_kind_by_args(self):
        h = VerifyCodeHandler()
        fake = {"cmd": "mvn -q test", "code": 0, "tail": "OK",
                "seconds": 9.9, "timed_out": False}
        with mock.patch.object(code_runner, "run_build", return_value=fake) as m:
            result = h.run(self.deps, None, "测试")
        self.assertEqual(m.call_args.kwargs["kind"], "test")
        self.assertIn("✅ 成功", result.messages[0])

    def test_verify_root_prefers_replica(self):
        # replica 目录（WEB_ROOT 同级 / replica_name）存在时优先
        handler = VerifyCodeHandler()
        root = handler.verify_root(self.deps)
        # 测试环境不存在 t-replica → 回退 project_dir
        self.assertEqual(root, self.proj)


if __name__ == "__main__":
    unittest.main()
