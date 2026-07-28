"""QuizR1Phase：掌握度考核第一轮策略。"""

from __future__ import annotations

from ...domain.models import SessionContext
from .base import PhaseHandler


class QuizR1Phase(PhaseHandler):
    """第一轮考核：点评后出第二轮检验题。"""

    def matches(self, session: SessionContext) -> bool:
        return session.current_stage == "quiz_r1"

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        return ("用户提交了第一轮答案。先专业点评（纠正概念偏差、给出面试口径），"
                "然后立即出第二轮检验题（触及底层原理 Why/Where），出题后停止。")

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        session.current_stage = "quiz_r2"
        session.quiz_round = 2
        return []
