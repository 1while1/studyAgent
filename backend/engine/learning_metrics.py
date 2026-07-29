"""学习效果度量（M1.3 教学大脑）

三指标组合（参考 M1_Research_Report.md §1.5）：
- 指标 A：掌握进度（evidence 数 + 天数）
- 指标 B：知识保持度（3 天后 quiz 正确率）
- 指标 C：迁移应用能力（代码验证完成度）

组合公式：mastery_score = w1*A + w2*B + w3*C
默认权重：0.3 / 0.3 / 0.4（可配）

BKT（贝叶斯知识追踪）：基于 Corbett & Anderson 1994
FSRS（Free Spaced Repetition Scheduler）：简化版间隔调度
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# 三指标组合
# ---------------------------------------------------------------------------

@dataclass
class LearningMetrics:
    """学习效果指标快照"""
    concept_id: str
    indicator_a: float   # 掌握进度 0-1
    indicator_b: float   # 知识保持度 0-1
    indicator_c: float   # 迁移应用 0-1
    mastery_score: float  # 组合分 0-1
    weights: tuple[float, float, float] = (0.3, 0.3, 0.4)


def compute_indicator_a(evidence_list: list, total_days: int) -> float:
    """指标 A：掌握进度

    = min(1.0, evidence_count / expected_count)
    expected_count = total_days * 2（每天预期 2 条 evidence）
    """
    if not evidence_list or total_days <= 0:
        return 0.0
    expected = total_days * 2
    return min(1.0, len(evidence_list) / expected)


def compute_indicator_b(quiz_results: list[dict], days_threshold: int = 3) -> float:
    """指标 B：知识保持度

    = 3 天后 quiz 的平均正确率（归一化到 0-1）
    quiz_results: [{"date": "2026-01-01", "score": 3.5}, ...]
    score 按 5 分制归一化。
    """
    if not quiz_results:
        return 0.0

    late_quizzes = []
    for qr in quiz_results:
        if qr.get("score", 0) > 0:
            late_quizzes.append(qr["score"] / 5.0)

    if not late_quizzes:
        return 0.0
    return sum(late_quizzes) / len(late_quizzes)


def compute_indicator_c(code_verify_pass: bool, has_code_concept: bool) -> float:
    """指标 C：迁移应用能力

    - 无代码概念：返回 1.0（不适用，不扣分）
    - 有代码概念 + 验证通过：1.0
    - 有代码概念 + 验证未通过：0.3（部分分）
    """
    if not has_code_concept:
        return 1.0
    return 1.0 if code_verify_pass else 0.3


def compute_mastery_score(
    indicator_a: float,
    indicator_b: float,
    indicator_c: float,
    weights: tuple[float, float, float] = (0.3, 0.3, 0.4),
) -> float:
    """组合掌握分 = w1*A + w2*B + w3*C"""
    w1, w2, w3 = weights
    return w1 * indicator_a + w2 * indicator_b + w3 * indicator_c


def compute_learning_metrics(
    concept_id: str,
    evidence_list: list,
    total_days: int,
    quiz_results: list[dict],
    code_verify_pass: bool,
    has_code_concept: bool,
    weights: tuple[float, float, float] = (0.3, 0.3, 0.4),
) -> LearningMetrics:
    """一站式计算三指标 + 组合分"""
    a = compute_indicator_a(evidence_list, total_days)
    b = compute_indicator_b(quiz_results)
    c = compute_indicator_c(code_verify_pass, has_code_concept)
    score = compute_mastery_score(a, b, c, weights)
    return LearningMetrics(
        concept_id=concept_id,
        indicator_a=round(a, 4),
        indicator_b=round(b, 4),
        indicator_c=round(c, 4),
        mastery_score=round(score, 4),
        weights=weights,
    )


# ---------------------------------------------------------------------------
# BKT — 贝叶斯知识追踪（Corbett & Anderson 1994）
# ---------------------------------------------------------------------------

BKT_DEFAULT_PARAMS: dict[str, float] = {
    "p_init": 0.1,       # 初始掌握概率
    "p_transit": 0.1,    # 学习转移概率
    "p_slip": 0.1,       # 失误概率
    "p_guess": 0.25,     # 猜测概率
}


def bkt_update(prior: float, correct: bool,
               params: dict[str, float] | None = None) -> float:
    """BKT 单次贝叶斯更新

    1. 预测  P(correct) = P(L)·(1-s) + (1-P(L))·g
    2. 更新  P(L|obs)
    3. 转移  P(L') = P(L|obs) + (1-P(L|obs))·t

    Returns:
        后验掌握概率 [0, 1]
    """
    p = params or BKT_DEFAULT_PARAMS
    p_init = p["p_init"]
    p_transit = p["p_transit"]
    p_slip = p["p_slip"]
    p_guess = p["p_guess"]

    # 预测 P(correct)
    p_correct = prior * (1 - p_slip) + (1 - prior) * p_guess
    if p_correct == 0:
        return prior

    # 更新 P(L|obs)
    if correct:
        posterior = prior * (1 - p_slip) / p_correct
    else:
        posterior = prior * p_slip / (1 - p_correct)

    # 转移 P(L') = P(L|obs) + (1 - P(L|obs)) * t
    updated = posterior + (1 - posterior) * p_transit
    return min(1.0, max(0.0, updated))


def bkt_mastery(evidence_list: list[dict],
                params: dict[str, float] | None = None) -> float:
    """从 evidence 序列计算 BKT 掌握概率

    evidence 中 type 含 quiz_right / quiz_wrong / quiz_score 的条目
    被视为观测事件；其余类型忽略。
    初始 prior = p_init。
    """
    p = params or BKT_DEFAULT_PARAMS
    prior = p["p_init"]
    for ev in evidence_list:
        etype = ev.get("type", "")
        if etype in ("quiz_right", "code_verify_pass"):
            prior = bkt_update(prior, True, p)
        elif etype in ("quiz_wrong", "code_verify_fail"):
            prior = bkt_update(prior, False, p)
        # quiz_score 按 delta 正负判断
        elif etype == "quiz_score":
            delta = ev.get("delta", 0)
            prior = bkt_update(prior, delta > 0.5, p)
    return round(prior, 4)


# ---------------------------------------------------------------------------
# FSRS — 简化版间隔调度（参考 M1_Research_Report.md §3.2）
# ---------------------------------------------------------------------------

FSRS_DEFAULT_PARAMS: dict = {
    "request_retention": 0.9,
    "w": [
        0.4, 0.6, 2.4, 5.8,          # stability 初始化
        4.93, 0.94, 0.86, 0.01,      # difficulty 初始化
        1.49, 0.14, 0.94,            # 稳定性增长
        2.18, 0.05, 0.34,            # 难度变化
        1.26, 0.29, 2.61,            # 其他
        0.0, 0.0,                    # 保留
    ],
}


def fsrs_schedule(reviews: list[dict],
                  params: dict | None = None) -> dict:
    """FSRS 调度计算（简化版）

    输入：复习历史 [{"date": "2026-01-01", "rating": 3}, ...]
    输出：{"interval_days": N, "stability": S, "difficulty": D}

    rating: 1(忘记) / 2(困难) / 3(良好) / 4(简单)
    """
    if not reviews:
        return {"interval_days": 1, "stability": 1.0, "difficulty": 5.0}

    last = reviews[-1]
    rating = last.get("rating", 3)
    review_count = len(reviews)

    # 基础间隔增长（简化：线性 × rating 系数）
    if rating <= 1:        # 忘记 → 重置
        interval = 1
    elif rating == 2:      # 困难
        interval = max(1, review_count)
    elif rating == 3:      # 良好
        interval = max(1, review_count * 2)
    else:                  # 简单
        interval = max(1, review_count * 3)

    return {
        "interval_days": min(interval, 365),   # 上限 1 年
        "stability": float(interval),
        "difficulty": round(max(1.0, 10.0 - rating * 2.0), 2),
    }


def fsrs_interval_from_evidence(evidence_list: list[dict],
                                params: dict | None = None) -> dict:
    """从 evidence 列表推导 FSRS 调度

    将 evidence 中的 quiz 类事件映射为 rating：
    - quiz_right / code_verify_pass → rating 3（良好）
    - quiz_wrong / code_verify_fail → rating 1（忘记）
    - quiz_score 按 delta 映射
    """
    reviews: list[dict] = []
    for ev in evidence_list:
        etype = ev.get("type", "")
        ts = ev.get("ts", "")
        if etype in ("quiz_right", "code_verify_pass"):
            reviews.append({"date": ts, "rating": 3})
        elif etype in ("quiz_wrong", "code_verify_fail"):
            reviews.append({"date": ts, "rating": 1})
        elif etype == "quiz_score":
            delta = ev.get("delta", 0)
            if delta >= 0.8:
                reviews.append({"date": ts, "rating": 4})
            elif delta >= 0.6:
                reviews.append({"date": ts, "rating": 3})
            elif delta >= 0.4:
                reviews.append({"date": ts, "rating": 2})
            else:
                reviews.append({"date": ts, "rating": 1})
    return fsrs_schedule(reviews, params)
