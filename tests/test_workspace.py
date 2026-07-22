"""工作区机制测试：RepoScanner / Workspace 合成与过滤 / DocInitializer（MockLLM 全流程）。"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.workspace import Workspace
from backend.llm.mock import MockLLM
from backend.services.config_service import ConfigService, WEB_ROOT
from backend.services.config_writer import update_code_roots, update_workspaces
from backend.services.doc_initializer import DocInitializer, InitError
from backend.services.repo_scanner import scan
from backend.services.study_plan import parse_day_text

PROJECT_MD = """# 项目架构

## 项目概述
测试项目。

## 技术栈
| 类别 | 技术 |
|---|---|
| 语言 | Python |

## 模块结构
| 模块 | 职责 |
|---|---|
| core | 核心逻辑 |

## 核心数据流
输入 → 处理 → 输出。
""" + "补充说明。" * 60


def make_study_md(days: int, replica: str = "test-replica",
                  detail_days: int | None = None) -> str:
    """detail_days=None 时全部细化；否则仅前 detail_days 天细化，其余粗纲。"""
    if detail_days is None:
        detail_days = days
    parts = ["当前天数：Day 1", "", "整体完成度：0%", ""]
    for d in range(1, days + 1):
        parts += [f"## Day {d} | 第{d}天主题", "**目标**：当日目标"]
        if d <= detail_days:
            parts += [
                "1. [ ] 单元A：概念学习（预计 40min）",
                "   - 文档：无",
                "2. [ ] 单元B：源码精读（预计 40min）",
                "   - 文档：无",
                f"**编码目标**：{replica} 完成 当日模块",
                "**推荐论文**：《Test Paper》 — 重点读 Section 1",
                '**面试话术目标**：产出"当日话题"的 30 秒/2 分钟版回答',
            ]
        parts.append("")
    return "\n".join(parts)


class TestRepoScanner(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="scan_"))
        proj = self.tmp / "proj"
        (proj / "src" / "core").mkdir(parents=True)
        (proj / "src" / "core" / "main.py").write_text("x = 1", encoding="utf-8")
        (proj / "pom.xml").write_text("<project><!-- deps --></project>",
                                      encoding="utf-8")
        (proj / "README.md").write_text("# Test Project\n你好", encoding="utf-8")
        nm = proj / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("x", encoding="utf-8")
        self.proj = proj

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_profile_contents(self):
        profile = scan(self.proj)
        self.assertIn("src/", profile)
        self.assertIn("main.py", profile)
        self.assertIn("pom.xml", profile)
        self.assertIn("Test Project", profile)

    def test_skip_dirs(self):
        self.assertNotIn("node_modules", scan(self.proj))

    def test_missing_dir(self):
        with self.assertRaises(FileNotFoundError):
            scan(self.tmp / "nope")

    def test_entry_detection(self):
        # 已有 src/core/main.py → 入口识别；再补一个 SpringBoot 启动类
        boot = self.proj / "engine" / "src" / "main" / "java" / "com" / "x"
        boot.mkdir(parents=True)
        (boot / "EngineApplication.java").write_text(
            "@SpringBootApplication\npublic class EngineApplication {}",
            encoding="utf-8")
        profile = scan(self.proj)
        self.assertIn("入口识别", profile)
        self.assertIn("src/core/main.py", profile)
        self.assertIn("EngineApplication.java", profile)

    def test_module_dependency_edges(self):
        (self.proj / "engine").mkdir(exist_ok=True)
        (self.proj / "web").mkdir(exist_ok=True)
        (self.proj / "engine" / "pom.xml").write_text(
            "<project><artifactId>engine</artifactId></project>", encoding="utf-8")
        (self.proj / "web" / "pom.xml").write_text(
            "<project><dependency>engine</dependency></project>", encoding="utf-8")
        profile = scan(self.proj)
        self.assertIn("模块依赖线索", profile)
        self.assertIn("web → engine", profile)
        self.assertNotIn("engine → web", profile)

    def test_key_configs(self):
        cfg = self.proj / "src" / "main" / "resources"
        cfg.mkdir(parents=True)
        (cfg / "application.yml").write_text("server:\n  port: 8080",
                                             encoding="utf-8")
        profile = scan(self.proj)
        self.assertIn("关键配置", profile)
        self.assertIn("application.yml", profile)


class TestWorkspaceConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wscfg_"))
        self.settings = self.tmp / "settings.toml"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_legacy_synthesis(self):
        self.settings.write_text('total_days = 21\ndocx_dir = "../docx"\n',
                                 encoding="utf-8")
        cfg = ConfigService(self.settings)
        ws = cfg.workspace
        self.assertEqual(ws.slug, "default")
        self.assertEqual(ws.total_days, 21)
        self.assertEqual(ws.docx_dir, (WEB_ROOT / "../docx").resolve())

    def test_roundtrip_and_root_filter(self):
        self.settings.write_text(
            'active_workspace = "a"\n'
            '[[code_roots]]\nname = "r1"\npath = "/p1"\nworkspace = "a"\n'
            '[[code_roots]]\nname = "r2"\npath = "/p2"\nworkspace = "b"\n'
            '[[workspaces]]\nslug = "a"\ntitle = "A"\n'
            '[[workspaces]]\nslug = "b"\ntitle = "B"\ntotal_days = 10\n',
            encoding="utf-8")
        cfg = ConfigService(self.settings)
        self.assertEqual(cfg.workspace.slug, "a")
        self.assertEqual([r["name"] for r in cfg.code_roots], ["r1"])
        # 切换后根过滤跟着变
        update_workspaces(self.settings, cfg.data["workspaces"], active="b")
        cfg.reload()
        self.assertEqual(cfg.workspace.slug, "b")
        self.assertEqual(cfg.workspace.total_days, 10)
        self.assertEqual([r["name"] for r in cfg.code_roots], ["r2"])
        # code_roots 写入保留 workspace 字段
        update_code_roots(self.settings,
                          [dict(r) for r in cfg.data["code_roots"]])
        cfg.reload()
        self.assertEqual([r["name"] for r in cfg.code_roots], ["r2"])


class TestDocInitializer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="init_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ws(self, days=2) -> Workspace:
        return Workspace.from_dict({
            "slug": "test",
            "title": "Test 项目面试冲刺",
            "goal": "测试目标",
            "docx_dir": str(self.tmp / "docx"),
            "project_dir": str(self.tmp),
            "session_path": str(self.tmp / "session.json"),
            "total_days": days,
            "replica_name": "test-replica",
        }, WEB_ROOT)

    def test_full_initialize(self):
        ws = self._ws(days=2)
        llm = MockLLM(script=[PROJECT_MD, make_study_md(2)])
        report = DocInitializer(llm).initialize(ws, "扫描画像")
        names = report["files"]
        for expected in ["StudyState.json", "Project.md", "Study.md",
                         "ReplicaPlan.md", "DocIndex.md", "InterviewQA.md"]:
            self.assertIn(expected, names)
            self.assertTrue((ws.docx_dir / expected).exists())
        state = json.loads((ws.docx_dir / "StudyState.json").read_text("utf-8"))
        self.assertEqual(state["current_day"], 1)
        self.assertEqual(state["total_days"], 2)
        self.assertTrue((ws.docx_dir / "StudyMemory").is_dir())
        # Study.md 逐天可解析
        text = (ws.docx_dir / "Study.md").read_text("utf-8")
        for d in (1, 2):
            self.assertTrue(parse_day_text(text, d, "test-replica")["units"])

    def test_retry_on_invalid_study_md(self):
        ws = self._ws(days=2)
        # 第一次 Study.md 缺 Day 2 → 校验失败 → 带错重试成功
        llm = MockLLM(script=[PROJECT_MD, "当前天数：Day 1\n\n## Day 1 | 只有一天\n**目标**：x\n",
                              make_study_md(2)])
        DocInitializer(llm).initialize(ws, "扫描画像")
        self.assertTrue((ws.docx_dir / "Study.md").exists())

    def test_retry_exhausted_raises(self):
        ws = self._ws(days=2)
        llm = MockLLM(script=[PROJECT_MD, "垃圾输出", "还是垃圾"])
        with self.assertRaises(InitError):
            DocInitializer(llm).initialize(ws, "扫描画像")
        self.assertFalse((ws.docx_dir / "Study.md").exists())

    def test_refresh_project_md(self):
        ws = self._ws()
        ws.docx_dir.mkdir(parents=True)
        llm = MockLLM(script=[PROJECT_MD])
        text = DocInitializer(llm).refresh_project_md(ws, "画像")
        self.assertIn("模块结构", text)
        self.assertEqual((ws.docx_dir / "Project.md").read_text("utf-8"), text)

    def test_coarse_outline_accepted(self):
        # 增量式：5 天计划只细化前 3 天，4-5 天仅标题+目标 → 校验通过
        ws = self._ws(days=5)
        llm = MockLLM(script=[PROJECT_MD, make_study_md(5, detail_days=3)])
        DocInitializer(llm).initialize(ws, "扫描画像")
        text = (ws.docx_dir / "Study.md").read_text("utf-8")
        for d in (1, 2, 3):
            self.assertTrue(parse_day_text(text, d, "test-replica")["units"])
        self.assertIn("## Day 5 |", text)

    def test_coarse_missing_header_rejected(self):
        # 粗纲天缺标题 → 校验失败重试后仍失败 → InitError
        ws = self._ws(days=5)
        bad = make_study_md(5, detail_days=3).replace("## Day 5 | 第5天主题", "")
        llm = MockLLM(script=[PROJECT_MD, bad, bad])
        with self.assertRaises(InitError):
            DocInitializer(llm).initialize(ws, "扫描画像")

    def test_doc_path_must_exist(self):
        # P0-3：细化单元「文档」字段引用不存在的路径 → 校验失败
        ws = self._ws(days=2)
        bad = make_study_md(2).replace("   - 文档：无",
                                       "   - 文档：no/such/File.java", 1)
        llm = MockLLM(script=[PROJECT_MD, bad, bad])
        with self.assertRaises(InitError) as ctx:
            DocInitializer(llm).initialize(ws, "扫描画像")
        self.assertIn("文档路径不存在", str(ctx.exception))

    def test_doc_path_exists_passes(self):
        # P0-3：路径真实存在（文件或目录）→ 通过
        (self.tmp / "src").mkdir(exist_ok=True)
        (self.tmp / "src" / "main.py").write_text("print(1)", encoding="utf-8")
        ws = self._ws(days=2)
        good = make_study_md(2).replace("   - 文档：无",
                                        "   - 文档：src/main.py", 1)
        llm = MockLLM(script=[PROJECT_MD, good])
        DocInitializer(llm).initialize(ws, "扫描画像")
        self.assertTrue((ws.docx_dir / "Study.md").exists())


if __name__ == "__main__":
    unittest.main()
