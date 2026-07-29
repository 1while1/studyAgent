"""教学行动策略库（M1.2 教学大脑）

基于 Bloom 掌握学习 + 脚手架理论（参考 M1_Research_Report.md §1.3）
推荐确认制：每回合生成教学建议，用户可确认或跳过

7 个教学行动：
- REVIEW_PREREQ: 补先修（mastery < 0.4 且有先修链）
- RETELL_CORE: 重讲核心（连续错误 >= 2）
- VARIANT_QUIZ: 出变体题（mastery 0.4-0.7）
- ADVANCE_NEXT: 推进下一概念（mastery >= 0.7）
- REST: 休息（连续学习 > 45 分钟）
- CHANGE_ANGLE: 换角度（同一概念连续错误模式不同）
- PRACTICE_PROJECT: 练项目（mastery >= 0.6 且 code_verify 未完成）
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TeachingAction(str, Enum):
    REVIEW_PREREQ = "REVIEW_PREREQ"
    RETELL_CORE = "RETELL_CORE"
    VARIANT_QUIZ = "VARIANT_QUIZ"
    ADVANCE_NEXT = "ADVANCE_NEXT"
    REST = "REST"
    CHANGE_ANGLE = "CHANGE_ANGLE"
    PRACTICE_PROJECT = "PRACTICE_PROJECT"


@dataclass
class TeachingSuggestion:
    """教学建议"""
    action: TeachingAction
    reason: str               # 为什么推荐这个行动
    confidence: float         # 0.0-1.0
    concept_id: Optional[str] = None  # 关联的概念

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "confidence": self.confidence,
            "concept_id": self.concept_id,
        }


def suggest_action(context: dict) -> TeachingSuggestion:
    """根据学习者上下文推荐教学行动

    Args:
        context: {
            "mastery": float,           # 当前概念掌握度 0-1
            "consecutive_errors": int,  # 连续错误数
            "error_patterns": list[str],# 最近的错误模式
            "session_minutes": int,     # 本次学习时长（分钟）
            "code_verify_pass": bool,   # 代码验证是否通过
            "has_prereq_gap": bool,     # 是否有先修缺口
            "prereq_concept_id": str | None,  # 先修概念 id
        }

    Returns:
        TeachingSuggestion 推荐的教学行动
    """
    mastery = context.get("mastery") or 0.5
    consecutive_errors = context.get("consecutive_errors") or 0
    error_patterns = context.get("error_patterns") or []
    session_minutes = context.get("session_minutes") or 0
    code_verify_pass = context.get("code_verify_pass") or False
    has_prereq_gap = context.get("has_prereq_gap") or False
    prereq_concept_id = context.get("prereq_concept_id")

    # ---- 规则优先级（从高到低） ----

    # 1. 休息（长时间学习后）
    if session_minutes >= 45:
        return TeachingSuggestion(
            action=TeachingAction.REST,
            reason=f"已连续学习 {session_minutes} 分钟，建议休息",
            confidence=0.9,
        )

    # 2. 补先修（有先修缺口且掌握度低）
    if has_prereq_gap and mastery < 0.5:
        return TeachingSuggestion(
            action=TeachingAction.REVIEW_PREREQ,
            reason=f"先修概念 {prereq_concept_id} 存在缺口",
            confidence=0.85,
            concept_id=prereq_concept_id,
        )

    # 3. 换角度（错误模式多样）
    if len(set(error_patterns)) >= 2 and consecutive_errors >= 2:
        return TeachingSuggestion(
            action=TeachingAction.CHANGE_ANGLE,
            reason=f"检测到 {len(set(error_patterns))} 种不同错误模式",
            confidence=0.8,
        )

    # 4. 重讲核心（连续错误）
    if consecutive_errors >= 2:
        return TeachingSuggestion(
            action=TeachingAction.RETELL_CORE,
            reason=f"连续 {consecutive_errors} 次错误，需要重新讲解核心概念",
            confidence=0.8,
        )

    # 5. 练项目（掌握度中等 + 代码未验证）
    if mastery >= 0.6 and not code_verify_pass:
        return TeachingSuggestion(
            action=TeachingAction.PRACTICE_PROJECT,
            reason="掌握度中等，建议通过项目实践巩固",
            confidence=0.75,
        )

    # 6. 出变体题（掌握度低-中）
    if mastery < 0.7:
        return TeachingSuggestion(
            action=TeachingAction.VARIANT_QUIZ,
            reason=f"掌握度 {mastery:.0%}，通过变体题加强理解",
            confidence=0.7,
        )

    # 7. 推进下一概念（掌握度高）
    return TeachingSuggestion(
        action=TeachingAction.ADVANCE_NEXT,
        reason=f"掌握度 {mastery:.0%}，可以推进下一概念",
        confidence=0.85,
    )


def build_context_from_session(state_store, session, learner_service) -> dict:
    """从当前会话状态构建教学建议上下文（M1.2 suggest_action 输入）。

    Args:
        state_store: StateStore 实例（读取学习状态）
        session: SessionContext 实例（运行时会话）
        learner_service: LearnerService 实例（学习者模型查询）

    Returns:
        suggest_action 所需的 context dict
    """
    from ..domain.models import SessionContext

    # 默认值
    mastery = 0.5
    consecutive_errors = 0
    error_patterns: list[str] = []
    session_minutes = 0
    code_verify_pass = False
    has_prereq_gap = False
    prereq_concept_id = None

    # 从 session 获取当前单元
    current_unit_id = getattr(session, "current_unit_id", None)
    if not current_unit_id:
        return {
            "mastery": mastery,
            "consecutive_errors": consecutive_errors,
            "error_patterns": error_patterns,
            "session_minutes": session_minutes,
            "code_verify_pass": code_verify_pass,
            "has_prereq_gap": has_prereq_gap,
            "prereq_concept_id": prereq_concept_id,
        }

    # 从 state_store 获取当前天数
    current_day = 1
    try:
        if state_store.exists():
            state = state_store.load()
            current_day = state.get("current_day", 1)
    except Exception:
        pass

    # 构建 concept_id
    from ..domain.learner import concept_id as make_cid
    cid = make_cid(current_day, current_unit_id)

    # 查询 mastery
    try:
        model = learner_service.get_model(current_day)
        for c in model.get("concepts", []):
            if c["id"] == cid:
                mastery = c.get("mastery", 0.5)
                # 检查代码验证状态
                code_verify_pass = c.get("has_code_pass", False)
                break
    except Exception:
        pass

    # 查询连续错误与错误模式
    try:
        patterns = learner_service.get_consecutive_errors(cid)
        error_patterns = patterns
        consecutive_errors = len(patterns)
    except Exception:
        pass

    # 检查先修缺口
    try:
        weak = learner_service.unmastered_upstream([cid], current_day)
        if weak:
            has_prereq_gap = True
            prereq_concept_id = weak[0].get("cid")
    except Exception:
        pass

    # 会话时长（从 round_count 粗略估算，每轮约 2-3 分钟）
    session_minutes = getattr(session, "round_count", 0) * 3

    return {
        "mastery": mastery,
        "consecutive_errors": consecutive_errors,
        "error_patterns": error_patterns,
        "session_minutes": session_minutes,
        "code_verify_pass": code_verify_pass,
        "has_prereq_gap": has_prereq_gap,
        "prereq_concept_id": prereq_concept_id,
    }
