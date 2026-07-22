"""[开始写代码]：进入/继续 coding 阶段（五步循环步骤二的显式入口）。"""

from __future__ import annotations

from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps


class CodeModeHandler(CommandHandler):
    name = "code_mode"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not session.current_unit_id:
            return "当前没有学习单元，请先 [开始今日学习]。"
        if session.current_stage == deps.stages.first:
            return f"当前单元还在导读阶段，先把理论讲完再写代码。"
        if session.current_stage == "quiz_r1" or session.current_stage == "quiz_r2":
            return "掌握度考核进行中，请先完成追问再写代码。"
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        session.current_stage = "coding"
        deps.session_store.save(session)
        limit = deps.config.get("code_line_limit", 20)
        exempt = deps.config.get("code_line_exemption_days", [21])
        state = deps.state_store.load()
        day = state["current_day"]
        unit = deps.state_store.set_unit(state, session.current_unit_id)
        if day in exempt:
            limit_note = f"今日为 Day {day}（例外日），可以生成完整 CRUD/前端代码。"
        else:
            limit_note = f"单次连续代码 ≤ {limit} 行，超过必须拆分。"
        instruction = (
            f"进入编码模式。模块：{unit['title']}。\n"
            f"请按「编码模式启动」模板输出（模块/对应原项目类/目标位置/≤5条设计要点/建议文件结构），"
            f"然后让用户先写骨架。规则：{limit_note}禁止直接给完整实现。")
        return CommandResult(messages=[], llm_instruction=instruction,
                             sop_card="SOP_开始写代码.md")
