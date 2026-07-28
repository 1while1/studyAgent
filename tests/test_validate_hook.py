# -*- coding: utf-8 -*-
"""validate_hook validator 自身异常保护回归测试（W1 审计修复）。

validator 动态加载 resources/hooks/validate_study.py；脚本损坏
（exec 期 SyntaxError/ImportError）或运行期抛错时，异常若穿透
atomic_persist 的 validator 调用，已写入的文件不会回滚（破窗态）。
修复后：validator 自身异常一律转为 (False, 输出)，走既有 not-ok
回滚路径并抛 PersistError。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.hooks import validate_hook
from backend.services.backup_service import BackupService, PersistError


def _fake_config(docx_dir: Path) -> SimpleNamespace:
    """make_validator/BackupService 只用到 docx_dir 与 workspace 两属性。"""
    return SimpleNamespace(
        docx_dir=docx_dir,
        workspace=SimpleNamespace(total_days=25, replica_name="replica"),
    )


class TestValidateHookGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="valhook_"))
        self.hooks = self.tmp / "hooks"
        self.hooks.mkdir()
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        self._orig_hooks_dir = validate_hook.HOOKS_DIR
        validate_hook.HOOKS_DIR = self.hooks

    def tearDown(self):
        validate_hook.HOOKS_DIR = self._orig_hooks_dir
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_script(self, body: str) -> None:
        (self.hooks / "validate_study.py").write_text(body, encoding="utf-8")

    def _validator(self):
        return validate_hook.make_validator(_fake_config(self.docx))

    def test_exec_time_syntax_error_returns_failure(self):
        """脚本 exec 期损坏：返回 (False, ...) 而非抛出。"""
        self._write_script("def main(:\n    pass\n")  # SyntaxError
        ok, output = self._validator()()
        self.assertFalse(ok, "损坏脚本必须判定校验失败")
        self.assertIn("validator 自身异常", output)

    def test_runtime_error_in_main_returns_failure(self):
        """脚本 main 运行期抛错：同样转为 (False, ...)。"""
        self._write_script(
            "def main(docx_dir, total_days, replica_name):\n"
            "    raise RuntimeError('模拟运行期崩溃')\n")
        ok, output = self._validator()()
        self.assertFalse(ok, "运行期崩溃必须判定校验失败")
        self.assertIn("validator 自身异常", output)

    def test_atomic_persist_rolls_back_when_validator_crashes(self):
        """集成：validator 崩溃时 atomic_persist 回滚已写入文件并抛 PersistError。"""
        self._write_script("import no_such_module_xyz\n")  # ImportError at exec
        target = self.docx / "StudyState.json"
        target.write_text('{"current_day": 1}', encoding="utf-8")
        svc = BackupService(_fake_config(self.docx))
        with self.assertRaises(PersistError,
                               msg="validator 崩溃必须经 not-ok 路径抛 PersistError"):
            svc.atomic_persist({target: '{"current_day": 2}'},
                               validator=self._validator())
        self.assertEqual(target.read_text(encoding="utf-8"),
                         '{"current_day": 1}',
                         "validator 崩溃后目标文件必须回滚到写入前内容")


if __name__ == "__main__":
    unittest.main()
