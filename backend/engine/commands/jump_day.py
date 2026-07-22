"""[跳转天数] Day <X>：强制调整活跃天数并重置路线图。"""

from __future__ import annotations

import re

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps


class JumpDayHandler(CommandHandler):
    name = "jump_day"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "StudyState.json 不存在。"
        if args.strip() in ("[是]", "是"):
            return None  # 用户已确认重置
        m = re.search(r"(\d+)", args)
        if not m:
            total = deps.config.workspace.total_days
            return f"用法：[跳转天数] Day <X>（1-{total}）"
        x = int(m.group(1))
        total = deps.config.workspace.total_days
        if not 1 <= x <= total:
            return f"跳转天数超出范围，必须在 1-{total} 之间。"
        state = deps.state_store.load()
        if str(x) in state.get("days", {}) and state["days"][str(x)].get("units"):
            return (f"检测到 Day {x} 已有历史进度。重置该天进度？\n"
                    f"回 [跳转天数] {x} 是 重置 / 回 [否] 保留历史继续。")
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        m = re.search(r"(\d+)", args)
        if not m:
            return CommandResult(
                messages=["未识别到天数，请回复带数字的格式，如：[跳转天数] Day 3"])
        x = int(m.group(1))
        state = deps.state_store.load()

        state["current_day"] = x
        day_data = deps.state_store.ensure_day(state, x)
        if args.strip() in ("[是]", "是") or not day_data.get("units"):
            day_data["units"] = []
            day_data["sync_records"] = {"mastered": [], "stuck": [],
                                        "questions": [], "code_completed": []}
            day_data["review_completed"] = False
            day_data["review_score"] = 0.0
        # 之前的天标记完成、之后的清除
        for key in list(state["days"].keys()):
            d = int(key)
            if d < x:
                state["days"][key]["active_day_completed"] = True
                if not state["days"][key].get("units"):
                    state["days"][key]["review_completed"] = True
            elif d > x:
                del state["days"][key]
        deps.state_store.recompute_percentage(state)

        study_content = deps.study_plan.read()
        study_content = deps.study_plan.update_header(
            study_content, x, state["overall_completion_percentage"])
        deps.backup.atomic_persist(
            {deps.state_store.path: deps.state_store.dump(state),
             deps.config.docx_dir / "Study.md": study_content},
            validator=deps.validator())

        goal = ""
        try:
            goal = deps.study_plan.parse_day(x)["goal"]
        except Exception:
            pass
        session.day_phase = DayPhase.NOT_STARTED.value
        session.current_unit_id = None
        session.current_stage = ""
        deps.session_store.save(session)

        msg = (deps.templates.get("jump_confirm")
               .replace("<X>", str(x))
               .replace("<Y>", str(state["overall_completion_percentage"]))
               .replace("<大纲目标>", goal or "见 Study.md"))
        return CommandResult(
            messages=[msg, "请说 [开始今日学习] 生成当日详细计划并开始导学。"])
