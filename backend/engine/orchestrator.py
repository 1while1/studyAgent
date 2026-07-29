"""聊天编排器：非指令消息的阶段驱动逻辑（API 层调用）。

职责：
- 根据 session 当前阶段生成 LLM 附加指令
- LLM 回复后处理：quiz 阶段评分提取、阶段流转、回合计数
- M1.2：教学行动建议生成
"""

from __future__ import annotations

from ..domain.enums import DayPhase
from ..domain.models import SessionContext
from ..engine.quiz_engine import QuizEngine
from ..engine.stage_machine import StageMachine
from ..engine.turn_engine import TurnEngine
from ..services.memory_store import MemoryStore
from ..services.state_store import StateStore
from ..services.template_service import TemplateService
from ..services.config_service import ConfigService
from ..services.observer import get_observer
from .phases import build_registry


class ChatOrchestrator(TurnEngine):
    def __init__(self, config: ConfigService, stages: StageMachine,
                 quiz: QuizEngine, state_store: StateStore,
                 memory: MemoryStore, templates: TemplateService):
        self._config = config
        self._stages = stages
        self._quiz = quiz
        self._state_store = state_store
        self._memory = memory
        self._templates = templates
        self._registry = build_registry(
            config, stages, quiz, state_store, templates)

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        """生成本次回复的附加指令。"""
        if session.day_phase in (DayPhase.ENDED.value,
                                 DayPhase.NOT_STARTED.value):
            return ""  # 🟡-2：已结束/未开始学习，不注入任何阶段附加指令
        # 所有已迁移分支通过 registry 委托（PREREQ/REVIEWING/INTERVIEW/quiz_r1/quiz_r2）
        return self._registry.instruction_for(session, user_text)

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        """LLM 回复完成后的状态处理。返回需要追加展示给用户的消息块。"""
        if session.day_phase in (DayPhase.ENDED.value,
                                 DayPhase.NOT_STARTED.value):
            return []  # 🟡-2：已结束/未开始学习，不做阶段推进与回合计数
        extra: list[str] = []
        stage = session.current_stage

        # quiz_r1/quiz_r2 发生在 STUDYING 阶段，必须先于回合复习检查
        if stage in ("quiz_r1", "quiz_r2"):
            return self._registry.post_process(session, assistant_text)

        # 已迁移分支通过 registry 委托（PREREQ/REVIEWING/INTERVIEW）
        if session.day_phase != DayPhase.STUDYING.value:
            return self._registry.post_process(session, assistant_text)

        # STUDYING 阶段：回合复习（InteractionModel §3 决策 2）：每 5-6 轮自动渲染
        # 掌握情况检查（与 [下一内容] 共用同一渲染函数，选项原样由用户自评）
        session.round_count += 1
        try:
            lo, hi = [int(x) for x in self._config.get(
                "round_review_interval", [5, 6])]
        except (TypeError, ValueError):
            lo, hi = 5, 6
        lo = max(1, lo)  # 🟡-6：[0,0]/[0,1] 钳制（防每轮都渲染）  # 🟡-5：非二元组/非数值回退默认
        if session.round_count >= lo:
            session.round_count = 0
            try:
                from .commands.base import render_mastery_check
                extra.append(render_mastery_check(
                    self._state_store, self._stages, self._templates,
                    session, preselect=None))
            except Exception as e:
                get_observer(self._config).log_tool(
                    "silent_orch_round", False, repr(e)[:200])
            extra.append("（系统：已到回合复习点，请按上方检查自评；"
                         "确认后可说 [下一内容] 正式推进，或继续当前讲解）")
        return extra

    def generate_teaching_suggestion(self, session: SessionContext
                                     ) -> dict | None:
        """M1.2：生成教学行动建议并存入 session。

        在 STUDYING 阶段每回合结束时调用，返回建议 dict（可序列化）或 None。
        异常静默吞掉（铁律 13：观测不阻断）。
        """
        if session.day_phase != DayPhase.STUDYING.value:
            return None
        try:
            from .teaching_strategy import suggest_action, build_context_from_session
            from ..services.learner_service import LearnerService
            learner_svc = LearnerService(self._config)
            ctx = build_context_from_session(self._state_store, session, learner_svc)
            suggestion = suggest_action(ctx)
            if suggestion is None:
                return None
            result = suggestion.to_dict()
            # 与上次建议对比，相同则不重复弹出
            prev = getattr(session, "pending_teaching_suggestion", None)
            if prev and prev.get("action") == result.get("action") and prev.get("concept_id") == result.get("concept_id"):
                return None
            session.pending_teaching_suggestion = result
            return result
        except Exception as e:
            get_observer(self._config).log_tool(
                "silent_teaching_suggest", False, repr(e)[:200])
            return None
