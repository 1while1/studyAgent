"""阶段策略注册表（W3）：orchestrator 分发逻辑的策略模式重构。"""

from __future__ import annotations

from ...domain.models import SessionContext
from .base import PhaseHandler
from .ended import EndedPhase
from .interview import InterviewPhase
from .prereq import PrereqPhase
from .quiz_r1 import QuizR1Phase
from .quiz_r2 import QuizR2Phase
from .reviewing import ReviewingPhase
# from .studying import StudyingPhase  # TODO: 回合计数逻辑迁出 orchestrator 后注册


class PhaseRegistry:
    """按优先级存储 handler 列表，dispatch 返回首个匹配的策略。"""

    def __init__(self, handlers: list[PhaseHandler]):
        self._handlers = handlers

    def dispatch(self, session: SessionContext) -> PhaseHandler | None:
        """按序遍历 matches，返回首个匹配的 handler；无匹配返回 None。"""
        for h in self._handlers:
            if h.matches(session):
                return h
        return None

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        """dispatch + 委托给匹配策略的 instruction_for。"""
        handler = self.dispatch(session)
        if handler is None:
            return ""
        return handler.instruction_for(session, user_text)

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        """dispatch + 委托给匹配策略的 post_process。"""
        handler = self.dispatch(session)
        if handler is None:
            return []
        return handler.post_process(session, assistant_text)


def build_registry(config, stages, quiz, state_store, templates
                   ) -> PhaseRegistry:
    """按优先级构建并返回 PhaseRegistry 实例。

    当前注册（W3）：EndedPhase → PrereqPhase → InterviewPhase →
    ReviewingPhase → QuizR1Phase → QuizR2Phase。
    StudyingPhase 暂不注册（回合计数仍由 orchestrator else 分支处理）。
    """
    return PhaseRegistry([
        EndedPhase(),
        PrereqPhase(config=config, state_store=state_store, quiz=quiz),
        InterviewPhase(config=config, quiz=quiz, state_store=state_store),
        ReviewingPhase(config=config, state_store=state_store, quiz=quiz),
        QuizR1Phase(),
        QuizR2Phase(quiz=quiz, stages=stages, state_store=state_store,
                     templates=templates, config=config),
    ])
