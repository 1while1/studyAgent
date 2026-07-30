"""C-2: .env 注入防护测试。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.services.config_writer import update_env_file


class TestEnvInjection(unittest.TestCase):
    """update_env_file 必须拒绝非法 key 和含换行符的 value。"""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.env_file = self.tmp_path / ".env"
        self.env_file.write_text("EXISTING=old\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    # ── 注入拒绝 ──────────────────────────────────────────

    def test_update_env_rejects_newline_in_value(self):
        with self.assertRaises(ValueError) as ctx:
            update_env_file(
                self.env_file,
                {"KEY": "val\nAUTH_PASSWORD_HASH=evil"},
            )
        self.assertIn("换行符", str(ctx.exception))

    def test_update_env_rejects_carriage_return_in_value(self):
        with self.assertRaises(ValueError) as ctx:
            update_env_file(
                self.env_file,
                {"KEY": "val\rINJECTED=evil"},
            )
        self.assertIn("换行符", str(ctx.exception))

    def test_update_env_rejects_invalid_key_with_space(self):
        with self.assertRaises(ValueError) as ctx:
            update_env_file(
                self.env_file,
                {"KEY WITH SPACE": "val"},
            )
        self.assertIn("非法", str(ctx.exception))

    def test_update_env_rejects_key_with_special_chars(self):
        with self.assertRaises(ValueError):
            update_env_file(
                self.env_file,
                {"KEY;INJECT=1": "val"},
            )

    def test_update_env_rejects_empty_key(self):
        with self.assertRaises(ValueError):
            update_env_file(
                self.env_file,
                {"": "val"},
            )

    def test_update_env_rejects_key_starting_with_digit(self):
        with self.assertRaises(ValueError):
            update_env_file(
                self.env_file,
                {"1BAD_KEY": "val"},
            )

    # ── 正常路径仍然工作 ──────────────────────────────────

    def test_update_env_normal_write(self):
        update_env_file(self.env_file, {"NEW_KEY": "hello"})
        content = self.env_file.read_text(encoding="utf-8")
        self.assertIn("NEW_KEY=hello", content)

    def test_update_env_replaces_existing(self):
        update_env_file(self.env_file, {"EXISTING": "new"})
        content = self.env_file.read_text(encoding="utf-8")
        self.assertIn("EXISTING=new", content)
        self.assertNotIn("EXISTING=old", content)

    def test_update_env_accepts_underscore_key(self):
        update_env_file(self.env_file, {"_PRIVATE_KEY": "abc"})
        content = self.env_file.read_text(encoding="utf-8")
        self.assertIn("_PRIVATE_KEY=abc", content)


if __name__ == "__main__":
    unittest.main()
