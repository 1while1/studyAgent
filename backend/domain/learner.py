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


# ---- 课程图谱（M7 §4）：先修链闭包与拓扑序。零 IO，prereq_map 由调用方装配 ----

def upstream_closure(cid: str, prereq_map: dict[str, list[str]]) -> list[str]:
    """cid 的全部传递上游（先修链闭包），DFS 后序 = 根基在前、近邻在后。

    - 环守卫：异常数据成环时不死循环，成环节点按首次访问序返回
    - 缺失容忍：prereq_map 中不存在的节点按无上游处理
    - 返回不含 cid 本身
    """
    ordered: list[str] = []
    state: dict[str, int] = {}  # 0=未访 1=在栈 2=完成

    def dfs(node: str) -> None:
        if state.get(node, 0) != 0:
            return
        state[node] = 1
        for pre in prereq_map.get(node, []):
            if state.get(pre, 0) == 1:
                continue  # 环：跳过回边
            dfs(pre)
        state[node] = 2
        if node != cid:
            ordered.append(node)

    dfs(cid)
    return ordered


def topo_order(cids: list[str] | set[str],
               prereq_map: dict[str, list[str]]) -> list[str]:
    """给定节点集合的拓扑补弱序（上游先补）：闭包深度小者（根基）在前，同层按 id 稳定序。

    深度 = 该节点上游闭包大小（根基=0、越下游越大），使集合内任何节点的
    上游都排在其前面（只要上游也在集合内）。
    """
    depth_cache: dict[str, int] = {}

    def depth(cid: str) -> int:
        if cid not in depth_cache:
            depth_cache[cid] = len(upstream_closure(cid, prereq_map))
        return depth_cache[cid]

    return sorted(set(cids), key=lambda c: (depth(c), c))
