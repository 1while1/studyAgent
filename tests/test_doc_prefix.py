# -*- coding: utf-8 -*-
"""G1 验收修复批：LLM 生成单元「文档」路径误带项目目录名前缀的规范化。

根因：项目画像目录树根行带项目目录名（如 `temp_tinyrag/`），LLM 抄路径时带上
前缀，而 check_unit_docs 以 project_dir 为根校验 → 初始化/滚动细化必失败
（G1 验收 1.2 真实命中）。修复：strip_project_doc_prefix 落盘前规范化 +
prompt 契约加固。本文件锁定纯函数行为与 initializer/end_day 两处接线。
"""

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.workspace import Workspace
from backend.engine.commands.base import Deps
from backend.engine.commands.end_day import EndDayHandler
from backend.engine.hooks.pipeline import HookPipeline
from backend.engine.prompt_builder import PromptBuilder
from backend.engine.quiz_engine import QuizEngine
from backend.engine.session_store import SessionStore
from backend.engine.stage_machine import StageMachine
from backend.llm.mock import MockLLM
from backend.services.backup_service import BackupService
from backend.services.config_service import ConfigService, WEB_ROOT
from backend.services.doc_initializer import DocInitializer
from backend.services.memory_store import MemoryStore
from backend.services.state_store import StateStore
from backend.services.study_plan import (StudyPlanStore,
                                         strip_project_doc_prefix)
from backend.services.template_service import TemplateService


class TestStripDocPrefix(unittest.TestCase):
    def test_strip_single(self):
        text = "   - 文档：temp_tinyrag/pom.xml"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"),
                         "   - 文档：pom.xml")

    def test_strip_multi_token_mixed(self):
        text = "   - 文档：temp_tinyrag/a.py, b/c.py、temp_tinyrag/x"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"),
                         "   - 文档：a.py, b/c.py, x")

    def test_no_doc_line_untouched(self):
        text = "## Day 1 | 主题\n**目标**：x\ntemp_tinyrag/pom.xml 出现在正文不动"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"), text)

    def test_descriptive_text_prefix_stripped_too(self):
        # 描述性文字带前缀同样剥前缀；注意剥后的文字（如「根目录及所有子模块 pom.xml」）
        # 仍会被 extract_doc_paths 当路径 token 提取并校验失败（靠 LLM 重试救）——
        # 剥前剥后行为一致，规范化对此类输入既不修复也不恶化
        text = "   - 文档：onecoupon/ 根目录及所有子模块 pom.xml"
        out = strip_project_doc_prefix(text, "onecoupon")
        self.assertEqual(out, "   - 文档：根目录及所有子模块 pom.xml")
        from backend.services.study_plan import extract_doc_paths
        self.assertEqual(extract_doc_paths("根目录及所有子模块 pom.xml"),
                         ["根目录及所有子模块 pom.xml"])

    def test_backtick_wrapped(self):
        text = "   - 文档：`temp_tinyrag/pom.xml`"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"),
                         "   - 文档：pom.xml")

    def test_clean_path_and_empty_name_untouched(self):
        text = "   - 文档：engine/pom.xml"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"), text)
        self.assertEqual(strip_project_doc_prefix(text, ""), text)

    def test_double_prefix(self):
        text = "   - 文档：temp_tinyrag/temp_tinyrag/pom.xml"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"),
                         "   - 文档：pom.xml")

    def test_multiple_doc_lines(self):
        text = ("1. [ ] 单元A：甲（预计 40min）\n"
                "   - 文档：temp_tinyrag/a.py\n"
                "2. [ ] 单元B：乙（预计 40min）\n"
                "   - 文档：b/c.py\n"
                "**编码目标**：x 完成 y")
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"),
                         "1. [ ] 单元A：甲（预计 40min）\n"
                         "   - 文档：a.py\n"
                         "2. [ ] 单元B：乙（预计 40min）\n"
                         "   - 文档：b/c.py\n"
                         "**编码目标**：x 完成 y")

    def test_windows_backslash_normalized(self):
        text = "   - 文档：temp_tinyrag\\pom.xml"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"),
                         "   - 文档：pom.xml")

    def test_separator_normalization_locked(self):
        # 分隔符归一行为锁定：中文逗号/顿号/分号统一重写为 ", "
        text = "   - 文档：a.py、b.py；c.py"
        self.assertEqual(strip_project_doc_prefix(text, "temp_tinyrag"),
                         "   - 文档：a.py, b.py, c.py")

    def test_exists_predicate_protects_same_name_package(self):
        # 同名包布局（仓库 foo/ 内含顶层包 foo/）：foo/core.py 是合法内部路径，
        # exists 谓词下不得误剥（🔴 回归锁：无条件剥会把它剥坏成 core.py）
        tmp = Path(tempfile.mkdtemp(prefix="samepkg_"))
        try:
            (tmp / "foo").mkdir()
            (tmp / "foo" / "core.py").write_text("x=1", encoding="utf-8")
            exists = lambda tok: (tmp / tok).exists()
            text = "   - 文档：foo/core.py"
            self.assertEqual(strip_project_doc_prefix(text, "foo", exists=exists),
                             "   - 文档：foo/core.py")
            # 原 token 不存在（真误带前缀）仍剥
            text2 = "   - 文档：foo/other.py"
            self.assertEqual(strip_project_doc_prefix(text2, "foo", exists=exists),
                             "   - 文档：other.py")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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


def _study_md(doc_line: str) -> str:
    return ("\n".join([
        "当前天数：Day 1", "", "整体完成度：0%", "",
        "## Day 1 | 第1天主题",
        "**目标**：当日目标",
        "1. [ ] 单元A：概念学习（预计 40min）",
        f"   - 文档：{doc_line}",
        "**编码目标**：test-replica 完成 当日模块",
        "**推荐论文**：《Test Paper》 — 重点读 Section 1",
        '**面试话术目标**：产出"当日话题"的 30 秒/2 分钟版回答', ""]))


class TestInitPrefixIntegration(unittest.TestCase):
    """初始化链路：带前缀的 LLM 输出 → 规范化后校验通过 + 落盘无前缀。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="docprefix_"))
        (self.tmp / "pom.xml").write_text("<project/>", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ws(self) -> Workspace:
        return Workspace.from_dict({
            "slug": "test", "title": "Test", "goal": "测试",
            "docx_dir": str(self.tmp / "docx"),
            "project_dir": str(self.tmp),
            "session_path": str(self.tmp / "session.json"),
            "total_days": 1, "replica_name": "test-replica",
        }, WEB_ROOT)

    def test_initialize_strips_prefix(self):
        ws = self._ws()
        prefixed = _study_md(f"{self.tmp.name}/pom.xml")
        llm = MockLLM(script=[PROJECT_MD, prefixed])
        DocInitializer(llm).initialize(ws, "扫描画像")
        text = (ws.docx_dir / "Study.md").read_text(encoding="utf-8")
        self.assertIn("- 文档：pom.xml", text)
        self.assertNotIn(f"{self.tmp.name}/pom.xml", text)

    def test_llm_failure_wrapped_as_init_error(self):
        # LLM 调用异常（402 余额/401 风控/网络）包装为 InitError → 路由 ok=False
        # 友好错误而非裸 500（G1 验收 1.4 重扫真实命中：DeepSeek 402 → HTTP 500）
        from backend.services.doc_initializer import InitError

        class _BoomLLM:
            def chat(self, messages, max_tokens=None):
                raise RuntimeError("Error code: 402 - Insufficient Balance")

            def chat_stream(self, messages, max_tokens=None):
                raise RuntimeError("Error code: 402")

        ws = self._ws()
        with self.assertRaises(InitError) as cm:
            DocInitializer(_BoomLLM()).initialize(ws, "扫描画像")
        self.assertIn("LLM 调用失败", str(cm.exception))
        self.assertIn("402", str(cm.exception))
        self.assertFalse((ws.docx_dir / "Study.md").exists())  # 零文件落盘

    def test_initialize_without_norm_would_fail(self):
        # 反向锁定：若规范化被移除，带前缀输出必撞校验（InitError）
        from backend.services.doc_initializer import InitError
        ws = self._ws()
        prefixed = _study_md(f"{self.tmp.name}/pom.xml")
        llm = MockLLM(script=[PROJECT_MD, prefixed, prefixed])
        init = DocInitializer(llm)
        with self.assertRaises(InitError):
            init._generate("init_study_md.md", ws, "扫描画像",
                           init._make_study_md_validator(ws, init._detail_days),
                           "Study.md", normalize=None)


class TestEndDayPrefixIntegration(unittest.TestCase):
    """滚动细化链路：end_day._detail_next_day 同样规范化（接线存在性）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="endday_prefix_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir(parents=True)
        (self.docx / "Project.md").write_text(PROJECT_MD, encoding="utf-8")
        self.study_md = "\n".join([
            "当前天数：Day 1", "", "整体完成度：0%", "",
            "## Day 1 | 第1天主题",
            "**目标**：当日目标",
            "1. [ ] 单元A：概念学习（预计 40min）",
            "   - 文档：无",
            "**编码目标**：ragent-replica 完成 当日模块",
            "**推荐论文**：无",
            '**面试话术目标**：产出"话题"的 30 秒/2 分钟版回答', "",
            "## Day 2 | 第2天粗纲主题",
            "**目标**：粗纲目标", ""])
        (self.docx / "Study.md").write_text(self.study_md, encoding="utf-8")
        settings_src = (WEB_ROOT / "config" / "settings.toml").read_text(encoding="utf-8")
        settings = settings_src.replace(
            'docx_dir = "../docx"',
            f'docx_dir = "{self.docx.as_posix()}"')
        settings = re.sub(r'active_workspace = ".*?"',
                          'active_workspace = "ragent"', settings)
        self.settings_path = self.tmp / "settings.toml"
        self.settings_path.write_text(settings, encoding="utf-8")
        self.config = ConfigService(self.settings_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deps(self, llm) -> Deps:
        config = self.config
        return Deps(
            config=config, state_store=StateStore(config),
            memory=MemoryStore(config), study_plan=StudyPlanStore(config),
            templates=TemplateService(config), backup=BackupService(config),
            stages=StageMachine(config), llm=llm, llm_cheap=llm,
            quiz=QuizEngine(config, llm),
            prompts=PromptBuilder(config, StateStore(config),
                                  MemoryStore(config), StageMachine(config)),
            hooks=HookPipeline(),
            session_store=SessionStore(self.tmp / "session.json"))

    def test_detail_next_day_strips_prefix(self):
        ws = self.config.workspace  # ragent，project_dir.name = ragent原项目
        real_inner = "frontend/index.html"  # ragent原项目 内真实存在的文件
        self.assertTrue((ws.project_dir / real_inner).exists(),
                        "前置：ragent原项目/frontend/index.html 应存在")
        llm = MockLLM(script=["\n".join([
            "## Day 2 | Mock 细化主题",
            "**目标**：Mock 目标",
            "1. [ ] 单元A：Mock 细化单元（预计 40min）",
            f"   - 文档：{ws.project_dir.name}/{real_inner}",
            "**编码目标**：ragent-replica 完成 Mock 编码",
            "**推荐论文**：无",
            '**面试话术目标**：产出"Mock 话题"的 30 秒/2 分钟版回答', ""])])
        deps = self._deps(llm)
        new_text, warn = EndDayHandler()._detail_next_day(
            deps, 1, self.study_md, "")
        self.assertIsNone(warn, f"细化应成功：{warn}")
        self.assertIn(f"- 文档：{real_inner}", new_text)
        self.assertNotIn(f"{ws.project_dir.name}/{real_inner}", new_text)


if __name__ == "__main__":
    unittest.main()
