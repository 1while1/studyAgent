"""间隔复习调度（services/review_scheduler.collect_due）测试。"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import ConfigService
from backend.services.memory_store import MemoryStore
from backend.services.review_scheduler import collect_due
from backend.services.state_store import StateStore


def _memory(units=(), stuck="", question="", rating_lines=()):
    lines = ["## 2026-07-20", "", "### 今日导学单元"]
    lines += [f"- [x] 单元{u}" for u in units]
    lines += ["", "### [同步] 记录",
              "- 已掌握：无",
              f"- 卡壳：{stuck}",
              f"- 疑问：{question}",
              "- 代码完成：无",
              "", "### 掌握度评分（1-5分）"]
    lines += list(rating_lines)
    lines += ["", "### 明日优先项", "- 待生成", ""]
    return "\n".join(lines)


class TestReviewScheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="review_"))
        docx = self.tmp / "docx"
        (docx / "StudyMemory").mkdir(parents=True)
        settings = self.tmp / "settings.toml"
        settings.write_text(
            f'docx_dir = "{docx.as_posix()}"\n'
            'active_workspace = "t"\n'
            '[[workspaces]]\nslug = "t"\ntitle = "t"\n'
            f'docx_dir = "{docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.memory = MemoryStore(self.config)
        self.state_store = StateStore(self.config)
        self.docx = docx

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_memory(self, day, **kw):
        (self.docx / "StudyMemory" / f"Day_{day:02d}.md").write_text(
            _memory(**kw), encoding="utf-8")

    def _write_state(self, days: dict, current_day=9):
        state = {"current_day": current_day,
                 "overall_completion_percentage": 0, "days": days}
        (self.docx / "StudyState.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def test_interval_hit_and_miss(self):
        # Day 2 卡壳：距 Day 3 为 1（命中），距 Day 4 为 2（不命中），距 Day 5 为 3（命中）
        self._write_memory(2, stuck="SSE 背压机制")
        self._write_state({}, current_day=3)
        hit = collect_due(self.config, self.state_store, self.memory, 3)
        self.assertEqual([i["text"] for i in hit], ["SSE 背压机制"])
        miss = collect_due(self.config, self.state_store, self.memory, 4)
        self.assertEqual(miss, [])
        hit7 = collect_due(self.config, self.state_store, self.memory, 5)
        self.assertEqual(len(hit7), 1)

    def test_question_only_pending(self):
        self._write_memory(1, question="什么是背压（待解答）、RAG 流程")
        self._write_state({}, current_day=2)
        due = collect_due(self.config, self.state_store, self.memory, 2)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["type"], "疑问")
        self.assertEqual(due[0]["text"], "什么是背压")

    def test_low_rating_unit(self):
        self._write_state({"1": {"units": [
            {"id": "A", "title": "低分单元", "status": "completed", "rating": 2.5},
            {"id": "B", "title": "高分单元", "status": "completed", "rating": 4.5},
            {"id": "C", "title": "未完成", "status": "postponed", "rating": 0},
        ]}}, current_day=2)
        due = collect_due(self.config, self.state_store, self.memory, 2)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["type"], "回滚")
        self.assertIn("低分单元", due[0]["text"])

    def test_priority_and_cap(self):
        # 多条复习项：回滚排最前；总量封顶 review_max_items
        for d in (1, 2, 3, 4):
            self._write_memory(d, stuck=f"卡壳{d}", question=f"疑问{d}（待解答）")
        self._write_state({"1": {"units": [
            {"id": "A", "title": "低分", "status": "completed", "rating": 2.0},
        ]}}, current_day=8)
        due = collect_due(self.config, self.state_store, self.memory, 8)
        # 距 8 天：Day1=7、Day4=4(不中)、Day2=6(不中)、Day3=5(不中) → 只有 Day1 命中
        self.assertEqual(due[0]["type"], "回滚")
        self.assertTrue(len(due) <= 6)

    def test_no_memory_returns_empty(self):
        self._write_state({}, current_day=5)
        self.assertEqual(
            collect_due(self.config, self.state_store, self.memory, 5), [])


if __name__ == "__main__":
    unittest.main()
