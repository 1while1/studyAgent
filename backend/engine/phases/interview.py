"""InterviewPhase：模拟面试（M5c）阶段策略。

口述评估 → 两轮追问 → 终评落 teach_back 证据。
"""

from __future__ import annotations

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from ..tool_registry import render_pedagogy
from .base import PhaseHandler, interview_title, record_teach_back


class InterviewPhase(PhaseHandler):
    """模拟面试：round 0 收口述评分 → 两轮追问 → 终评落 teach_back。"""

    def __init__(self, config, quiz, state_store):
        self._config = config
        self._quiz = quiz
        self._state_store = state_store

    def matches(self, session: SessionContext) -> bool:
        return session.day_phase == DayPhase.INTERVIEW.value

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        title = interview_title(self._config, self._state_store, session)
        if session.interview_round == 0:
            return render_pedagogy("retell_assess.md", 知识点=title)
        if session.interview_round == 1:
            return render_pedagogy("probe_followup.md", 知识点=title)
        return (render_pedagogy("probe_followup.md", 知识点=title)
                + "\n\n本回合是最后一轮：点评后给出终评，评分必须输出为"
                  "【评分：X.X】（1.0-5.0），不再出新题。")

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        extra: list[str] = []
        if session.interview_round == 0:
            score = self._quiz.extract_score(assistant_text)
            if score is None:
                extra.append("（系统提示：AI 未输出【评分：X.X】标记，"
                             "请追问「你的评分是多少」）")
            else:
                session.interview_score = score  # 独立于 quiz pending_score（R4）
                session.interview_round = 1
        elif session.interview_round == 1:
            session.interview_round = 2
        else:
            score = self._quiz.extract_score(assistant_text)
            if score is None:
                extra.append("（系统提示：AI 未输出终评【评分：X.X】标记，"
                             "请追问「最终评分是多少」）")
            else:
                record_teach_back(
                    self._quiz, self._state_store, self._config,
                    session, score, extra)
        return extra
