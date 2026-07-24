"""架构审计修复批回归测试（B 包：backend/services + frontend 族）。

- Y4 run_build 超时只杀直接子进程 → Popen + psutil 杀整棵树（孙进程不留活口）
- Y5 md/txt 解码：utf-8 严格失败即全文 GBK → 仅 GBK 严格成功才用 GBK，否则 utf-8 替换符
- Y6 Study.md 单元「文档」300 字符盲窗错挂下一单元 → 窗口限定到下一单元/标题
- Y7 InterviewQA 一个坏块使其后全部条目进 tail → 坏块仅自身进 tail
- Y9 resolve_doc `t.endswith(il)` 无分隔符边界 → 边界化（token 尾部重叠不错配短 id）

前端项（Y8 序号防护 / Y10 model 泄漏 / Y11 mtime 冲突 / Y12 合并点击序 / B10 乱码注释）
的验证为 `node --check frontend/app.js`（JS 逻辑无后端单测载体），走查另由主流程覆盖。
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil

from backend.services import code_runner
from backend.services.config_service import ConfigService
from backend.services.materials_service import MaterialsService
from backend.services.qa_service import parse as qa_parse, render as qa_render
from backend.services.study_plan import parse_day_text

PY = sys.executable


class TestRunBuildKillTree(unittest.TestCase):
    """Y4：超时强杀整棵进程树——spawn 孙进程的命令超时后孙进程也必须死。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="runbuild_"))
        self._orig_build_command = code_runner.build_command
        self._gpid = None

    def tearDown(self):
        code_runner.build_command = self._orig_build_command
        if self._gpid and psutil.pid_exists(self._gpid):  # 失败残留兜底
            try:
                psutil.Process(self._gpid).kill()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch_cmd(self, cmd):
        code_runner.build_command = lambda tool, kind, offline=False: cmd

    def test_timeout_kills_whole_tree(self):
        pid_file = self.tmp / "grandchild.pid"
        # 直接子进程：spawn 孙进程（沉睡 120s）后自己也沉睡——模拟 maven 派生 java
        parent_src = (
            "import subprocess,sys,time,pathlib\n"
            f"g = subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])\n"
            f"pathlib.Path(r'{pid_file.as_posix()}').write_text(str(g.pid))\n"
            "time.sleep(120)\n")
        self._patch_cmd([PY, "-c", parent_src])
        r = code_runner.run_build(self.tmp, "npm", timeout=1)
        # 返回契约不变
        self.assertEqual(set(r), {"cmd", "code", "tail", "seconds", "timed_out"})
        self.assertTrue(r["timed_out"])
        self.assertEqual(r["code"], -1)
        self.assertIn("强杀", r["tail"])
        # 孙进程 pid 已在被杀前写入文件
        deadline = time.time() + 3
        while time.time() < deadline and not pid_file.exists():
            time.sleep(0.1)
        self.assertTrue(pid_file.exists(), "孙进程 pid 文件未出现（测试前提失败）")
        self._gpid = int(pid_file.read_text().strip())
        # 关键断言：孙进程也死（修复前 subprocess.run 只杀直接子进程，孙进程存活）
        deadline = time.time() + 5
        while time.time() < deadline and psutil.pid_exists(self._gpid):
            time.sleep(0.2)
        self.assertFalse(psutil.pid_exists(self._gpid), "孙进程未被杀树")

    def test_normal_exit_contract(self):
        self._patch_cmd([PY, "-c", "print('build-ok')"])
        r = code_runner.run_build(self.tmp, "npm", timeout=30)
        self.assertFalse(r["timed_out"])
        self.assertEqual(r["code"], 0)
        self.assertIn("build-ok", r["tail"])


class _MaterialsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="matfix_"))
        self.docs = self.tmp / "docs"
        self.docs.mkdir()
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n'
            f'materials_dir = "{self.docs.as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.ms = MaterialsService(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestGbkFallback(_MaterialsBase):
    """Y5：含坏字节的 UTF-8 不再整体转 GBK 乱码；真 GBK 文件仍可解析。"""

    def test_bad_byte_utf8_keeps_chinese(self):
        p = self.docs / "bad.md"
        p.write_bytes(
            "第一章 概述\n".encode("utf-8") + b"\xff"
            + "第二章 深入\n结束".encode("utf-8"))
        text = self.ms._extract_text(p, "md")
        self.assertIn("�", text)          # 坏字节 → 替换符
        self.assertIn("第一章 概述", text)  # 其余中文保留（修复前整体 GBK 乱码）
        self.assertIn("第二章 深入", text)

    def test_real_gbk_file_parses(self):
        p = self.docs / "gbk.txt"
        raw = "第一章 概述\nGBK 正文\n第二行".encode("gbk")
        p.write_bytes(raw)
        text = self.ms._extract_text(p, "txt")
        self.assertEqual(text, "第一章 概述\nGBK 正文\n第二行")

    def test_clean_utf8_unchanged(self):
        p = self.docs / "ok.md"
        raw = "# 标题\n正文内容".encode("utf-8")
        p.write_bytes(raw)
        self.assertEqual(self.ms._extract_text(p, "md"), "# 标题\n正文内容")


class TestStudyPlanDocWindow(unittest.TestCase):
    """Y6：缺「文档」行的单元不再错挂下一单元的文档路径。"""

    _TEXT = """# 学习计划

## Day 1 | 2026-07-22（星期三）
**目标**：基础
**导学单元**：
1. [ ] 单元A：基础一（预计 40min）
2. [ ] 单元B：基础二（预计 40min）
   - 文档：docs/b.md
**编码目标**：无
**推荐论文**：无
**面试话术目标**：无

## Day 2 | 2026-07-23（星期四）
**目标**：进阶
**导学单元**：
1. [ ] 单元A：进阶一（预计 40min）
   - 文档：docs/a2.md
**编码目标**：无
**推荐论文**：无
**面试话术目标**：无
"""

    def test_missing_doc_line_not_borrowed(self):
        day = parse_day_text(self._TEXT, 1)
        self.assertEqual(len(day["units"]), 2)
        self.assertEqual(day["units"][0]["doc"], "")  # 修复前错挂 docs/b.md
        self.assertEqual(day["units"][1]["doc"], "docs/b.md")

    def test_normal_doc_line_still_parsed(self):
        day = parse_day_text(self._TEXT, 2)
        self.assertEqual(day["units"][0]["doc"], "docs/a2.md")


class TestQaBadBlock(unittest.TestCase):
    """Y7：坏块仅自身进 tail，其后合法条目仍解析为条目。"""

    _ENTRY = """## {title}
**标签**：#模块
**关联代码**：`x.py:1`
**精简版（30秒）**：简短版
**展开版（2分钟）**：详细版
**追问预案**：
- Q: q1
  A: a1
- Q: q2
  A: a2
- Q: q3
  A: a3
**产出来源**：{source}"""

    def _md(self):
        return ("# 面试话术库\n\n前言说明\n\n"
                + self._ENTRY.format(title="条目一", source="Day 1 复盘拷打")
                + "\n\n## 坏块（手工笔记）\n一些没有产出来源的内容\n\n"
                + self._ENTRY.format(title="条目二", source="Day 2 复盘拷打") + "\n")

    def test_entries_survive_around_bad_block(self):
        doc = qa_parse(self._md())
        titles = [e["title"] for e in doc["entries"]]
        self.assertEqual(titles, ["条目一", "条目二"])  # 坏块后条目存活
        self.assertIn("坏块（手工笔记）", doc["tail"])  # 坏块自身进 tail
        self.assertIn("前言说明", doc["preamble"])

    def test_render_roundtrip_keeps_bad_block(self):
        doc = qa_parse(self._md())
        out = qa_render(doc["preamble"], doc["entries"], doc["tail"])
        doc2 = qa_parse(out)
        self.assertEqual([e["title"] for e in doc2["entries"]], ["条目一", "条目二"])
        self.assertIn("坏块（手工笔记）", doc2["tail"])


class TestResolveDocBoundary(_MaterialsBase):
    """Y9：后缀匹配带分隔符边界——token 尾部巧合重叠不错配短 id 资料。"""

    def setUp(self):
        super().setUp()
        reg = {"schema_version": 1, "materials": {
            "rag": {"id": "rag"},
            "docs/top/sub": {"id": "docs/top/sub"},
            "AI & RAG 基础扫盲/3.Prompt工程入门": {
                "id": "AI & RAG 基础扫盲/3.Prompt工程入门"},
        }}
        (self.docx / "materials.json").write_text(
            json.dumps(reg, ensure_ascii=False), encoding="utf-8")

    def test_tail_overlap_no_mismatch(self):
        # 修复前 "day01-rag".endswith("rag") 错配短 id「rag」
        self.assertIsNone(self.ms.resolve_doc("day01-rag"))

    def test_normal_hits_still_work(self):
        self.assertEqual(self.ms.resolve_doc("rag")["id"], "rag")           # 精确
        self.assertEqual(self.ms.resolve_doc("notes/rag")["id"], "rag")     # 带界后缀
        self.assertEqual(self.ms.resolve_doc("top/sub")["id"], "docs/top/sub")
        # 词干兜底（≥4 字符）不变
        self.assertEqual(self.ms.resolve_doc("Prompt工程入门")["id"],
                         "AI & RAG 基础扫盲/3.Prompt工程入门")

    def test_short_stem_still_rejected(self):
        self.assertIsNone(self.ms.resolve_doc("ai"))


if __name__ == "__main__":
    unittest.main()
