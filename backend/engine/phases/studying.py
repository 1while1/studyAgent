"""StudyingPhase：普通导学阶段策略（兜底回合计数 + 掌握情况检查）。"""

from __future__ import annotations

from ...domain.models import SessionContext
from ...services.observer import get_observer
from .base import PhaseHandler


class StudyingPhase(PhaseHandler):
    """普通导学：回合计数 + 定期渲染掌握情况检查。"""

    def __init__(self, config, state_store, stages, templates):
        self._config = config
        self._state_store = state_store
        self._stages = stages
        self._templates = templates

    def matches(self, session: SessionContext) -> bool:
        return True  # 兜底策略

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        return ""

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        extra: list[str] = []
        # 回合复习（InteractionModel §3 决策 2）：每 5-6 轮自动渲染
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
                from ...engine.commands.base import render_mastery_check
                extra.append(render_mastery_check(
                    self._state_store, self._stages, self._templates,
                    session, preselect=None))
            except Exception as e:
                get_observer(self._config).log_tool(
                    "silent_orch_round", False, repr(e)[:200])
            extra.append("（系统：已到回合复习点，请按上方检查自评；"
                         "确认后可说 [下一内容] 正式推进，或继续当前讲解）")
        return extra
