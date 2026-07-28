"""ReviewingPhase：复盘拷问阶段策略。

自测结束 → 严格拷问 → 评分提取 → 落盘（atomic_persist + validator）。
"""

from __future__ import annotations

import re

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from ...services.config_service import ConfigService
from ...services.observer import get_observer
from ...services.state_store import StateStore
from .base import PhaseHandler


class ReviewingPhase(PhaseHandler):
    """复盘拷问：计数 → 提取评分 → recompute → atomic_persist → 阶段流转。"""

    def __init__(self, config: ConfigService, state_store: StateStore, quiz):
        self._config = config
        self._state_store = state_store
        self._quiz = quiz

    def matches(self, session: SessionContext) -> bool:
        return session.day_phase == DayPhase.REVIEWING.value

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        if "讲完" in user_text:
            return ("用户自测结束。进入 Step 3 严格拷问：立即出 Q1（连环追问、不给提示、"
                    "追问到源码类名方法名），之后用户每答一题你点评并出下一题，"
                    f"总题量 ≥ {self._quiz.min_review_questions}。")
        return ("复盘拷问进行中：点评用户上一题回答（引用块格式，不粉饰），"
                "然后出下一题。若已问够题量，输出评分表并给出【评分：X.X】。")

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        extra: list[str] = []

        # 1. 计数复盘拷问数
        session.review_question_count += len(
            re.findall(r"^Q\d+[:：]", assistant_text, re.MULTILINE))

        # 2. 提取评分
        score = self._quiz.extract_score(assistant_text)
        if score is not None and self._state_store.exists():
            state = self._state_store.load()
            day_data = self._state_store.day(state)
            day_data["review_completed"] = True
            day_data["review_score"] = score

            # G2c 教训核心：recompute_percentage 必须在 atomic_persist 之前
            self._state_store.recompute_percentage(state)

            from ...services.study_plan import StudyPlanStore
            plan = StudyPlanStore(self._config)
            files = {self._state_store.path: self._state_store.dump(state)}
            try:
                # Study.md 缺失/损坏时降级只落 StudyState
                files[self._config.docx_dir / "Study.md"] = plan.update_header(
                    plan.read(), state["current_day"],
                    state["overall_completion_percentage"])
            except Exception as e:
                get_observer(self._config).log_tool(
                    "silent_orch_plan", False, repr(e)[:200])

            from ...engine.hooks.validate_hook import make_validator
            from ...services.backup_service import BackupService
            BackupService(self._config).atomic_persist(
                files, validator=make_validator(self._config))

            try:
                from ...services.learner_service import LearnerService
                svc = LearnerService(self._config)
                svc.ensure_concepts(state)
                svc.record_review(state["current_day"],
                                  day_data.get("units", []), score)
            except Exception as e:
                get_observer(self._config).log_tool(
                    "silent_orch_review", False, repr(e)[:200])

            session.day_phase = DayPhase.STUDYING.value
            session.pending_qa_capture = True  # M4：触发拷打反喂话术（chat 路由执行）
            extra.append(f"复盘评分已落盘：{score} 分。")

        return extra
