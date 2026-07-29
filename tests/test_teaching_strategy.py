"""M1.2 教学行动策略库测试。

覆盖：
- suggest_action 7 个行动的选择逻辑与优先级
- TeachingSuggestion / TeachingAction 数据结构
- extract_error_patterns 复数提取
- build_context_from_session 上下文构建
- 容错：context 缺失字段不崩溃
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 确保 backend 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.engine.teaching_strategy import (
    TeachingAction, TeachingSuggestion, suggest_action,
    build_context_from_session,
)
from backend.domain.error_pattern import (
    ErrorPatternMajor, extract_error_pattern, extract_error_patterns,
)


class TestTeachingAction(unittest.TestCase):
    """TeachingAction 枚举完整性。"""

    def test_seven_actions(self):
        self.assertEqual(len(TeachingAction), 7)

    def test_values(self):
        expected = {
            "REVIEW_PREREQ", "RETELL_CORE", "VARIANT_QUIZ",
            "ADVANCE_NEXT", "REST", "CHANGE_ANGLE", "PRACTICE_PROJECT",
        }
        self.assertEqual({a.value for a in TeachingAction}, expected)

    def test_str_enum(self):
        """TeachingAction 是 str 枚举，可直接比较。"""
        self.assertEqual(TeachingAction.REST, "REST")
        self.assertIsInstance(TeachingAction.REST, str)


class TestTeachingSuggestion(unittest.TestCase):
    """TeachingSuggestion 数据类。"""

    def test_basic(self):
        s = TeachingSuggestion(
            action=TeachingAction.REST,
            reason="测试原因",
            confidence=0.9,
        )
        self.assertEqual(s.action, TeachingAction.REST)
        self.assertEqual(s.reason, "测试原因")
        self.assertAlmostEqual(s.confidence, 0.9)
        self.assertIsNone(s.concept_id)

    def test_with_concept_id(self):
        s = TeachingSuggestion(
            action=TeachingAction.REVIEW_PREREQ,
            reason="先修缺口",
            confidence=0.85,
            concept_id="Day1-A",
        )
        self.assertEqual(s.concept_id, "Day1-A")

    def test_to_dict(self):
        s = TeachingSuggestion(
            action=TeachingAction.ADVANCE_NEXT,
            reason="掌握度高",
            confidence=0.85,
            concept_id="Day2-B",
        )
        d = s.to_dict()
        self.assertEqual(d["action"], "ADVANCE_NEXT")
        self.assertEqual(d["reason"], "掌握度高")
        self.assertAlmostEqual(d["confidence"], 0.85)
        self.assertEqual(d["concept_id"], "Day2-B")

    def test_to_dict_no_concept(self):
        s = TeachingSuggestion(
            action=TeachingAction.REST, reason="休息", confidence=0.9)
        d = s.to_dict()
        self.assertIsNone(d["concept_id"])


class TestSuggestAction(unittest.TestCase):
    """suggest_action 7 个行动的选择逻辑与优先级。"""

    # ---- 各行动独立测试 ----

    def test_rest(self):
        """session_minutes >= 45 → REST"""
        ctx = {"session_minutes": 50, "mastery": 0.8}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.REST)
        self.assertGreaterEqual(s.confidence, 0.8)

    def test_rest_boundary_45(self):
        """恰好 45 分钟也触发 REST。"""
        ctx = {"session_minutes": 45}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.REST)

    def test_rest_not_triggered_below_45(self):
        """44 分钟不触发 REST。"""
        ctx = {"session_minutes": 44, "mastery": 0.8}
        s = suggest_action(ctx)
        self.assertNotEqual(s.action, TeachingAction.REST)

    def test_review_prereq(self):
        """has_prereq_gap + mastery < 0.5 → REVIEW_PREREQ"""
        ctx = {
            "mastery": 0.3,
            "has_prereq_gap": True,
            "prereq_concept_id": "Day1-A",
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.REVIEW_PREREQ)
        self.assertEqual(s.concept_id, "Day1-A")

    def test_review_prereq_not_triggered_high_mastery(self):
        """has_prereq_gap 但 mastery >= 0.5 不触发 REVIEW_PREREQ。"""
        ctx = {"mastery": 0.6, "has_prereq_gap": True, "prereq_concept_id": "Day1-A"}
        s = suggest_action(ctx)
        self.assertNotEqual(s.action, TeachingAction.REVIEW_PREREQ)

    def test_change_angle(self):
        """2+ 种错误模式 + 连续错误 >= 2 → CHANGE_ANGLE"""
        ctx = {
            "mastery": 0.5,
            "consecutive_errors": 3,
            "error_patterns": ["CONCEPT_CONFUSION", "LOGIC_BREAK"],
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.CHANGE_ANGLE)

    def test_change_angle_three_patterns(self):
        """3 种错误模式也触发 CHANGE_ANGLE。"""
        ctx = {
            "consecutive_errors": 2,
            "error_patterns": ["CONCEPT_CONFUSION", "LOGIC_BREAK", "FORGOTTEN"],
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.CHANGE_ANGLE)
        self.assertIn("3", s.reason)

    def test_retell_core(self):
        """连续错误 >= 2（单一错误模式）→ RETELL_CORE"""
        ctx = {
            "mastery": 0.5,
            "consecutive_errors": 2,
            "error_patterns": ["CONCEPT_CONFUSION"],
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.RETELL_CORE)

    def test_retell_core_no_patterns(self):
        """连续错误 >= 2 但无错误模式记录 → RETELL_CORE"""
        ctx = {"consecutive_errors": 3, "error_patterns": []}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.RETELL_CORE)

    def test_practice_project(self):
        """mastery >= 0.6 + code_verify 未完成 → PRACTICE_PROJECT"""
        ctx = {"mastery": 0.65, "code_verify_pass": False}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.PRACTICE_PROJECT)

    def test_practice_project_not_triggered_when_verified(self):
        """code_verify 已通过不触发 PRACTICE_PROJECT。"""
        ctx = {"mastery": 0.65, "code_verify_pass": True}
        s = suggest_action(ctx)
        self.assertNotEqual(s.action, TeachingAction.PRACTICE_PROJECT)

    def test_variant_quiz(self):
        """mastery < 0.7（且无其他高优先条件）→ VARIANT_QUIZ"""
        ctx = {"mastery": 0.5}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.VARIANT_QUIZ)

    def test_variant_quiz_boundary(self):
        """mastery = 0.69 → VARIANT_QUIZ"""
        ctx = {"mastery": 0.69, "code_verify_pass": True}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.VARIANT_QUIZ)

    def test_advance_next(self):
        """mastery >= 0.7 + code_verify_pass → ADVANCE_NEXT"""
        ctx = {"mastery": 0.75, "code_verify_pass": True}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.ADVANCE_NEXT)
        self.assertGreaterEqual(s.confidence, 0.8)

    def test_advance_next_boundary(self):
        """mastery = 0.7 + code_verify_pass → ADVANCE_NEXT"""
        ctx = {"mastery": 0.7, "code_verify_pass": True}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.ADVANCE_NEXT)

    # ---- 优先级测试 ----

    def test_priority_rest_over_prereq(self):
        """REST 优先于 REVIEW_PREREQ。"""
        ctx = {
            "session_minutes": 50,
            "mastery": 0.3,
            "has_prereq_gap": True,
            "prereq_concept_id": "Day1-A",
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.REST)

    def test_priority_prereq_over_change_angle(self):
        """REVIEW_PREREQ 优先于 CHANGE_ANGLE。"""
        ctx = {
            "mastery": 0.3,
            "has_prereq_gap": True,
            "prereq_concept_id": "Day1-A",
            "consecutive_errors": 3,
            "error_patterns": ["CONCEPT_CONFUSION", "LOGIC_BREAK"],
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.REVIEW_PREREQ)

    def test_priority_change_angle_over_retell(self):
        """CHANGE_ANGLE 优先于 RETELL_CORE。"""
        ctx = {
            "consecutive_errors": 3,
            "error_patterns": ["CONCEPT_CONFUSION", "LOGIC_BREAK"],
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.CHANGE_ANGLE)

    def test_priority_retell_over_practice(self):
        """RETELL_CORE 优先于 PRACTICE_PROJECT。"""
        ctx = {
            "mastery": 0.65,
            "consecutive_errors": 2,
            "code_verify_pass": False,
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.RETELL_CORE)

    # ---- 容错测试 ----

    def test_empty_context(self):
        """空 context 返回 None（无有效掌握度信息）。"""
        s = suggest_action({})
        self.assertIsNone(s)

    def test_partial_context(self):
        """部分字段缺失不崩溃。"""
        # mastery=0.8 但 code_verify_pass 默认 False → PRACTICE_PROJECT
        s = suggest_action({"mastery": 0.8})
        self.assertEqual(s.action, TeachingAction.PRACTICE_PROJECT)
        # mastery=0.8 且 code_verify_pass=True → ADVANCE_NEXT
        s = suggest_action({"mastery": 0.8, "code_verify_pass": True})
        self.assertEqual(s.action, TeachingAction.ADVANCE_NEXT)

    def test_none_values(self):
        """None 值字段返回 None（mastery=None 时信息不足）。"""
        ctx = {
            "mastery": None,
            "consecutive_errors": None,
            "error_patterns": None,
            "session_minutes": None,
        }
        s = suggest_action(ctx)
        self.assertIsNone(s)


class TestExtractErrorPatterns(unittest.TestCase):
    """extract_error_patterns 复数形式测试。"""

    def test_single_object(self):
        output = '评分结果：{"error_major": "CONCEPT_CONFUSION", "error_minor": "混淆了BFS和DFS"}'
        patterns = extract_error_patterns(output)
        self.assertEqual(patterns, ["CONCEPT_CONFUSION"])

    def test_json_array(self):
        arr = [
            {"error_major": "CONCEPT_CONFUSION", "error_minor": "混淆概念"},
            {"error_major": "LOGIC_BREAK", "error_minor": "推理断裂"},
        ]
        output = f'结果：{json.dumps(arr)}'
        patterns = extract_error_patterns(output)
        self.assertEqual(len(patterns), 2)
        self.assertIn("CONCEPT_CONFUSION", patterns)
        self.assertIn("LOGIC_BREAK", patterns)

    def test_dedup(self):
        """重复的 major 去重。"""
        arr = [
            {"error_major": "CONCEPT_CONFUSION"},
            {"error_major": "CONCEPT_CONFUSION"},
        ]
        output = json.dumps(arr)
        patterns = extract_error_patterns(output)
        self.assertEqual(patterns, ["CONCEPT_CONFUSION"])

    def test_no_match(self):
        patterns = extract_error_patterns("没有 JSON 的普通文本")
        self.assertEqual(patterns, [])

    def test_null_major(self):
        """error_major: null → 无错误。"""
        output = '{"error_major": null}'
        patterns = extract_error_patterns(output)
        self.assertEqual(patterns, [])

    def test_invalid_major(self):
        """非法 major 值被过滤。"""
        output = '{"error_major": "INVALID_TYPE"}'
        patterns = extract_error_patterns(output)
        self.assertEqual(patterns, [])

    def test_backward_compatible(self):
        """extract_error_pattern（单数）仍然正常工作。"""
        output = '{"error_major": "FORGOTTEN", "error_minor": "忘了公式"}'
        major, minor = extract_error_pattern(output)
        self.assertEqual(major, "FORGOTTEN")
        self.assertEqual(minor, "忘了公式")


class TestGetConsecutiveErrors(unittest.TestCase):
    """learner_service.get_consecutive_errors 测试。"""

    def _make_service(self, evidence: list[dict]):
        """创建带有预设 evidence 的 LearnerService mock。"""
        from backend.services.learner_service import LearnerService
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MagicMock()
            config.docx_dir = Path(tmpdir)
            config.get = MagicMock(return_value={})
            svc = LearnerService(config)
            # 直接 mock _load_json 返回预设数据
            model = {"schema_version": 1, "concepts": {
                "Day1-A": {"title": "Test", "mastery": 0.3,
                           "evidence": evidence, "last_review_day": 1,
                           "review_due": []}
            }}
            svc._load_json = MagicMock(return_value=model)
            return svc

    def test_no_evidence(self):
        svc = self._make_service([])
        result = svc.get_consecutive_errors("Day1-A")
        self.assertEqual(result, [])

    def test_single_wrong(self):
        svc = self._make_service([
            {"type": "quiz_wrong", "error_pattern_major": "CONCEPT_CONFUSION"},
        ])
        result = svc.get_consecutive_errors("Day1-A")
        self.assertEqual(result, ["CONCEPT_CONFUSION"])

    def test_consecutive_wrong(self):
        svc = self._make_service([
            {"type": "quiz_right"},
            {"type": "quiz_wrong", "error_pattern_major": "CONCEPT_CONFUSION"},
            {"type": "quiz_wrong", "error_pattern_major": "LOGIC_BREAK"},
        ])
        result = svc.get_consecutive_errors("Day1-A")
        # 从末尾向前扫描，遇到 quiz_right 停止
        self.assertEqual(len(result), 2)
        self.assertIn("LOGIC_BREAK", result)
        self.assertIn("CONCEPT_CONFUSION", result)

    def test_stops_at_right(self):
        """遇到 quiz_right 停止。"""
        svc = self._make_service([
            {"type": "quiz_wrong", "error_pattern_major": "FORGOTTEN"},
            {"type": "quiz_right"},
            {"type": "quiz_wrong", "error_pattern_major": "CONCEPT_CONFUSION"},
        ])
        result = svc.get_consecutive_errors("Day1-A")
        # 从末尾：CONCEPT_CONFUSION → quiz_right → 停止
        self.assertEqual(result, ["CONCEPT_CONFUSION"])

    def test_no_pattern_field(self):
        """quiz_wrong 但无 error_pattern_major 字段。"""
        svc = self._make_service([
            {"type": "quiz_wrong"},  # 无 error_pattern_major
        ])
        result = svc.get_consecutive_errors("Day1-A")
        self.assertEqual(result, [])

    def test_nonexistent_concept(self):
        svc = self._make_service([])
        result = svc.get_consecutive_errors("Day99-Z")
        self.assertEqual(result, [])

    def test_quiz_score_negative(self):
        """quiz_score 负分也算错误。"""
        svc = self._make_service([
            {"type": "quiz_score", "delta": -0.2,
             "error_pattern_major": "DETAIL_ERROR"},
        ])
        result = svc.get_consecutive_errors("Day1-A")
        self.assertEqual(result, ["DETAIL_ERROR"])

    def test_quiz_score_positive_stops(self):
        """quiz_score 正分不算错误，中断连续。"""
        svc = self._make_service([
            {"type": "quiz_score", "delta": 0.3},
            {"type": "quiz_wrong", "error_pattern_major": "FORGOTTEN"},
        ])
        result = svc.get_consecutive_errors("Day1-A")
        # 从末尾：FORGOTTEN(quiz_wrong) → quiz_score(正分) → 停止
        self.assertEqual(result, ["FORGOTTEN"])


class TestBuildContextFromSession(unittest.TestCase):
    """build_context_from_session 上下文构建。"""

    def _make_deps(self, mastery=0.5, code_pass=False, patterns=None,
                   weak=None, current_day=1):
        """构建 mock 依赖。"""
        state_store = MagicMock()
        state_store.exists.return_value = True
        state_store.load.return_value = {"current_day": current_day}

        session = MagicMock()
        session.current_unit_id = "A"
        session.round_count = 5

        learner_svc = MagicMock()
        learner_svc.get_model.return_value = {
            "concepts": [{
                "id": f"Day{current_day}-A",
                "mastery": mastery,
                "has_code_pass": code_pass,
            }]
        }
        learner_svc.get_consecutive_errors.return_value = patterns or []
        learner_svc.unmastered_upstream.return_value = weak or []

        return state_store, session, learner_svc

    def test_basic_context(self):
        state_store, session, learner_svc = self._make_deps(mastery=0.6)
        ctx = build_context_from_session(state_store, session, learner_svc)
        self.assertAlmostEqual(ctx["mastery"], 0.6)
        self.assertEqual(ctx["consecutive_errors"], 0)
        self.assertEqual(ctx["error_patterns"], [])
        self.assertFalse(ctx["code_verify_pass"])

    def test_with_errors(self):
        state_store, session, learner_svc = self._make_deps(
            patterns=["CONCEPT_CONFUSION", "LOGIC_BREAK"])
        ctx = build_context_from_session(state_store, session, learner_svc)
        self.assertEqual(ctx["consecutive_errors"], 2)
        self.assertEqual(len(ctx["error_patterns"]), 2)

    def test_with_prereq_gap(self):
        state_store, session, learner_svc = self._make_deps(
            weak=[{"cid": "Day1-X", "title": "先修"}])
        ctx = build_context_from_session(state_store, session, learner_svc)
        self.assertTrue(ctx["has_prereq_gap"])
        self.assertEqual(ctx["prereq_concept_id"], "Day1-X")

    def test_no_unit(self):
        """无当前单元时返回 None mastery。"""
        state_store = MagicMock()
        session = MagicMock()
        session.current_unit_id = None
        learner_svc = MagicMock()
        ctx = build_context_from_session(state_store, session, learner_svc)
        self.assertIsNone(ctx["mastery"])
        self.assertEqual(ctx["consecutive_errors"], 0)

    def test_session_minutes_from_chat_history(self):
        state_store, session, learner_svc = self._make_deps()
        session.chat_history = [{"role": "user"} for _ in range(10)]
        ctx = build_context_from_session(state_store, session, learner_svc)
        self.assertEqual(ctx["session_minutes"], 20)  # 10 * 2

    def test_code_verify_pass(self):
        state_store, session, learner_svc = self._make_deps(code_pass=True)
        ctx = build_context_from_session(state_store, session, learner_svc)
        self.assertTrue(ctx["code_verify_pass"])


class TestIntegrationSuggestWithRealContext(unittest.TestCase):
    """集成测试：build_context → suggest_action 端到端。"""

    def test_high_mastery_advance(self):
        ctx = {"mastery": 0.8, "consecutive_errors": 0, "error_patterns": [], "code_verify_pass": True}
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.ADVANCE_NEXT)

    def test_low_mastery_with_errors_change_angle(self):
        ctx = {
            "mastery": 0.3,
            "consecutive_errors": 3,
            "error_patterns": ["CONCEPT_CONFUSION", "LOGIC_BREAK"],
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.CHANGE_ANGLE)

    def test_medium_mastery_no_code_practice(self):
        ctx = {
            "mastery": 0.65,
            "consecutive_errors": 0,
            "code_verify_pass": False,
        }
        s = suggest_action(ctx)
        self.assertEqual(s.action, TeachingAction.PRACTICE_PROJECT)


if __name__ == "__main__":
    unittest.main()
