"""[开始今日复盘]：4 步严格拷打（回顾 → 自测 → 拷问 → 评分）。"""

from __future__ import annotations

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps


class DayReviewHandler(CommandHandler):
    name = "day_review"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "StudyState.json 不存在，请先 [开始今日学习]。"
        state = deps.state_store.load()
        day = state["current_day"]
        if not deps.memory.exists(day):
            return "先 [开始今日学习] 完成学习再复盘。"
        checks = deps.memory.unit_checks(deps.memory.read(day))
        if not any(checks.values()):
            return "今天还没学完任何单元，复盘无内容。"
        if deps.state_store.day(state).get("review_completed") and args.strip() != "是":
            return "今日已复盘，重复执行？回 [开始今日复盘] 是 继续 / 回 [否] 取消。"
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        state = deps.state_store.load()
        day = state["current_day"]
        content = deps.memory.read(day)
        checks = deps.memory.unit_checks(content)
        units = deps.state_store.day(state)["units"]
        done = [u["title"] for u in units if checks.get(u["id"])]
        todo = [u["title"] for u in units if not checks.get(u["id"])]
        counts = deps.memory.sync_counts(content)

        step1 = (deps.templates.get("review_step1")
                 .replace("<列表，从 StudyMemory>",
                          "、".join(f"单元{u['id']}" for u in units))
                 .replace("✅ 已完成：<列表>",
                          f"✅ 已完成：{'、'.join(done) if done else '无'}")
                 .replace("⚠️ 卡壳点：<列表>",
                          f"⚠️ 卡壳点：{counts.get('卡壳', 0)} 项（见 [同步] 记录）")
                 .replace("❌ 未掌握：<列表>",
                          f"❌ 未掌握：{'、'.join(todo) if todo else '无'}"))
        import re as _re
        step1 = _re.sub(r"核心知识点（我复述）：\n1\. <知识点 1>\n2\. <知识点 2>\n\.\.\.",
                        "核心知识点（由 AI 在下方复述）：", step1)

        session.day_phase = DayPhase.REVIEWING.value
        session.review_question_count = 0
        deps.session_store.save(session)

        instruction = (
            "进入今日复盘模式。先复述今日核心知识点（编号列表），然后输出「复盘 Step 2：用户自测」模板，"
            "之后沉默等用户口述。用户讲完后进入 Step 3 严格拷问：连环追问、不给提示、故意挖坑、"
            f"追问到源码类名方法名，总题量 ≥ {deps.quiz.min_review_questions} 题，"
            "每题用 Q<N> + 引用块格式，答错直接指出不粉饰。拷问结束后输出评分表并给出【评分：X.X】。")
        return CommandResult(messages=[step1], llm_instruction=instruction,
                             sop_card="SOP_开始今日复盘.md")
