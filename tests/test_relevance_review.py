"""感召式复习（M7 §4/§13，start_day 集成）测试。

真数据副本驱动（TestFlows 同款）：ragent docx 临时副本上跑 start_day.run，
断言 ①上游感召标签/排序/review_prefix 分组 ②无感召时与旧形态一致
③感召服务异常静默降级 ④合并封顶 review_max_items。
"""

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import ConfigService, WEB_ROOT
from backend.engine.commands.start_day import StartDayHandler
from tests.test_flows import make_deps


def _make_tmp_docx(prefix: str):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    shutil.copytree(WEB_ROOT.parent / "docx", tmp / "docx")
    settings_src = (WEB_ROOT / "config" / "settings.toml") \
        .read_text(encoding="utf-8")
    settings = settings_src.replace(
        'docx_dir = "../docx"', f'docx_dir = "{(tmp / "docx").as_posix()}"')
    settings = re.sub(r'active_workspace = ".*?"',
                      'active_workspace = "ragent"', settings)
    sp = tmp / "settings.toml"
    sp.write_text(settings, encoding="utf-8")
    # 🟡-1 钉住真实数据漂移（三处假红路径免疫）：
    # a) 用户推进学习 → 强制 current_day=2、Day2 单元未开始、无跨日完成标记
    import json as _json
    state_p = tmp / "docx" / "StudyState.json"
    state = _json.loads(state_p.read_text(encoding="utf-8"))
    state["current_day"] = 2
    state["days"] = {k: v for k, v in state["days"].items() if k in ("1", "2")}
    state["days"]["1"].pop("active_day_completed", None)
    state["days"]["2"].pop("active_day_completed", None)
    state["days"]["2"]["units"] = [
        {"id": u["id"], "title": u["title"], "status": "not_started",
         "rating": 0} for u in state["days"]["2"].get("units", [])]
    for u in state["days"]["1"].get("units", []):
        u["rating"] = 4.0  # 消除日历回滚项（pin 无日历通道）
    state_p.write_text(_json.dumps(state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    # b) mastery 演进 → 删模型（零证据上游仍感召达标线以下）
    (tmp / "docx" / "learner_model.json").unlink(missing_ok=True)
    # c) 日历通道 → 删 Day_01（memory 无来源）；Day_02 也清（走全新开始分支）
    (tmp / "docx" / "StudyMemory" / "Day_01.md").unlink(missing_ok=True)
    (tmp / "docx" / "StudyMemory" / "Day_02.md").unlink(missing_ok=True)
    return tmp, ConfigService(sp)


class TestRelevanceReview(unittest.TestCase):
    def setUp(self):
        self.tmp, self.config = _make_tmp_docx("relrev_")
        self.deps = make_deps(self.config, self.tmp / "session.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_start(self):
        session = self.deps.session_store.load()
        return StartDayHandler().run(self.deps, session, "重新开始今日学习")

    def test_relevance_tagged_and_grouped(self):
        """ragent Day2 → 上游 Day1 三概念（迁移证据 mastery≈0.04）全部感召。"""
        result = self._run_start()
        step1 = result.messages[0]
        self.assertIn("上游感召·Day 1：Day1-A", step1)
        self.assertIn("上游感召·Day 1：Day1-B", step1)
        self.assertIn("上游感召·Day 1：Day1-C", step1)
        # 拓扑序：A 在 B 前、B 在 C 前
        ia, ib, ic = (step1.index("Day1-A"), step1.index("Day1-B"),
                      step1.index("Day1-C"))
        self.assertLess(ia, ib)
        self.assertLess(ib, ic)
        # review_prefix：有【上游感召】组，无日历项则无【间隔复习】组
        self.assertIn("【上游感召】", result.llm_instruction)
        self.assertNotIn("【间隔复习】", result.llm_instruction)
        self.assertIn("先修链未达标", result.llm_instruction)

    def test_no_relevance_keeps_old_shape(self):
        """上游全达标（mastery≥0.7）→ 感召为空 → 输出无感召字样（旧形态）。"""
        import json as _json

        def evs(cid):
            out = [{"type": "quiz_right", "delta": 0.10, "ts": "2026-07-23",
                    "source_ref": f"t:{cid}:{i}"} for i in range(6)]
            out.append({"type": "code_verify_pass", "delta": 0.20,
                        "ts": "2026-07-23", "source_ref": f"t:{cid}:v"})
            return out  # 0.6 + 0.2 = 0.8 ≥ 0.7 达标

        concepts = _json.loads(
            (self.tmp / "docx" / "concepts.json").read_text(encoding="utf-8"))
        day1 = [c for c in concepts["concepts"] if c.startswith("Day1-")]
        model = {"schema_version": 1, "concepts": {
            cid: {"title": cid, "mastery": 0.8, "evidence": evs(cid),
                  "last_review_day": 1, "review_due": []} for cid in day1}}
        (self.tmp / "docx" / "learner_model.json").write_text(
            _json.dumps(model, ensure_ascii=False), encoding="utf-8")
        result = self._run_start()
        joined = "\n".join(result.messages)
        self.assertNotIn("上游感召", joined)
        self.assertNotIn("【上游感召】", result.llm_instruction)

    def test_relevance_service_error_degrades_silently(self):
        with mock.patch(
                "backend.services.learner_service.LearnerService"
                ".unmastered_upstream", side_effect=RuntimeError("boom")):
            result = self._run_start()
        self.assertIn("---【Step 3：今日计划】---", "\n".join(result.messages))
        self.assertNotIn("上游感召", "\n".join(result.messages))

    def test_merge_capped_at_max_items(self):
        """合并总量封顶 review_max_items（默认 6），感召优先占位。"""
        fake = [{"cid": f"Day1-{chr(65 + i)}", "title": f"弱项{i}",
                 "mastery": 0.1, "has_evidence": True, "prereq_of": "Day2-A"}
                for i in range(9)]
        with mock.patch(
                "backend.services.learner_service.LearnerService"
                ".unmastered_upstream", return_value=fake):
            result = self._run_start()
        step1 = result.messages[0]
        self.assertEqual(step1.count("上游感召·"), 6)  # 9 个候选被截到 6
        self.assertNotIn("弱项8", step1)
        self.assertNotIn("弱项7", step1)
        self.assertNotIn("弱项6", step1)

    def test_start_day_clears_prereq_fields(self):
        """矩阵：start_day 新开始清诊断残留字段（与清面试字段对称）。"""
        session = self.deps.session_store.load()
        session.prereq_targets = [{"cid": "Day1-A", "title": "x",
                                   "question": "y"}]
        session.prereq_retry = 1
        self.deps.session_store.save(session)
        StartDayHandler().run(self.deps, session, "重新开始今日学习")
        self.assertEqual(session.prereq_targets, [])
        self.assertEqual(session.prereq_retry, 0)

    def test_f1_ensure_before_graph_read(self):
        """F1 回归：新日窗口（当日单元未注册 concepts）感召经 ensure 仍出现。"""
        import json as _json
        cp = self.tmp / "docx" / "concepts.json"
        data = _json.loads(cp.read_text(encoding="utf-8"))
        data["concepts"] = {k: v for k, v in data["concepts"].items()
                            if k.startswith("Day1-")}  # Day2 条目尚未注册
        cp.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = self._run_start()
        self.assertIn("上游感召·Day 1：Day1-A", result.messages[0])


if __name__ == "__main__":
    unittest.main()
