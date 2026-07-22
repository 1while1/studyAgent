"""代码引用解析（CodeBrowser.resolve）测试：根前缀 / 直接相对 / 后缀搜索 / 防护。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.code_browser import CodeBrowser
from backend.services.config_service import ConfigService


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="resolve_"))
        projA = self.tmp / "projA"
        (projA / "infra-ai").mkdir(parents=True)
        (projA / "infra-ai" / "pom.xml").write_text("<xml/>", encoding="utf-8")
        (projA / "README.md").write_text("hi", encoding="utf-8")
        core = projA / "app" / "core"
        core.mkdir(parents=True)
        (core / "prompt_manager.py").write_text("x = 1", encoding="utf-8")
        # 排除目录：node_modules 里的文件不应被索引命中
        nm = projA / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("x", encoding="utf-8")
        projB = self.tmp / "projB"
        projB.mkdir()
        (projB / "pom.xml").write_text("<xml/>", encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(
            f'[[code_roots]]\nname = "projA"\npath = "{projA.as_posix()}"\n\n'
            f'[[code_roots]]\nname = "projB"\npath = "{projB.as_posix()}"\n',
            encoding="utf-8")
        self.cb = CodeBrowser(ConfigService(settings))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_root_prefixed(self):
        self.assertEqual(self.cb.resolve("projA/infra-ai/pom.xml"),
                         {"root": "projA", "path": "infra-ai/pom.xml"})

    def test_direct_relative(self):
        self.assertEqual(self.cb.resolve("infra-ai/pom.xml"),
                         {"root": "projA", "path": "infra-ai/pom.xml"})

    def test_suffix_search(self):
        self.assertEqual(self.cb.resolve("core/prompt_manager.py"),
                         {"root": "projA", "path": "app/core/prompt_manager.py"})
        self.assertEqual(self.cb.resolve("prompt_manager.py"),
                         {"root": "projA", "path": "app/core/prompt_manager.py"})

    def test_ambiguous_picks_shortest(self):
        hit = self.cb.resolve("pom.xml")
        self.assertEqual(hit, {"root": "projB", "path": "pom.xml"})

    def test_backtick_and_line_suffix_stripped(self):
        self.assertEqual(self.cb.resolve("`projA/infra-ai/pom.xml:L4-L11`"),
                         {"root": "projA", "path": "infra-ai/pom.xml"})

    def test_not_found(self):
        self.assertIsNone(self.cb.resolve("no/such/file.java"))

    def test_skip_dirs_excluded(self):
        self.assertIsNone(self.cb.resolve("index.js"))

    def test_traversal_rejected(self):
        self.assertIsNone(self.cb.resolve("../settings.toml"))


if __name__ == "__main__":
    unittest.main()
