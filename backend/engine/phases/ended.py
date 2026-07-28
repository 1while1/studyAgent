"""EndedPhase：当日学习已结束/未开始阶段的策略。"""

from __future__ import annotations

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from .base import PhaseHandler


class EndedPhase(PhaseHandler):
    """已结束或未开始学习：不注入任何阶段附加指令，不做阶段推进。"""

    def matches(self, session: SessionContext) -> bool:
        return session.day_phase in (DayPhase.ENDED.value,
                                     DayPhase.NOT_STARTED.value)

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        return ""

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        return []
