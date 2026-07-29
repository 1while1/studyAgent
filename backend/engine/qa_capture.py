"""拷打反喂话术（M4）：复盘评分落盘后，从拷问转录提炼话术沉淀到 InterviewQA.md。

触发：orchestrator.post_process 复盘评分分支置 session.pending_qa_capture；
执行：chat 路由在回复完成后调用 run_capture（一次非流式 LLM 调用）。
产出契约：LLM 只填内容，validate_capture 机械校验把关格式（失败重试一次，
再失败静默放弃）；`**产出来源**：` 行由服务端强制覆写为
`Day {current_day} 复盘拷打`（end_day 按此前缀统计条数，契约不可破）；
同名标题已存在时跳过（重复复盘不产生重复条目）。
"""

from __future__ import annotations

from ..services.config_service import PROMPTS_DIR
from ..services.qa_service import QaService, render_entry, validate_capture
from ..services.observer import get_observer
from ..domain.error_pattern import extract_error_pattern


def run_capture(deps, session) -> list[str]:
    """执行一次拷打反喂。返回追加展示给用户的消息块（无产出为空列表）。

    任何异常静默吞掉——反喂是增益功能，绝不阻断复盘主流程。
    """
    config = deps.config
    if not config.get("qa_capture_enabled", True):
        return []
    try:
        transcript = session.chat_history[session.review_msg_start:]
        if not transcript:
            return []
        text = "\n\n".join(
            f"{'用户' if m.get('role') == 'user' else 'AI'}：{m.get('content', '')}"
            for m in transcript)
        max_entries = int(config.get("qa_capture_max_entries", 2))
        try:
            day = int(deps.state_store.load().get("current_day", 0))
        except Exception:
            day = 0
        prompt = ((PROMPTS_DIR / "qa_capture.md").read_text(encoding="utf-8")
                  .replace("<条数>", str(max_entries))
                  .replace("<转录>", text))
        entries, raw_output = _generate(deps, prompt)
        if not entries:
            return []
        qa = QaService(config)
        existing = {e["title"] for e in qa.entries()}
        added: list[str] = []
        for e in entries[:max_entries]:
            if e["title"] in existing:
                continue
            e["source"] = f"Day {day} 复盘拷打"  # 服务端强制覆写来源行
            qa.add_entry(render_entry(e))
            existing.add(e["title"])
            added.append(e["title"])
        if not added:
            return []
        # M1.1：尝试从 LLM 原始输出提取错误分类，写入 evidence（静默失败）
        try:
            _write_error_patterns(deps, session, raw_output, day)
        except Exception:
            pass
        return ["🎙 拷打反喂：已沉淀 "
                f"{len(added)} 条话术到 InterviewQA.md（话术页可查看/编辑）：\n"
                + "\n".join(f"- {t}" for t in added)]
    except Exception as e:
        get_observer(config).log_tool(
            "silent_qa_capture", False, repr(e)[:200])
        return []


def _generate(deps, prompt: str) -> tuple[list[dict] | None, str]:
    """LLM 提炼 + 机械校验；失败带原因重试一次，再失败返回 (None, last_output)。"""
    messages = [{"role": "user", "content": prompt}]
    out = ""
    for _ in range(2):
        out = deps.llm.chat(messages, max_tokens=2000)
        entries = validate_capture(out)
        if entries:
            return entries, out
        messages = [
            messages[0],
            {"role": "assistant", "content": out},
            {"role": "user", "content":
             "格式校验失败：每条必须含 标签/关联代码/精简版/展开版/追问预案（≥3 组 "
             "Q/A）/产出来源 全部字段。请严格按模板重新输出，只输出条目。"}]
    return None, out


def _write_error_patterns(deps, session, raw_output: str, day: int) -> None:
    """从 LLM 原始输出提取错误分类，写入当前复盘单元的 evidence（静默失败）。
    使用 deps 中的 learner_service（如可用），避免创建孤立实例。
    """
    if not raw_output:
        return
    major, minor = extract_error_pattern(raw_output)
    if major is None:
        return
    # 尝试获取当前复盘单元信息并写入 evidence
    try:
        from ..services.learner_service import LearnerService
        from ..domain.learner import concept_id
        state = deps.state_store.load()
        review_units = state.get("days", {}).get(
            str(day), {}).get("units", [])
        if not review_units:
            return
        # 优先使用 deps 中共享的 learner_service，避免孤立实例
        learner_svc = (deps.learner_service
                       if hasattr(deps, 'learner_service')
                       else LearnerService(deps.config))
        for unit in review_units:
            cid = concept_id(day, unit["id"])
            learner_svc.add_evidence(
                cid, "quiz_wrong",
                f"Day{day}-{unit['id']}:qa_capture",
                day,
                error_pattern_major=major,
                error_pattern_minor=minor)
    except Exception:
        pass
