"""课程图谱（M7 §4）测试：域纯函数闭包/拓扑序 + LearnerService 图查询。

关键断言：上游先补的拓扑序（根基在前）、环守卫不死循环、零证据节点
计入 unmastered_upstream（先修诊断核心）但不计入 remediation_order。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.learner import topo_order, upstream_closure
from backend.services.config_service import ConfigService
from backend.services.learner_service import LearnerService

# Day1-A ← Day1-B ← Day1-C ← Day2-A（跨天链，与 ensure_concepts 生成同构）
PMAP = {
    "Day1-A": [],
    "Day1-B": ["Day1-A"],
    "Day1-C": ["Day1-B"],
    "Day2-A": ["Day1-C"],
    "Day2-B": ["Day2-A"],
}


class TestDomainGraph(unittest.TestCase):
    def test_closure_root_first(self):
        self.assertEqual(upstream_closure("Day2-A", PMAP),
                         ["Day1-A", "Day1-B", "Day1-C"])
        self.assertEqual(upstream_closure("Day1-C", PMAP),
                         ["Day1-A", "Day1-B"])
        self.assertEqual(upstream_closure("Day1-A", PMAP), [])

    def test_closure_cycle_guard(self):
        cyclic = {"A": ["B"], "B": ["C"], "C": ["A"]}
        out = upstream_closure("A", cyclic)  # 不死循环即胜利
        self.assertEqual(set(out), {"B", "C"})

    def test_closure_missing_nodes_tolerated(self):
        out = upstream_closure("Day2-A", {"Day2-A": ["Ghost-X"]})
        self.assertEqual(out, ["Ghost-X"])  # 未知上游按叶子处理

    def test_topo_order_upstream_first(self):
        out = topo_order(["Day2-A", "Day1-C", "Day1-A", "Day1-B"], PMAP)
        self.assertEqual(out, ["Day1-A", "Day1-B", "Day1-C", "Day2-A"])
        # 子集也保序
        out = topo_order(["Day1-C", "Day1-A"], PMAP)
        self.assertEqual(out, ["Day1-A", "Day1-C"])


class TestServiceGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lgraph_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            '[evidence_delta]\nquiz_right = 0.10\nquiz_wrong = -0.15\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        concepts = {"schema_version": 1, "concepts": {
            cid: {"id": cid, "title": f"标题{cid}", "prerequisites": pre,
                  "materials": [], "code_refs": []}
            for cid, pre in PMAP.items()}}
        (self.docx / "concepts.json").write_text(
            json.dumps(concepts, ensure_ascii=False), encoding="utf-8")
        today = "2026-07-23"
        model = {"schema_version": 1, "concepts": {
            "Day1-A": {"title": "标题Day1-A", "mastery": 0.1,
                       "evidence": [{"type": "quiz_wrong", "delta": -0.15,
                                     "ts": today, "source_ref": "t:1"}],
                       "last_review_day": 1, "review_due": []},
            "Day1-B": {"title": "标题Day1-B", "mastery": 0.9,
                       "evidence": [{"type": "quiz_right", "delta": 0.10,
                                     "ts": today, "source_ref": f"t:b{i}"}
                                    for i in range(6)] +
                                   [{"type": "code_verify_pass", "delta": 0.20,
                                     "ts": today, "source_ref": "t:bv"}],
                       "last_review_day": 1, "review_due": []},
            # Day1-C 无证据（未学）；Day2-A/B 无证据
        }}
        (self.docx / "learner_model.json").write_text(
            json.dumps(model, ensure_ascii=False), encoding="utf-8")
        self.svc = LearnerService(self.config)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upstream_chain(self):
        self.assertEqual(self.svc.upstream_chain("Day2-B"),
                         ["Day1-A", "Day1-B", "Day1-C", "Day2-A"])

    def test_unmastered_upstream(self):
        out = self.svc.unmastered_upstream(["Day2-A"], current_day=2)
        cids = [x["cid"] for x in out]
        # 拓扑序（根基在前）：Day1-A(弱,有证据) → Day1-C(零证据)
        # Day1-B mastery 0.9 达标剔除
        self.assertEqual(cids, ["Day1-A", "Day1-C"])
        self.assertEqual(out[0]["prereq_of"], "Day2-A")
        self.assertTrue(out[0]["has_evidence"])
        self.assertFalse(out[1]["has_evidence"])  # 零证据计入（诊断场景）
        # 多个目标节点合并去重
        out = self.svc.unmastered_upstream(["Day2-A", "Day2-B"], current_day=2)
        self.assertEqual([x["cid"] for x in out],
                         ["Day1-A", "Day1-C", "Day2-A"])

    def test_remediation_order(self):
        # 仅有证据且未达标：Day1-A 唯一入选（Day1-C 零证据不计入）
        self.assertEqual(self.svc.remediation_order(current_day=2), ["Day1-A"])
        # 加一条 Day1-C 弱证据 → 拓扑序 Day1-A 前 Day1-C 后
        self.svc.add_evidence("Day1-C", "quiz_wrong", "t:9", 1)
        self.assertEqual(self.svc.remediation_order(current_day=2),
                         ["Day1-A", "Day1-C"])


if __name__ == "__main__":
    unittest.main()
