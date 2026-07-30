"""间隔复习调度：按 1/3/7 天间隔采集今日应回顾的历史薄弱项。

复习项来源：
- 过去 StudyMemory 的 [同步]「卡壳」条目
- 过去 StudyMemory 的 [同步]「疑问」条目（仅仍带 （待解答） 标记的）
- StudyState 中 0 < rating < 3.0 的已完成单元（低分回滚项）

仅当 (当日 - 来源天) ∈ review_intervals（默认 [1,3,7]）时到期；
总量封顶 review_max_items（默认 6），优先级：回滚 > 卡壳 > 疑问。
v1 不回写“已复习”标记——间隔到期后条目自然消失。

M1.3 增强：FSRS 自适应间隔调度（不影响原有 collect_due 逻辑）。
"""

from __future__ import annotations

from .config_service import ConfigService
from .memory_store import MemoryStore
from .state_store import StateStore
from ..domain.learning_metrics import fsrs_schedule, FSRS_DEFAULT_PARAMS

_PRIORITY = {"回滚": 0, "卡壳": 1, "疑问": 2}


def collect_due(config: ConfigService, state_store: StateStore,
                memory: MemoryStore, day: int) -> list[dict]:
    """采集第 day 天到期的复习项：[{"type": 类型, "from_day": N, "text": ...}]"""
    intervals = config.get("review_intervals", [1, 3, 7])
    max_items = int(config.get("review_max_items", 6))
    items: list[dict] = []

    for d in range(1, day):
        if (day - d) not in intervals:
            continue
        if memory.exists(d):
            content = memory.read(d)
            for text in memory.sync_items(content, "卡壳"):
                items.append({"type": "卡壳", "from_day": d, "text": text})
            for text in memory.sync_items(content, "疑问"):
                if text.endswith("（待解答）"):
                    items.append({"type": "疑问", "from_day": d,
                                  "text": text[:-len("（待解答）")]})

    if state_store.exists():
        state = state_store.load()
        pass_line = float(config.get("mastery_pass_score", 3.0))
        for d_str, day_data in state.get("days", {}).items():
            d = int(d_str)
            if d >= day or (day - d) not in intervals:
                continue
            for u in day_data.get("units", []):
                rating = u.get("rating", 0) or 0
                if u.get("status") == "completed" and 0 < rating < pass_line:
                    items.append({
                        "type": "回滚", "from_day": d,
                        "text": f"Day {d} 单元{u['id']}：{u['title']}"
                                f"（评分 {rating}）"})

    items.sort(key=lambda x: (_PRIORITY.get(x["type"], 9), x["from_day"]))
    return items[:max_items]


# ---------------------------------------------------------------------------
# FSRS 自适应调度（M1.3 增强，不影响原 collect_due）
# ---------------------------------------------------------------------------

def fsrs_review_params(config: ConfigService) -> dict:
    """从 settings.toml 读取 FSRS 参数，缺失则用默认值。"""
    cfg = config.get("fsrs_params", {}) or {}
    return {**FSRS_DEFAULT_PARAMS, **cfg}


def fsrs_next_interval(review_history: list[dict],
                       config: ConfigService) -> dict:
    """基于复习历史计算下次间隔。

    review_history: [{"date": "2026-01-01", "rating": 3}, ...]
    rating: 1(忘记) / 2(困难) / 3(良好) / 4(简单)
    返回 {"interval_days": N, "stability": S, "difficulty": D}
    """
    params = fsrs_review_params(config)
    return fsrs_schedule(review_history, params)
