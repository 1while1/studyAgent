"""[模拟面试]：确定性选题 + 进入口述环节（M5c）。

选题代码强制（不依赖 LLM 自觉）：args 指定（concept id 或标题精确匹配）>
当前单元 concept > 有证据 concept 中 mastery 最低者。进入后由 orchestrator
的 INTERVIEW 分支驱动「口述 → 四档评估 → 两轮追问 → teach_back 落盘」。
"""

from __future__ import annotations

from ...domain.enums import DayPhase
from ...domain.learner import concept_id
from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps


class InterviewHandler(CommandHandler):
    name = "interview"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "还没初始化学习数据，请先 [开始今日学习]。"
        if session.day_phase == DayPhase.REVIEWING.value:
            return "今日复盘进行中，请先完成复盘再开始模拟面试。"
        if session.day_phase == DayPhase.INTERVIEW.value:
            return "模拟面试已在进行中，请先完成本场面试。"
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        from ...services.learner_service import LearnerService
        day = deps.state_store.load().get("current_day", 1)
        model = LearnerService(deps.config).get_model(day)
        concepts = model["concepts"]
        if not concepts:
            return CommandResult(messages=[
                "还没有可面试的知识点（学习者模型为空）。"
                "请先完成一些单元的学习再来模拟面试。"])
        token = (args or "").strip()
        picked = None
        if token:
            picked = next((c for c in concepts
                           if token in (c["id"], c.get("title", ""))), None)
            if picked is None:
                ids = "、".join(c["id"] for c in concepts[:10])
                return CommandResult(messages=[
                    f"没找到指定知识点「{token}」。当前可面试知识点：{ids}"])
        elif session.current_unit_id:
            cid = concept_id(day, session.current_unit_id)
            picked = next((c for c in concepts if c["id"] == cid), None)
        if picked is None:
            evidenced = [c for c in concepts if c.get("evidence")]
            if not evidenced:
                return CommandResult(messages=[
                    "学习者模型中还没有带证据的知识点，"
                    "请先完成单元考核再来模拟面试。"])
            picked = min(evidenced, key=lambda c: c.get("mastery", 0))
        cid = picked["id"]
        title = picked.get("title", cid)
        session.day_phase = DayPhase.INTERVIEW.value
        session.interview_cid = cid
        session.interview_round = 0
        deps.session_store.save(session)
        from ...engine.tool_registry import render_pedagogy
        instruction = render_pedagogy("retell_guide.md", 知识点=title,
                                      薄弱点=self._weak(picked))
        return CommandResult(
            messages=[f"🎤 模拟面试开始：本场知识点 **{title}**（{cid}）。"],
            llm_instruction=instruction, sop_card="")

    @staticmethod
    def _weak(c: dict) -> str:
        ev = c.get("evidence", [])
        if not ev:
            return "该知识点暂无历史证据（尚未考核过）。"
        recent = ev[-3:]
        return (f"当前掌握度 {c.get('mastery', 0):.2f}；最近证据："
                + "、".join(f"{e.get('type')}({e.get('ts', '')})"
                            for e in recent))
