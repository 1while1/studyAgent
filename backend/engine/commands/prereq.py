"""[先修诊断]（M7 §4）：进入新分支前 3-5 题快测，已会节点置初始 mastery。

流程（确定性代码强制，不靠 LLM 自觉）：
1. fail_fast：仅导学中（STUDYING）可发起（行为矩阵与模拟面试对称）。
2. run：代码选题——当前单元的上游未达标链（unmastered_upstream，拓扑序
   根基先补，含零证据节点）前 5 个；无目标 → 明确提示不开空头诊断。
3. 一次非流式 LLM 出题（resources/pedagogy/prereq_quiz.md 策略卡），
   机械校验每 cid 恰好一题（缺一带原因重试一次，再不齐 fail-closed 不开场）。
4. 设 DayPhase.PREREQ + prereq_targets；评分由 orchestrator 的 PREREQ
   分支驱动（逐 cid 评分 → 机械校验全覆盖 → prereq_pass/fail 证据落盘）。
"""

from __future__ import annotations

import re

from ...domain.enums import DayPhase
from ...domain.learner import concept_id
from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps

_MAX_TARGETS = 5


class PrereqHandler(CommandHandler):
    name = "prereq"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "还没初始化学习数据，请先 [开始今日学习]。"
        if session.day_phase == DayPhase.PREREQ.value:
            return "先修诊断已在进行中，请先完成本场诊断。"
        if session.day_phase != DayPhase.STUDYING.value:
            labels = {DayPhase.REVIEWING.value: "今日复盘进行中，请先完成复盘",
                      DayPhase.ENDED.value: "今日学习已结束，请明天再来",
                      DayPhase.NOT_STARTED.value: "今日尚未开始，请先 [开始今日学习]",
                      DayPhase.PLANNING.value: "今日计划生成中，请稍后",
                      DayPhase.INTERVIEW.value: "模拟面试进行中，请先完成面试"}
            return (labels.get(session.day_phase, "当前状态不能开始先修诊断")
                    + "。")
        return None

    # ---- 选题 ----

    @staticmethod
    def _targets(deps: Deps, session: SessionContext, day: int) -> list[dict]:
        from ...services.learner_service import LearnerService
        unit_id = session.current_unit_id
        if not unit_id:
            state = deps.state_store.load()
            units = state["days"].get(str(day), {}).get("units", [])
            unit_id = units[0]["id"] if units else "A"
        cid = concept_id(day, unit_id)
        return LearnerService(deps.config).unmastered_upstream(
            [cid], day)[:_MAX_TARGETS]

    # ---- 出题（一次 LLM + 机械校验，缺一带原因重试一次） ----

    @staticmethod
    def _gen_questions(deps: Deps, targets: list[dict],
                       unit_title: str) -> list[dict] | None:
        from ...engine.tool_registry import render_pedagogy
        listing = "\n".join(
            f"- {t['cid']}：{t['title']}（当前掌握度 {t['mastery']:.2f}"
            f"{'，未学' if not t['has_evidence'] else ''}）"
            for t in targets)
        prompt = render_pedagogy("prereq_quiz.md",
                                 今日单元=unit_title, 目标清单=listing)
        if not prompt:
            return None  # 缺策略卡 fail-closed（与面试 R7 同款）
        wanted = [t["cid"] for t in targets]

        def parse(text: str) -> tuple[list[dict] | None, str]:
            found = {}
            for m in re.finditer(r"【(Day\d+-[^】]+)】([^\n【]+)", text):
                cid, q = m.group(1).strip(), m.group(2).strip()
                if cid in wanted and q:
                    found[cid] = q
            missing = [c for c in wanted if c not in found]
            if missing:
                return None, f"缺少知识点 {missing} 的题目"
            return [{"cid": c, "title": next(t["title"] for t in targets
                                             if t["cid"] == c),
                     "question": found[c]} for c in wanted], ""

        from ...services.observer import task_scope
        try:
            with task_scope("tool"):
                first = deps.llm.chat(
                    [{"role": "user", "content": prompt}], max_tokens=2000)
        except Exception:
            return None
        questions, why = parse(first or "")
        if questions is not None:
            return questions
        try:  # 带原因重试一次（与 qa_capture 同款机械校验哲学）
            with task_scope("tool"):
                second = deps.llm.chat(
                    [{"role": "user", "content": prompt},
                     {"role": "assistant", "content": first or ""},
                     {"role": "user", "content":
                      f"上次输出未通过校验：{why}。请严格按格式重新输出，"
                      "每个知识点一段，以【DayN-X】开头。"}],
                    max_tokens=2000)
        except Exception:
            return None
        questions, _ = parse(second or "")
        return questions

    # ---- 主流程 ----

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        day = deps.state_store.load().get("current_day", 1)
        targets = self._targets(deps, session, day)
        if not targets:
            return CommandResult(messages=[
                "当前单元的先修链上没有未达标节点（上游全部达标或无上游），"
                "无需先修诊断，继续当前学习即可。"])
        unit_title = next(
            (u.get("title", "") for u in
             deps.state_store.load()["days"].get(str(day), {}).get("units", [])
             if u["id"] == (session.current_unit_id or "")), "")
        questions = self._gen_questions(deps, targets, unit_title or "当前单元")
        if questions is None:
            return CommandResult(messages=[
                "诊断出题未通过格式校验（知识点覆盖缺失或资源缺失），"
                "本场诊断未开始，学习者模型未做任何改动，请稍后再试。"])
        session.day_phase = DayPhase.PREREQ.value
        session.prereq_targets = questions
        session.prereq_retry = 0
        deps.session_store.save(session)
        lines = "\n\n".join(f"**【{q['cid']}】{q['title']}**\n{q['question']}"
                            for q in questions)
        return CommandResult(messages=[
            f"🩺 先修诊断开始：今日单元的先修链上有 {len(questions)} "
            f"个未达标节点。请依次作答（每题一两句话即可，会就是会、不会就说不会），"
            f"我将逐题评分；通过的节点会置初始掌握度，跳过重复教学。\n\n{lines}"])
