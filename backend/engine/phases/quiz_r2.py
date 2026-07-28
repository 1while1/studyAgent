"""QuizR2Phase：掌握度考核第二轮策略。"""

from __future__ import annotations

from ...domain.models import SessionContext
from .base import PhaseHandler, current_unit_title, next_unit_title


class QuizR2Phase(PhaseHandler):
    """第二轮考核：评分提取 + pass/fail 分支 + 模板替换。"""

    def __init__(self, quiz, stages, state_store, templates, config):
        self._quiz = quiz
        self._stages = stages
        self._state_store = state_store
        self._templates = templates
        self._config = config

    def matches(self, session: SessionContext) -> bool:
        return session.current_stage == "quiz_r2"

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        return ("用户提交了第二轮答案。点评后给出终期量化评分，"
                "评分必须输出为【评分：X.X】（1.0-5.0）。")

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        extra: list[str] = []
        score = self._quiz.extract_score(assistant_text)
        if score is None:
            extra.append("（系统提示：AI 未输出【评分：X.X】标记，请追问「你的评分是多少」）")
        else:
            session.pending_score = score
            if self._quiz.is_pass(score):
                next_unit = next_unit_title(self._state_store, session)
                session.current_stage = "scored"
                extra.append(
                    self._templates.get("next_preview")
                    .replace("<单元名>", current_unit_title(
                        self._state_store, self._config, session))
                    .replace("<下一单元名>", next_unit or "（今日单元已全部完成）")
                    .replace("<2-3 句话>", "见 Study.md 大纲")
                    .replace("<X 分钟>", "40"))
            else:
                session.current_stage = self._stages.first
                session.pending_score = None
                extra.append(
                    self._templates.get("reject_advance")
                    .replace("<单元名>", current_unit_title(
                        self._state_store, self._config, session))
                    .replace("<具体卡点>", f"终期评分 {score} 未达及格线")
                    .replace("<用户哪里没答上来 / 复述哪里有偏差>",
                             "见上方点评"))
        return extra
