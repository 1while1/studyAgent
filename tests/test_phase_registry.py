"""PhaseRegistry 测试（W3）：dispatch 优先级、build_registry、matches 条件。

验证 orchestrator 阶段策略注册表的分发逻辑：
- 6 个策略按正确优先级注册
- dispatch 返回首个 matches 的策略
- 每个策略的 matches 条件精确匹配对应 session 状态
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.enums import DayPhase
from backend.domain.models import SessionContext
from backend.engine.phases import PhaseRegistry, build_registry
from backend.engine.phases.ended import EndedPhase
from backend.engine.phases.interview import InterviewPhase
from backend.engine.phases.prereq import PrereqPhase
from backend.engine.phases.quiz_r1 import QuizR1Phase
from backend.engine.phases.quiz_r2 import QuizR2Phase
from backend.engine.phases.reviewing import ReviewingPhase


def _make_deps():
    """构造 build_registry 所需的最小 mock 依赖。"""
    config = MagicMock()
    stages = MagicMock()
    quiz = MagicMock()
    state_store = MagicMock()
    templates = MagicMock()
    return config, stages, quiz, state_store, templates


def _make_registry() -> PhaseRegistry:
    """用 mock 依赖构建真实 PhaseRegistry。"""
    config, stages, quiz, state_store, templates = _make_deps()
    return build_registry(config, stages, quiz, state_store, templates,
                          )


# -----------------------------------------------------------------------
# 1. dispatch 优先级测试
# -----------------------------------------------------------------------

class TestDispatchPriority(unittest.TestCase):
    """验证 registry 按正确顺序匹配策略：
    ENDED/NOT_STARTED → EndedPhase
    PREREQ → PrereqPhase
    INTERVIEW → InterviewPhase
    REVIEWING → ReviewingPhase
    current_stage == 'quiz_r1' → QuizR1Phase
    current_stage == 'quiz_r2' → QuizR2Phase
    """

    def setUp(self):
        self.registry = _make_registry()

    def test_ended_dispatches_to_ended_phase(self):
        session = SessionContext(day_phase=DayPhase.ENDED.value)
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, EndedPhase)

    def test_not_started_dispatches_to_ended_phase(self):
        session = SessionContext(day_phase=DayPhase.NOT_STARTED.value)
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, EndedPhase)

    def test_prereq_dispatches_to_prereq_phase(self):
        session = SessionContext(day_phase=DayPhase.PREREQ.value)
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, PrereqPhase)

    def test_interview_dispatches_to_interview_phase(self):
        session = SessionContext(day_phase=DayPhase.INTERVIEW.value)
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, InterviewPhase)

    def test_reviewing_dispatches_to_reviewing_phase(self):
        session = SessionContext(day_phase=DayPhase.REVIEWING.value)
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, ReviewingPhase)

    def test_quiz_r1_dispatches_to_quiz_r1_phase(self):
        session = SessionContext(day_phase=DayPhase.STUDYING.value,
                                 current_stage="quiz_r1")
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, QuizR1Phase)

    def test_quiz_r2_dispatches_to_quiz_r2_phase(self):
        session = SessionContext(day_phase=DayPhase.STUDYING.value,
                                 current_stage="quiz_r2")
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, QuizR2Phase)

    def test_ended_takes_priority_over_quiz_r1(self):
        """day_phase=ENDED 且 current_stage=quiz_r1 时，EndedPhase 优先。"""
        session = SessionContext(day_phase=DayPhase.ENDED.value,
                                 current_stage="quiz_r1")
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, EndedPhase)

    def test_prereq_takes_priority_over_interview(self):
        """day_phase=PREREQ 且 day_phase 同时满足 interview 条件不可能，
        但验证 PREREQ 在注册顺序中先于 INTERVIEW。"""
        session = SessionContext(day_phase=DayPhase.PREREQ.value)
        handler = self.registry.dispatch(session)
        self.assertIsInstance(handler, PrereqPhase)

    def test_studying_no_match_returns_none(self):
        """STUDYING 阶段无注册策略（StudyingPhase 暂未注册），dispatch 返回 None。"""
        session = SessionContext(day_phase=DayPhase.STUDYING.value,
                                 current_stage="teaching")
        handler = self.registry.dispatch(session)
        self.assertIsNone(handler)

    def test_planning_no_match_returns_none(self):
        """PLANNING 阶段无注册策略，dispatch 返回 None。"""
        session = SessionContext(day_phase=DayPhase.PLANNING.value)
        handler = self.registry.dispatch(session)
        self.assertIsNone(handler)


# -----------------------------------------------------------------------
# 2. build_registry 测试
# -----------------------------------------------------------------------

class TestBuildRegistry(unittest.TestCase):
    """验证 build_registry 注册数量和顺序。"""

    def setUp(self):
        self.registry = _make_registry()

    def test_registry_has_six_handlers(self):
        """当前注册 6 个策略（StudyingPhase 暂未注册）。"""
        self.assertEqual(len(self.registry._handlers), 6)

    def test_registration_order(self):
        """注册顺序：EndedPhase → PrereqPhase → InterviewPhase →
        ReviewingPhase → QuizR1Phase → QuizR2Phase。"""
        expected_types = [
            EndedPhase,
            PrereqPhase,
            InterviewPhase,
            ReviewingPhase,
            QuizR1Phase,
            QuizR2Phase,
        ]
        actual_types = [type(h) for h in self.registry._handlers]
        self.assertEqual(actual_types, expected_types)


# -----------------------------------------------------------------------
# 3. matches 条件测试
# -----------------------------------------------------------------------

class TestEndedPhaseMatches(unittest.TestCase):

    def setUp(self):
        self.phase = EndedPhase()

    def test_matches_ended(self):
        session = SessionContext(day_phase=DayPhase.ENDED.value)
        self.assertTrue(self.phase.matches(session))

    def test_matches_not_started(self):
        session = SessionContext(day_phase=DayPhase.NOT_STARTED.value)
        self.assertTrue(self.phase.matches(session))

    def test_not_matches_studying(self):
        session = SessionContext(day_phase=DayPhase.STUDYING.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_prereq(self):
        session = SessionContext(day_phase=DayPhase.PREREQ.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_interview(self):
        session = SessionContext(day_phase=DayPhase.INTERVIEW.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_reviewing(self):
        session = SessionContext(day_phase=DayPhase.REVIEWING.value)
        self.assertFalse(self.phase.matches(session))


class TestPrereqPhaseMatches(unittest.TestCase):

    def setUp(self):
        self.phase = PrereqPhase(config=MagicMock(),
                                 state_store=MagicMock(),
                                 quiz=MagicMock())

    def test_matches_prereq(self):
        session = SessionContext(day_phase=DayPhase.PREREQ.value)
        self.assertTrue(self.phase.matches(session))

    def test_not_matches_studying(self):
        session = SessionContext(day_phase=DayPhase.STUDYING.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_ended(self):
        session = SessionContext(day_phase=DayPhase.ENDED.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_interview(self):
        session = SessionContext(day_phase=DayPhase.INTERVIEW.value)
        self.assertFalse(self.phase.matches(session))


class TestInterviewPhaseMatches(unittest.TestCase):

    def setUp(self):
        self.phase = InterviewPhase(config=MagicMock(),
                                    quiz=MagicMock(),
                                    state_store=MagicMock())

    def test_matches_interview(self):
        session = SessionContext(day_phase=DayPhase.INTERVIEW.value)
        self.assertTrue(self.phase.matches(session))

    def test_not_matches_studying(self):
        session = SessionContext(day_phase=DayPhase.STUDYING.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_prereq(self):
        session = SessionContext(day_phase=DayPhase.PREREQ.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_reviewing(self):
        session = SessionContext(day_phase=DayPhase.REVIEWING.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_ended(self):
        session = SessionContext(day_phase=DayPhase.ENDED.value)
        self.assertFalse(self.phase.matches(session))


class TestReviewingPhaseMatches(unittest.TestCase):

    def setUp(self):
        self.phase = ReviewingPhase(config=MagicMock(),
                                    state_store=MagicMock(),
                                    quiz=MagicMock())

    def test_matches_reviewing(self):
        session = SessionContext(day_phase=DayPhase.REVIEWING.value)
        self.assertTrue(self.phase.matches(session))

    def test_not_matches_studying(self):
        session = SessionContext(day_phase=DayPhase.STUDYING.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_interview(self):
        session = SessionContext(day_phase=DayPhase.INTERVIEW.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_ended(self):
        session = SessionContext(day_phase=DayPhase.ENDED.value)
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_prereq(self):
        session = SessionContext(day_phase=DayPhase.PREREQ.value)
        self.assertFalse(self.phase.matches(session))


class TestQuizR1PhaseMatches(unittest.TestCase):

    def setUp(self):
        self.phase = QuizR1Phase()

    def test_matches_quiz_r1(self):
        session = SessionContext(current_stage="quiz_r1")
        self.assertTrue(self.phase.matches(session))

    def test_not_matches_quiz_r2(self):
        session = SessionContext(current_stage="quiz_r2")
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_teaching(self):
        session = SessionContext(current_stage="teaching")
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_empty_stage(self):
        session = SessionContext(current_stage="")
        self.assertFalse(self.phase.matches(session))


class TestQuizR2PhaseMatches(unittest.TestCase):

    def setUp(self):
        self.phase = QuizR2Phase(quiz=MagicMock(), stages=MagicMock(),
                                 state_store=MagicMock(),
                                 templates=MagicMock(), config=MagicMock())

    def test_matches_quiz_r2(self):
        session = SessionContext(current_stage="quiz_r2")
        self.assertTrue(self.phase.matches(session))

    def test_not_matches_quiz_r1(self):
        session = SessionContext(current_stage="quiz_r1")
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_scored(self):
        session = SessionContext(current_stage="scored")
        self.assertFalse(self.phase.matches(session))

    def test_not_matches_empty_stage(self):
        session = SessionContext(current_stage="")
        self.assertFalse(self.phase.matches(session))


if __name__ == "__main__":
    unittest.main()
