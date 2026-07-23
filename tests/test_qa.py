"""面试话术层（services/qa_service）测试。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import ConfigService
from backend.services.qa_service import (QaService, parse, render,
                                         render_entry, validate_capture)

PREAMBLE_MD = """# 面试话术库

## 问题模板

**标签**：#标签
**关联代码**：`文件路径:行号`

**精简版（30秒）**：
...

**展开版（2分钟）**：
...

**追问预案**：
- Q: ...
  A: ...

**产出来源**：YYYY-MM-DD 场景

---

## 已累积话术

（学习开始后自动累积）"""

ENTRY1 = """## 什么是 RAG

**标签**：#RAG #检索增强
**关联代码**：`framework/rag/pipeline.py:L10-L20`

**精简版（30秒）**：
检索+生成两段式，先查资料再让模型作答。

**展开版（2分钟）**：
RAG 解决幻觉与知识截止两大痛点：
- 检索层：向量库召回
- 生成层：注入上下文约束输出

**追问预案**：
- Q: 为什么不用微调？
  A: 知识更新成本高。
- Q: 检索不准怎么办？
  A: 重排序+混合检索。
- Q: 如何评估？
  A: 命中率与忠实度。

**产出来源**：Day 2 [同步] 面试话术"""

ENTRY2 = """## 背压机制是什么

**标签**：#SSE #流式
**关联代码**：`infra-ai/sse.py:L33`

**精简版（30秒）**：
下游来不及消费时向上游施加的流控信号。

**展开版（2分钟）**：
**重点**：背压不是丢弃，是减速。

**追问预案**：
- Q: 与缓冲区关系？
  A: 缓冲是吸收，背压是抑制。
- Q: 项目里在哪实现？
  A: sse.py 的队列水位。
- Q: 溢出怎么办？
  A: 降级为轮询。

**产出来源**：Day 2 复盘拷打"""


class QaTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qa_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started"]\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.svc = QaService(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, md: str):
        self.svc.path.write_text(md, encoding="utf-8")


class TestParse(QaTestBase):
    def test_skeleton_has_no_entries(self):
        doc = parse(PREAMBLE_MD)
        self.assertEqual(doc["entries"], [])
        self.assertIn("问题模板", doc["preamble"])  # 固定小节不进条目

    def test_parse_two_entries(self):
        doc = parse(PREAMBLE_MD + "\n\n" + ENTRY1 + "\n\n" + ENTRY2 + "\n")
        self.assertEqual(len(doc["entries"]), 2)
        e1, e2 = doc["entries"]
        self.assertEqual(e1["title"], "什么是 RAG")
        self.assertEqual(e1["tags"], ["RAG", "检索增强"])
        self.assertEqual(e1["code_ref"], "framework/rag/pipeline.py:L10-L20")
        self.assertIn("两段式", e1["brief"])
        self.assertEqual(len(e1["followups"]), 3)
        self.assertEqual(e1["followups"][0], ("为什么不用微调？", "知识更新成本高。"))
        self.assertEqual(e1["source"], "Day 2 [同步] 面试话术")
        # 内容里的加粗行不被误切为字段（在展开版字段内）
        self.assertIn("**重点**", e2["detail"])
        self.assertEqual(e2["source"], "Day 2 复盘拷打")
        # id 稳定
        self.assertEqual(e1["id"], parse(ENTRY1)["entries"][0]["id"])

    def test_round_trip(self):
        full = PREAMBLE_MD + "\n\n" + ENTRY1 + "\n\n" + ENTRY2 + "\n"
        doc = parse(full)
        again = parse(render(doc["preamble"], doc["entries"], doc["tail"]))
        self.assertEqual([e["id"] for e in doc["entries"]],
                         [e["id"] for e in again["entries"]])
        self.assertEqual(doc["entries"][0]["followups"],
                         again["entries"][0]["followups"])
        self.assertIn("问题模板", again["preamble"])


class TestWrite(QaTestBase):
    def test_add_entry_strips_placeholder(self):
        self._write(PREAMBLE_MD)
        self.svc.add_entry(ENTRY1)
        md = self.svc.path.read_text(encoding="utf-8")
        self.assertNotIn("（学习开始后自动累积）", md)
        entries = self.svc.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "什么是 RAG")

    def test_add_entry_to_missing_file(self):
        self.svc.add_entry(ENTRY1)
        self.assertEqual(len(self.svc.entries()), 1)

    def test_update_entry(self):
        self._write(PREAMBLE_MD + "\n\n" + ENTRY1 + "\n")
        eid = self.svc.entries()[0]["id"]
        e = self.svc.update_entry(eid, brief="新的 30 秒版", code_ref="a.py:L1")
        self.assertEqual(e["brief"], "新的 30 秒版")
        entries = self.svc.entries()
        self.assertEqual(entries[0]["code_ref"], "a.py:L1")
        self.assertEqual(entries[0]["source"], "Day 2 [同步] 面试话术")  # 未动
        self.assertIsNone(self.svc.update_entry("ffffffff", brief="x"))

    def test_delete_entry(self):
        self._write(PREAMBLE_MD + "\n\n" + ENTRY1 + "\n\n" + ENTRY2 + "\n")
        eid = self.svc.entries()[0]["id"]
        self.assertTrue(self.svc.delete_entry(eid))
        self.assertEqual(len(self.svc.entries()), 1)
        self.assertEqual(self.svc.entries()[0]["title"], "背压机制是什么")
        self.assertFalse(self.svc.delete_entry(eid))
        # preamble 保留
        self.assertIn("问题模板", self.svc.path.read_text(encoding="utf-8"))


class TestValidateCapture(QaTestBase):
    def test_valid_passes(self):
        out = validate_capture("以下是提炼：\n\n" + ENTRY1 + "\n\n" + ENTRY2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["title"], "什么是 RAG")

    def test_missing_followups_rejected(self):
        bad = ENTRY1.replace("- Q: 如何评估？\n  A: 命中率与忠实度。\n", "")
        bad = bad.replace("- Q: 检索不准怎么办？\n  A: 重排序+混合检索。\n", "")
        self.assertIsNone(validate_capture(bad))  # 只剩 1 组追问

    def test_missing_fields_rejected(self):
        bad = ENTRY1.replace("**精简版（30秒）**：\n检索+生成两段式，先查资料再让模型作答。\n", "")
        self.assertIsNone(validate_capture(bad))

    def test_garbage_returns_none(self):
        self.assertIsNone(validate_capture("模型随意输出的一段废话"))
        self.assertIsNone(validate_capture(""))


if __name__ == "__main__":
    unittest.main()
