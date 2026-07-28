"""阶段策略基类与共享 helper。

PhaseHandler：所有阶段策略的 ABC。
模块级函数：从 orchestrator 提取的共享工具函数（原为 orchestrator 私有方法）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...domain.models import SessionContext
from ...services.config_service import ConfigService
from ...services.observer import get_observer
from ...services.state_store import StateStore


class PhaseHandler(ABC):
    """阶段策略接口：orchestrator 通过 registry 委托给匹配的策略。"""

    @abstractmethod
    def matches(self, session: SessionContext) -> bool:
        """判断当前 session 是否属于本策略处理的阶段。"""

    @abstractmethod
    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        """生成本次回复的附加指令。"""

    @abstractmethod
    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        """LLM 回复完成后的状态处理。返回需要追加展示给用户的消息块。"""


# ---------------------------------------------------------------------------
# 共享 helper（从 orchestrator 私有方法提取为模块级函数）
# ---------------------------------------------------------------------------

def current_unit_title(state_store: StateStore, config: ConfigService,
                       session: SessionContext) -> str:
    """当前单元标题（原 orchestrator._current_unit_title）。"""
    try:
        state = state_store.load()
        unit = state_store.set_unit(state, session.current_unit_id)
        return unit["title"]
    except Exception as e:
        get_observer(config).log_tool(
            "silent_orch_unittitle", False, repr(e)[:200])
        return session.current_unit_id or ""


def next_unit_title(state_store: StateStore,
                    session: SessionContext) -> str | None:
    """下一未完成单元标题（原 orchestrator._next_unit_title）。"""
    state = state_store.load()
    for u in state_store.day(state)["units"]:
        if u["status"] != "completed" and u["id"] != session.current_unit_id:
            return u["title"]
    return None


def interview_title(config: ConfigService, state_store: StateStore,
                    session: SessionContext) -> str:
    """面试知识点标题（原 orchestrator._interview_title）。"""
    try:
        from ...services.learner_service import LearnerService
        day = int(state_store.load().get("current_day", 1))
        for c in LearnerService(config).get_model(day)["concepts"]:
            if c["id"] == session.interview_cid:
                return c.get("title", session.interview_cid)
    except Exception as e:
        get_observer(config).log_tool(
            "silent_orch_interviewtitle", False, repr(e)[:200])
    return session.interview_cid or "当前知识点"


def record_teach_back(quiz, state_store: StateStore, config: ConfigService,
                      session: SessionContext, score: float,
                      extra: list[str]) -> None:
    """teach_back 证据落盘（原 orchestrator._record_teach_back）。

    写入失败不阻断面试流程（铁律 15）；随后 phase 还原 STUDYING。
    """
    from datetime import date
    cid = session.interview_cid
    passed = quiz.is_pass(score)
    etype = "teach_back_pass" if passed else "teach_back_fail"
    ref = f"interview:{cid}:{date.today().isoformat()}"
    written = False
    idempotent = False
    try:
        from ...services.learner_service import LearnerService
        day = int(state_store.load().get("current_day", 1))
        written = LearnerService(config).add_evidence(
            cid, etype, ref, day)
        if not written:
            model = LearnerService(config).get_model(day)
            idempotent = any(
                ev.get("source_ref") == ref
                for c in model["concepts"] if c["id"] == cid
                for ev in c.get("evidence", []))
    except Exception as e:
        get_observer(config).log_tool(
            "silent_orch_teachback", False, repr(e)[:200])
    if written:
        note = "teach_back 证据已落盘"
    elif idempotent:
        note = "今日已记录过本场面试证据（幂等跳过）"
    else:
        note = "证据落盘失败（不影响流程）"
    extra.append(
        f"🎤 模拟面试结束：终评 {score} 分（{'通过' if passed else '未通过'}），{note}。")
    from ...domain.enums import DayPhase
    session.day_phase = DayPhase.STUDYING.value
    session.interview_cid = ""
    session.interview_round = 0
    session.interview_score = None
