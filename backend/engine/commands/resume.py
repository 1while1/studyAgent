"""[恢复学习]：从上次中断单元恢复。"""

from __future__ import annotations

import os
from datetime import datetime

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps


class ResumeHandler(CommandHandler):
    name = "resume"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "StudyState.json 不存在，请说 [开始今日学习]。"
        state = deps.state_store.load()
        if not deps.memory.exists(state["current_day"]):
            return "当日 StudyMemory 不存在，请说 [开始今日学习]。"
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        state = deps.state_store.load()
        day = state["current_day"]
        day_data = deps.state_store.day(state)
        content = deps.memory.read(day)
        checks = deps.memory.unit_checks(content)

        done = [u["title"] for u in day_data["units"]
                if checks.get(u["id"]) or u["status"] == "completed"]
        first_todo = next((u for u in day_data["units"]
                           if not checks.get(u["id"]) and u["status"] != "completed"),
                          None)
        counts = deps.memory.sync_counts(content)
        mtime = datetime.fromtimestamp(
            os.path.getmtime(deps.memory.path_for(day))).strftime("%H:%M")

        if first_todo is None:
            return CommandResult(messages=[
                f"Day {day} 单元已全部完成。可以说 [开始今日复盘] 或 [结束今日学习]。"])

        session.day_phase = DayPhase.STUDYING.value
        session.current_unit_id = first_todo["id"]
        session.current_stage = deps.stages.first
        session.round_count = 0
        session.quiz_round = 0
        deps.session_store.save(session)

        msg = (deps.templates.get("resume_summary")
               .replace("<YYYY-MM-DD>", day_data.get("date", ""))
               .replace("<N>", str(day))
               .replace("<HH:MM>", mtime)
               .replace("<首个未完成单元名>", first_todo["title"]))
        msg = msg.replace("- 已完成：<列表>",
                          f"- 已完成：{'、'.join(done) if done else '无'}")
        msg = msg.replace("- 卡壳：<列表>", f"- 卡壳：{counts.get('卡壳', 0)} 项")
        msg = msg.replace("- 待解答疑问：<列表>",
                          f"- 待解答疑问：{counts.get('疑问', 0)} 项")
        return CommandResult(
            messages=[msg],
            llm_instruction=(
                f"用户选择直接继续学习。请输出单元「{first_todo['title']}」的开场第一段"
                f"（≤300字），然后开始步骤一：文档带读。直接输出教学内容，"
                f"不要复述任何流程模板或指令文字。"),
            sop_card="")  # 纯教学内容生成：不携带 SOP 卡，防止模型复读卡片模板
