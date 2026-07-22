"""[下一内容] / [强制下一内容] / [超前学习]：掌握情况检查 → 连环追问 → 落盘推进。"""

from __future__ import annotations

from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps


class NextContentHandler(CommandHandler):
    name = "next_content"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "StudyState.json 不存在，请先 [开始今日学习]。"
        state = deps.state_store.load()
        if not deps.memory.exists(state["current_day"]):
            return "当日 StudyMemory 不存在，请先 [开始今日学习]。"
        if not session.current_unit_id and mode != "ahead":
            return "当前没有明确的学习单元。你想推进到哪个单元？"
        return None

    # ---- 共用：单元落盘 + 推进 ----

    def _persist_and_advance(self, deps: Deps, session: SessionContext,
                             score: float, force: bool) -> CommandResult:
        state = deps.state_store.load()
        day = state["current_day"]
        unit_id = session.current_unit_id
        deps.state_store.set_unit(state, unit_id, status="completed", rating=score)

        content = deps.memory.read(day)
        content = deps.memory.set_unit_checked(
            content, unit_id, True, note="（未掌握-跳过）" if force else "")
        content = deps.memory.set_unit_score(content, unit_id, score)
        deps.backup.atomic_persist(
            {deps.state_store.path: deps.state_store.dump(state),
             deps.memory.path_for(day): content},
            validator=deps.validator())

        next_unit = next(
            (u for u in deps.state_store.day(state)["units"]
             if u["status"] != "completed"), None)
        if next_unit is None:
            session.current_stage = deps.stages.terminal
            deps.session_store.save(session)
            return CommandResult(messages=[
                f"单元{unit_id} 已落盘（{score}分）。\n"
                f"今日单元已全部完成，可以说 [开始今日复盘] 或 [结束今日学习]。"])

        session.current_unit_id = next_unit["id"]
        session.current_stage = deps.stages.first
        session.round_count = 0
        session.quiz_round = 0
        session.pending_score = None
        session.force_skip = False
        deps.session_store.save(session)

        opening = (deps.templates.get("unit_open")
                   .replace("<标题>", next_unit["title"])
                   .replace("<1 句话>", "掌握本单元核心概念")
                   .replace("<X>", "40", 1)
                   .replace("<1-2 个>", "面试高频考点（导学中展开）")
                   .replace("<路径>", "见 Study.md 当日大纲")
                   .replace("<引用>", "见当日推荐"))
        return CommandResult(
            messages=[f"单元{unit_id} 已落盘（{score}分）。", opening],
            llm_instruction="输出新单元开场「第一段」（≤300字），开始步骤一：文档带读。",
            sop_card="SOP_下一内容.md")

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        # ---- [强制下一内容]：跳过追问，薄弱标记落盘 ----
        if mode == "force":
            score = float(deps.config.get("force_skip_score", 2.0))
            return self._persist_and_advance(deps, session, score, force=True)

        # ---- [超前学习]：今日单元须已全部完成，拽入明日首个单元 ----
        if mode == "ahead":
            state = deps.state_store.load()
            day = state["current_day"]
            remaining = [u for u in deps.state_store.day(state)["units"]
                         if u["status"] != "completed"]
            if remaining:
                return CommandResult(messages=[
                    f"今日还有 {len(remaining)} 个单元未完成，不能超前学习。"])
            try:
                plan = deps.study_plan.parse_day(day + 1)
            except Exception as e:
                return CommandResult(messages=[f"无法加载 Day {day + 1} 大纲：{e}"])
            if not plan["units"]:
                return CommandResult(messages=[f"Day {day + 1} 无可用单元。"])
            first = plan["units"][0]
            day_data = deps.state_store.day(state)
            new_id = first["id"]
            existing = {u["id"] for u in day_data["units"]}
            if new_id in existing:
                new_id = f"{new_id}A"  # 防 id 冲突
            day_data["units"].append({
                "id": new_id, "title": f"（超前）{first['title']}",
                "status": "in_progress", "rating": 0, "ahead": True})
            content = deps.memory.read(day)
            content = content.replace(
                "### [同步] 记录",
                f"- [ ] 单元{new_id}（超前）：{first['title']}\n\n### [同步] 记录")
            deps.backup.atomic_persist(
                {deps.state_store.path: deps.state_store.dump(state),
                 deps.memory.path_for(day): content},
                validator=deps.validator())
            session.current_unit_id = new_id
            session.current_stage = deps.stages.first
            deps.session_store.save(session)
            opening = (deps.templates.get("unit_open")
                       .replace("<标题>", first["title"])
                       .replace("<1 句话>", "超前学习明日首个单元")
                       .replace("<X>", first.get("duration", "40min").replace("min", ""), 1)
                       .replace("<1-2 个>", "面试高频考点")
                       .replace("<路径>", first.get("doc") or "见大纲")
                       .replace("<引用>", "见当日推荐"))
            return CommandResult(
                messages=[f"已超前加载 Day {day + 1} 首个单元。", opening],
                llm_instruction="输出开场「第一段」（≤300字），开始步骤一：文档带读。",
                sop_card="SOP_下一内容.md")

        # ---- 阶段 = scored：本次 [下一内容] 是确认推进 → 落盘 ----
        if session.current_stage == "scored" and session.pending_score is not None:
            return self._persist_and_advance(
                deps, session, session.pending_score, force=False)

        # ---- 常规：输出掌握情况检查 + 进入 quiz_r1 ----
        state = deps.state_store.load()
        day = state["current_day"]
        unit = deps.state_store.set_unit(state, session.current_unit_id)  # 校验存在
        deps.state_store.set_unit(state, session.current_unit_id, status="in_progress")
        deps.backup.atomic_persist(
            {deps.state_store.path: deps.state_store.dump(state)},
            validator=deps.validator())

        done_stages = []
        names = deps.stages.names()
        if session.current_stage in names:
            done_stages = names[: names.index(session.current_stage) + 1]
        check = (deps.templates.get("mastery_check")
                 .replace("<填入>", unit["title"], 1)
                 .replace("<填入>",
                          "、".join(deps.stages.sop_step(s) for s in done_stages) or "见讲解记录", 1)
                 .replace("<填入>", "见对话记录", 1)
                 .replace("[已掌握 / 基本掌握 / 需巩固]", "[需巩固]"))
        if any(s == "coding" for s in done_stages):
            check = check.replace("[已完成 / 进行中 / 未开始 / 不适用]", "[已完成]")

        session.current_stage = "quiz_r1"
        session.quiz_round = 1
        deps.session_store.save(session)
        return CommandResult(
            messages=[check],
            llm_instruction="为了进行真实理解检验，我将发起连环追问。第一轮考点：本单元基础概念（What/How）。请出第一轮检验题（一道），出题后停止。",
            sop_card="SOP_下一内容.md")
