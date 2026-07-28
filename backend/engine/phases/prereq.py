"""PrereqPhase：先修诊断（M7）阶段策略。

逐 cid 评分 → 机械校验 → prereq 证据落盘。
"""

from __future__ import annotations

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from ...services.config_service import ConfigService
from ...services.observer import get_observer
from ...services.state_store import StateStore
from .base import PhaseHandler


class PrereqPhase(PhaseHandler):
    """先修诊断：逐 cid 评分 → 重试校验 → evidence 落盘 → 阶段流转。"""

    def __init__(self, config: ConfigService, state_store: StateStore, quiz):
        self._config = config
        self._state_store = state_store
        self._quiz = quiz

    def matches(self, session: SessionContext) -> bool:
        return session.day_phase == DayPhase.PREREQ.value

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        # 先修诊断（M7）：逐 cid 评分（机械契约：每目标恰好一行 DayN-X：【评分：X.X】）
        targets = session.prereq_targets or []
        listing = "\n".join(f"【{q['cid']}】{q['title']}：{q['question']}"
                            for q in targets)
        return ("你在为「先修诊断」评分。目标知识点与快测题如下：\n"
                f"{listing}\n\n"
                "用户作答见上一条消息。请逐题一句话点评（严格对标快测水位："
                "会=4-5、半会=2.5-3.5、不会=1-2），然后逐行输出评分，"
                "格式严格为 `DayN-X：【评分：X.X】`（1.0-5.0）。"
                "每个目标知识点必须恰好一行评分，禁止遗漏、禁止合并、"
                "禁止改写 concept id。")

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        extra: list[str] = []

        # 先修诊断（M7）：逐 cid 评分 → 机械校验全覆盖 → prereq 证据落盘
        targets = session.prereq_targets or []
        cids = [q["cid"] for q in targets]
        scores = self._quiz.extract_scores_by_cid(assistant_text, cids)
        missing = [c for c in cids if scores.get(c) is None]
        if missing:
            if session.prereq_retry < 1:
                session.prereq_retry += 1
                extra.append(
                    f"（系统提示：缺少 {missing} 的评分行。请补充对这些"
                    "知识点的评分，格式 `DayN-X：【评分：X.X】`）")
            else:
                # 重试用尽：fail-open 取消（不写证据，与压缩降级同款哲学）
                session.day_phase = DayPhase.STUDYING.value
                session.prereq_targets = []
                session.prereq_retry = 0
                extra.append("诊断评分两次未通过格式校验，已取消本场诊断"
                             "（未写入任何证据）。你可以继续学习，"
                             "或稍后重新 [先修诊断]。")
            return extra

        from ...services.learner_service import LearnerService
        from datetime import date
        day = 1
        if self._state_store.exists():
            day = self._state_store.load().get("current_day", 1)
        lines = []
        for q in targets:
            tcid = q["cid"]  # 避开 cid 函数级遮蔽
            score = scores[tcid]
            passed = self._quiz.is_pass(score)
            etype = "prereq_pass" if passed else "prereq_fail"
            ref = f"prereq:{tcid}:{date.today().isoformat()}"
            try:
                written = LearnerService(self._config).add_evidence(
                    tcid, etype, ref, day)
                note = ("已置初始掌握度" if written
                        else "今日已记录过（幂等跳过）")
            except Exception as e:
                get_observer(self._config).log_tool(
                    "silent_orch_prereq", False, repr(e)[:200])
                note = "落盘失败（已跳过）"  # 模型写入失败不阻断（铁律 15）
            mark = "✅" if passed else "❌"
            lines.append(f"- {mark} {tcid} {q['title']}：{score} 分，{note}")
        session.day_phase = DayPhase.STUDYING.value
        session.prereq_targets = []
        session.prereq_retry = 0
        extra.append("🩺 先修诊断完成：\n" + "\n".join(lines))
        return extra
