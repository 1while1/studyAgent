"""workshop_service（M6 实战工坊写路径）测试。

断言核心：写白名单（demo/replica 可写，原项目只读）、脚手架复制与 {{name}}
替换、demo 代码根自动注册（带 workspace 归属）、路径穿越/敏感文件拒绝、
atomic_write 回读一致。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import ConfigService
from backend.services.workshop_service import WorkshopError, WorkshopService


class TestWorkshop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="workshop_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        self.demo = self.tmp / "demo"
        self.proj = self.tmp / "projA"
        self.proj.mkdir()
        (self.proj / "a.txt").write_text("hello", encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            f'[[code_roots]]\nname = "projA"\npath = "{self.proj.as_posix()}"\n'
            'workspace = "t"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.proj.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n'
            f'demo_dir = "{self.demo.as_posix()}"\n'
            'replica_name = ""\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.svc = WorkshopService(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 脚手架 ----

    def test_scaffold_types(self):
        types = {t["type"] for t in self.svc.scaffold_types()}
        self.assertIn("npm", types)
        self.assertIn("maven-module", types)
        self.assertIn("gradle", types)

    def test_scaffold_create_npm(self):
        r = self.svc.scaffold_create("npm", "my-demo")
        self.assertEqual(r["path"], "demo/my-demo")
        self.assertGreaterEqual(r["files"], 6)
        pkg = json.loads((self.demo / "my-demo" / "package.json")
                         .read_text(encoding="utf-8"))
        self.assertEqual(pkg["name"], "my-demo")  # {{name}} 已替换
        html = (self.demo / "my-demo" / "src" / "index.html") \
            .read_text(encoding="utf-8")
        self.assertNotIn("{{name}}", html)
        # demo 代码根自动注册（带 workspace 归属）
        roots = {x["name"]: x for x in self.config.code_roots}
        self.assertIn("demo", roots)
        self.assertEqual(roots["demo"]["workspace"], "t")
        # 幂等：再次创建别的 demo 不重复注册
        self.svc.scaffold_create("npm", "second")
        names = [x["name"] for x in self.config.code_roots]
        self.assertEqual(names.count("demo"), 1)

    def test_scaffold_create_maven_and_gradle(self):
        r1 = self.svc.scaffold_create("maven-module", "j-demo")
        self.assertTrue((self.demo / "j-demo" / "pom.xml").is_file())
        self.assertIn("<artifactId>j-demo</artifactId>",
                      (self.demo / "j-demo" / "pom.xml")
                      .read_text(encoding="utf-8"))
        r2 = self.svc.scaffold_create("gradle", "g-demo")
        self.assertTrue((self.demo / "g-demo" / "build.gradle").is_file())
        self.assertTrue(r1["files"] > 0 and r2["files"] > 0)

    def test_scaffold_create_rejects(self):
        with self.assertRaises(WorkshopError):
            self.svc.scaffold_create("npm", "")          # 空名
        with self.assertRaises(WorkshopError):
            self.svc.scaffold_create("npm", "..")        # 穿越
        with self.assertRaises(WorkshopError):
            self.svc.scaffold_create("npm", "a/b")       # 含分隔符
        with self.assertRaises(WorkshopError):
            self.svc.scaffold_create("no-such", "x")     # 未知类型
        self.svc.scaffold_create("npm", "dup")
        with self.assertRaises(WorkshopError):
            self.svc.scaffold_create("npm", "dup")       # 重名非空

    # ---- 写白名单（别名路径） ----

    def test_resolve_write_whitelist(self):
        t = self.svc.resolve_write("demo/x/y.py")
        self.assertEqual(t, (self.demo / "x" / "y.py").resolve())
        with self.assertRaises(WorkshopError):
            self.svc.resolve_write("demo/../escape.py")   # 越界
        with self.assertRaises(WorkshopError):
            self.svc.resolve_write("project/a.txt")       # 非白名单别名
        with self.assertRaises(WorkshopError):
            self.svc.resolve_write("demo/")               # 缺相对路径
        with self.assertRaises(WorkshopError):
            self.svc.resolve_write("demo/.env")           # 敏感文件
        with self.assertRaises(WorkshopError):
            self.svc.resolve_write("")                    # 空路径

    def test_write_alias_atomic(self):
        r = self.svc.write_alias("demo/note/a.md", "# 标题\n内容\n")
        self.assertGreater(r["bytes"], 0)
        back = (self.demo / "note" / "a.md").read_text(encoding="utf-8")
        self.assertEqual(back, "# 标题\n内容\n")

    def test_write_alias_replica(self):
        rep = self.tmp / "replica"
        rep.mkdir()
        self.svc.replica_root = lambda: rep  # 测试隔离：replica 根注入 tmp
        r = self.svc.write_alias("replica/day01/x.py", "print('ok')\n")
        self.assertTrue((rep / "day01" / "x.py").is_file())
        self.assertEqual(r["path"], "replica/day01/x.py")

    # ---- UI 保存入口（代码根名） ----

    def test_save_via_root(self):
        self.svc.scaffold_create("npm", "s-demo")  # 注册 demo 代码根
        r = self.svc.save_via_root("demo", "s-demo/src/app.js",
                                   "// edited\n")
        self.assertEqual(r["root"], "demo")
        back = (self.demo / "s-demo" / "src" / "app.js") \
            .read_text(encoding="utf-8")
        self.assertEqual(back, "// edited\n")
        # 原项目代码根只读
        with self.assertRaises(WorkshopError):
            self.svc.save_via_root("projA", "a.txt", "hack")
        # 未配置的根
        with self.assertRaises(WorkshopError):
            self.svc.save_via_root("ghost", "x", "y")
        # 穿越
        with self.assertRaises(WorkshopError):
            self.svc.save_via_root("demo", "../evil.txt", "x")

    # ---- editable 标记 ----

    def test_editable(self):
        self.svc.scaffold_create("npm", "e-demo")
        self.assertTrue(self.svc.editable("demo", "e-demo/src/app.js"))
        self.assertFalse(self.svc.editable("projA", "a.txt"))     # 原项目只读
        self.assertFalse(self.svc.editable("demo", ".env"))       # 敏感文件
        self.assertFalse(self.svc.editable("demo", "../x"))       # 越界
        self.assertFalse(self.svc.editable("ghost", "x"))         # 未知根


if __name__ == "__main__":
    unittest.main()
