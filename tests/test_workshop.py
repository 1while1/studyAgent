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

    # ---- M6 审查修复回归 ----

    def test_scaffold_preserves_other_workspace_roots(self):
        """R1：scaffold 注册代码根不得丢别的工作区的根（全量未过滤基线）。"""
        settings = self.tmp / "settings2.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            f'[[code_roots]]\nname = "otherRoot"\n'
            f'path = "{self.proj.as_posix()}"\nworkspace = "other"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.proj.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s2.json").as_posix()}"\n'
            f'demo_dir = "{(self.tmp / "demo2").as_posix()}"\n'
            'replica_name = ""\n'
            '[[workspaces]]\nslug = "other"\n'
            f'docx_dir = "{(self.tmp / "docx2").as_posix()}"\n'
            f'project_dir = "{self.proj.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s3.json").as_posix()}"\n',
            encoding="utf-8")
        cfg = ConfigService(settings)
        WorkshopService(cfg).scaffold_create("npm", "multi-demo")
        names = [r["name"] for r in cfg.data.get("code_roots", [])]
        self.assertIn("otherRoot", names)   # 别的工作区根保住
        self.assertIn("demo", names)        # 新注册的在
        ws = {r["name"]: r for r in cfg.data.get("code_roots", [])}
        self.assertEqual(ws["otherRoot"]["workspace"], "other")
        self.assertEqual(ws["demo"]["workspace"], "t")

    def test_scaffold_create_retry_after_failure(self):
        """A1：注册失败不留残骸，可直接重入。"""
        from unittest import mock
        from backend.services import config_writer
        orig = config_writer.update_code_roots
        calls = {"n": 0}

        def flaky(path, roots):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IOError("模拟写盘失败")
            return orig(path, roots)

        with mock.patch.object(config_writer, "update_code_roots", flaky):
            with self.assertRaises(Exception):
                self.svc.scaffold_create("npm", "retry-demo")
        # 失败未产生非空目录（先注册后复制）→ 重试成功
        self.assertFalse((self.demo / "retry-demo").exists())
        r = self.svc.scaffold_create("npm", "retry-demo")
        self.assertEqual(r["path"], "demo/retry-demo")
        self.assertTrue((self.demo / "retry-demo" / "package.json").is_file())


class TestWorkshopRoutes(unittest.TestCase):
    """路由级（routes.py 直接调用）：写路径 API 的 ok/error 契约。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="workshop_rt_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        self.demo = self.tmp / "demo"
        self.proj = self.tmp / "projA"
        self.proj.mkdir()
        (self.proj / "a.txt").write_text("hello", encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
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

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _init_routes(self):
        from backend.api import routes
        from backend.engine.orchestrator import ChatOrchestrator
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.tmp / "session.json")
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        return routes

    def test_demo_scaffold_api(self):
        routes = self._init_routes()
        r = routes.demo_scaffolds()
        self.assertTrue(r["ok"])
        self.assertIn("npm", {s["type"] for s in r["scaffolds"]})
        r = routes.demo_scaffold({"type": "npm", "name": "api-demo"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["path"], "demo/api-demo")
        r = routes.demo_scaffold({"type": "npm", "name": "api-demo"})
        self.assertFalse(r["ok"])  # 重名
        r = routes.demo_scaffold({"type": "ghost", "name": "x"})
        self.assertFalse(r["ok"])  # 未知类型

    def test_code_save_api_whitelist(self):
        routes = self._init_routes()
        routes.demo_scaffold({"type": "npm", "name": "s-demo"})
        r = routes.code_save({"root": "demo", "path": "s-demo/src/app.js",
                              "content": "// api edited\n"})
        self.assertTrue(r["ok"])
        self.assertEqual((self.demo / "s-demo" / "src" / "app.js")
                         .read_text(encoding="utf-8"), "// api edited\n")
        r = routes.code_save({"root": "projA", "path": "a.txt",
                              "content": "hack"})
        self.assertFalse(r["ok"])  # 原项目只读
        self.assertEqual((self.proj / "a.txt").read_text(encoding="utf-8"),
                         "hello")  # 未被改动
        r = routes.code_save({"root": "", "path": "x", "content": "y"})
        self.assertFalse(r["ok"])  # 参数缺失

    def test_code_file_editable_flag(self):
        routes = self._init_routes()
        routes.demo_scaffold({"type": "npm", "name": "e-demo"})
        r = routes.code_file("demo", "e-demo/src/app.js")
        self.assertTrue(r["ok"])
        self.assertTrue(r["editable"])
        r = routes.code_file("projA", "a.txt")
        self.assertTrue(r["ok"])
        self.assertFalse(r["editable"])
        r = routes.code_file("demo", "e-demo/nope.js")
        self.assertFalse(r["ok"])  # 不存在仍走原错误契约

    def test_code_save_bad_types_no_500(self):
        """Y4：非字符串参数也走 ok=False 契约，不冒 AttributeError 500。"""
        routes = self._init_routes()
        r = routes.code_save({"root": 123, "path": "x", "content": "y"})
        self.assertFalse(r["ok"])
        r = routes.code_save({"root": None, "path": "x", "content": "y"})
        self.assertFalse(r["ok"])

    def test_code_roots_add_delete_preserve_other_workspaces(self):
        """R1：路由增删代码根基于全量未过滤清单，别的工作区根不受影响。"""
        settings = self.tmp / "settings3.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            f'[[code_roots]]\nname = "otherRoot"\n'
            f'path = "{self.proj.as_posix()}"\nworkspace = "other"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.proj.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s4.json").as_posix()}"\n'
            f'demo_dir = "{self.demo.as_posix()}"\n'
            'replica_name = ""\n'
            '[[workspaces]]\nslug = "other"\n'
            f'docx_dir = "{(self.tmp / "docx2").as_posix()}"\n'
            f'project_dir = "{self.proj.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s5.json").as_posix()}"\n',
            encoding="utf-8")
        from backend.api import routes as rt
        from backend.engine.orchestrator import ChatOrchestrator
        from tests.test_flows import make_deps
        cfg = ConfigService(settings)
        deps = make_deps(cfg, self.tmp / "s6.json")
        orch = ChatOrchestrator(cfg, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        rt.init(deps, orch)
        r = rt.add_code_root({"name": "newRoot", "path": str(self.proj)})
        self.assertTrue(r["ok"], r.get("error"))
        names = [x["name"] for x in cfg.data.get("code_roots", [])]
        self.assertIn("otherRoot", names)
        self.assertIn("newRoot", names)
        r = rt.delete_code_root({"name": "newRoot"})
        self.assertTrue(r["ok"], r.get("error"))
        names = [x["name"] for x in cfg.data.get("code_roots", [])]
        self.assertIn("otherRoot", names)       # 别的工作区根保住
        self.assertNotIn("newRoot", names)


if __name__ == "__main__":
    unittest.main()
