"""学习者模型域纯函数（M3）：concept id 铸造、mastery 计算、复习间隔。零 IO。

设计依据 docs/AgentDesign.md v3 §3 三张硬表：
- mastery = clamp(Σ(delta_i × 0.5^(距今工作区天数/半衰期)), 0, 上限)
- 上限规则：无 code_verify_pass 证据的 concept，mastery 封顶 0.6（防"看懂"幻觉）
- 复习间隔 = f(mastery)：<0.4 → 1 天，<0.7 → 3 天，否则 7 天；过期累积不消失
"""

from __future__ import annotations

from datetime import date


def concept_id(day: int, unit_id: str) -> str:
    """concept id 由代码确定性铸造（Day{N}-{单元id}），禁止 LLM 造。"""
    return f"Day{day}-{unit_id}"


def _days_between(ts: str, today: date) -> int:
    """证据日期 → 距今天数（负数按 0 计，防未来日期倒挂）。"""
    try:
        d = date.fromisoformat(ts)
    except (ValueError, TypeError):
        return 0
    return max(0, (today - d).days)


def compute_mastery(evidence: list[dict], today: date, half_life: float,
                    cap_without_code: float) -> tuple[float, float, bool]:
    """按衰减公式累加证据。返回 (mastery, uncapped, capped)。

    evidence 项需含 delta(±) 与 ts(YYYY-MM-DD)；latency_s 等附加字段忽略。
    """
    total = 0.0
    for ev in evidence:
        age = _days_between(ev.get("ts", ""), today)
        total += ev.get("delta", 0.0) * (0.5 ** (age / half_life))
    uncapped = min(1.0, max(0.0, total))
    has_code_pass = any(ev.get("type") == "code_verify_pass" for ev in evidence)
    capped = False
    mastery = uncapped
    if not has_code_pass and uncapped > cap_without_code:
        mastery = cap_without_code
        capped = True
    return mastery, uncapped, capped


def review_interval(mastery: float) -> int:
    """复习间隔（天）：薄弱 1 天、中等 3 天、扎实 7 天。"""
    if mastery < 0.4:
        return 1
    if mastery < 0.7:
        return 3
    return 7


def is_due(review_due: list[int], current_day: int) -> bool:
    """到期未复习即保持到期（累积不消失），直到有新证据重排。"""
    return bool(review_due) and current_day >= min(review_due)
