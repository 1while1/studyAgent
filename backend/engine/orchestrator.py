"""聊天编排器：非指令消息的阶段驱动逻辑（API 层调用）。

职责：
- 根据 session 当前阶段生成 LLM 附加指令
- LLM 回复后处理：quiz 阶段评分提取、阶段流转、回合计数
"""

from __future__ import annotations

import re

from ..domain.enums import DayPhase
from ..domain.models import SessionContext
from ..engine.quiz_engine import QuizEngine
from ..engine.stage_machine import StageMachine
from ..engine.turn_engine import TurnEngine
from ..services.memory_store import MemoryStore
from ..services.state_store import StateStore
from ..services.template_service import TemplateService
from ..services.config_service import ConfigService


class ChatOrchestrator(TurnEngine):
    def __init__(self, config: ConfigService, stages: StageMachine,
                 quiz: QuizEngine, state_store: StateStore,
                 memory: MemoryStore, templates: TemplateService):
        self._config = config
        self._stages = stages
        self._quiz = quiz
        self._state_store = state_store
        self._memory = memory
        self._templates = templates

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        """生成本次回复的附加指令。"""
        stage = session.current_stage
        if session.day_phase == DayPhase.PREREQ.value:
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
        if session.day_phase == DayPhase.INTERVIEW.value:
            # 模拟面试（M5c）：口述评估 → 两轮追问 → 终评落证据
            from ..engine.tool_registry import render_pedagogy
            title = self._interview_title(session)
            if session.interview_round == 0:
                return render_pedagogy("retell_assess.md", 知识点=title)
            if session.interview_round == 1:
                return render_pedagogy("probe_followup.md", 知识点=title)
            return (render_pedagogy("probe_followup.md", 知识点=title)
                    + "\n\n本回合是最后一轮：点评后给出终评，评分必须输出为"
                      "【评分：X.X】（1.0-5.0），不再出新题。")
        if session.day_phase == DayPhase.REVIEWING.value:
            if "讲完" in user_text:
                return ("用户自测结束。进入 Step 3 严格拷问：立即出 Q1（连环追问、不给提示、"
                        "追问到源码类名方法名），之后用户每答一题你点评并出下一题，"
                        f"总题量 ≥ {self._quiz.min_review_questions}。")
            return ("复盘拷问进行中：点评用户上一题回答（引用块格式，不粉饰），"
                    "然后出下一题。若已问够题量，输出评分表并给出【评分：X.X】。")
        if stage == "quiz_r1":
            return ("用户提交了第一轮答案。先专业点评（纠正概念偏差、给出面试口径），"
                    "然后立即出第二轮检验题（触及底层原理 Why/Where），出题后停止。")
        if stage == "quiz_r2":
            return ("用户提交了第二轮答案。点评后给出终期量化评分，"
                    "评分必须输出为【评分：X.X】（1.0-5.0）。")
        # 普通导学阶段：回合计数提醒由 post_process 处理
        return ""

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        """LLM 回复完成后的状态处理。返回需要追加展示给用户的消息块。"""
        extra: list[str] = []
        stage = session.current_stage

        if session.day_phase == DayPhase.PREREQ.value:
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
            from ..services.learner_service import LearnerService
            from datetime import date
            day = 1
            if self._state_store.exists():
                day = self._state_store.load().get("current_day", 1)
            lines = []
            for q in targets:
                tcid = q["cid"]  # 避开 cid 函数级遮蔽（下文面试分支有同名赋值）
                score = scores[tcid]
                passed = self._quiz.is_pass(score)
                etype = "prereq_pass" if passed else "prereq_fail"
                ref = f"prereq:{tcid}:{date.today().isoformat()}"
                try:
                    written = LearnerService(self._config).add_evidence(
                        tcid, etype, ref, day)
                    note = ("已置初始掌握度" if written
                            else "今日已记录过（幂等跳过）")
                except Exception:
                    note = "落盘失败（已跳过）"  # 模型写入失败不阻断（铁律 15）
                mark = "✅" if passed else "❌"
                lines.append(f"- {mark} {tcid} {q['title']}：{score} 分，{note}")
            session.day_phase = DayPhase.STUDYING.value
            session.prereq_targets = []
            session.prereq_retry = 0
            extra.append("🩺 先修诊断完成：\n" + "\n".join(lines))
            return extra

        if session.day_phase == DayPhase.INTERVIEW.value:
            # 模拟面试（M5c）：round 0 收口述评分 → 两轮追问 → 终评落 teach_back
            if session.interview_round == 0:
                score = self._quiz.extract_score(assistant_text)
                if score is None:
                    extra.append("（系统提示：AI 未输出【评分：X.X】标记，"
                                 "请追问「你的评分是多少」）")
                else:
                    session.interview_score = score  # 独立于 quiz pending_score（R4）
                    session.interview_round = 1
            elif session.interview_round == 1:
                session.interview_round = 2
            else:
                score = self._quiz.extract_score(assistant_text)
                if score is None:
                    extra.append("（系统提示：AI 未输出终评【评分：X.X】标记，"
                                 "请追问「最终评分是多少」）")
                else:
                    self._record_teach_back(session, score, extra)
            return extra

        if session.day_phase == DayPhase.REVIEWING.value:
            session.review_question_count += len(
                re.findall(r"^Q\d+[:：]", assistant_text, re.MULTILINE))
            score = self._quiz.extract_score(assistant_text)
            if score is not None and self._state_store.exists():
                state = self._state_store.load()
                day_data = self._state_store.day(state)
                day_data["review_completed"] = True
                day_data["review_score"] = score
                from ..engine.hooks.validate_hook import make_validator
                from ..services.backup_service import BackupService
                BackupService(self._config).atomic_persist(
                    {self._state_store.path: self._state_store.dump(state)},
                    validator=make_validator(self._config))
                try:
                    from ..services.learner_service import LearnerService
                    svc = LearnerService(self._config)
                    svc.ensure_concepts(state)
                    svc.record_review(state["current_day"],
                                      day_data.get("units", []), score)
                except Exception:
                    pass  # 学习者模型写入失败不阻断复盘流程
                session.day_phase = DayPhase.STUDYING.value
                session.pending_qa_capture = True  # M4：触发拷打反喂话术（chat 路由执行）
                extra.append(f"复盘评分已落盘：{score} 分。")

        elif stage == "quiz_r1":
            session.current_stage = "quiz_r2"
            session.quiz_round = 2

        elif stage == "quiz_r2":
            score = self._quiz.extract_score(assistant_text)
            if score is None:
                extra.append("（系统提示：AI 未输出【评分：X.X】标记，请追问「你的评分是多少」）")
            else:
                session.pending_score = score
                if self._quiz.is_pass(score):
                    next_unit = self._next_unit_title(session)
                    session.current_stage = "scored"
                    extra.append(
                        self._templates.get("next_preview")
                        .replace("<单元名>", self._current_unit_title(session))
                        .replace("<下一单元名>", next_unit or "（今日单元已全部完成）")
                        .replace("<2-3 句话>", "见 Study.md 大纲")
                        .replace("<X 分钟>", "40"))
                else:
                    session.current_stage = self._stages.first
                    session.pending_score = None
                    extra.append(
                        self._templates.get("reject_advance")
                        .replace("<单元名>", self._current_unit_title(session))
                        .replace("<具体卡点>", f"终期评分 {score} 未达及格线")
                        .replace("<用户哪里没答上来 / 复述哪里有偏差>",
                                 "见上方点评"))
        else:
            # 回合复习：每 5-6 轮提示一次掌握情况检查
            session.round_count += 1
            lo, hi = self._config.get("round_review_interval", [5, 6])
            if session.round_count >= lo:
                session.round_count = 0
                extra.append("（系统：已到回合复习点，可以说 [下一内容] 触发掌握情况检查，"
                             "或继续当前讲解）")
        return extra

    def _current_unit_title(self, session: SessionContext) -> str:
        try:
            state = self._state_store.load()
            unit = self._state_store.set_unit(state, session.current_unit_id)
            return unit["title"]
        except Exception:
            return session.current_unit_id or ""

    def _interview_title(self, session: SessionContext) -> str:
        """面试知识点标题（LearnerService 查找，失败回退 cid）。"""
        try:
            from ..services.learner_service import LearnerService
            day = int(self._state_store.load().get("current_day", 1))
            for c in LearnerService(self._config).get_model(day)["concepts"]:
                if c["id"] == session.interview_cid:
                    return c.get("title", session.interview_cid)
        except Exception:
            pass
        return session.interview_cid or "当前知识点"

    def _record_teach_back(self, session: SessionContext, score: float,
                           extra: list[str]) -> None:
        """teach_back 证据落盘（M5c 验收硬条）：终评 → pass/fail 证据（幂等）。

        写入失败不阻断面试流程（铁律 15）；随后 phase 还原 STUDYING。
        """
        from datetime import date
        cid = session.interview_cid
        passed = self._quiz.is_pass(score)
        etype = "teach_back_pass" if passed else "teach_back_fail"
        ref = f"interview:{cid}:{date.today().isoformat()}"
        written = False
        idempotent = False
        try:
            from ..services.learner_service import LearnerService
            day = int(self._state_store.load().get("current_day", 1))
            written = LearnerService(self._config).add_evidence(
                cid, etype, ref, day)
            if not written:
                # 区分幂等命中（同日已记录，正常）与真实失败（R5 文案）
                model = LearnerService(self._config).get_model(day)
                idempotent = any(
                    ev.get("source_ref") == ref
                    for c in model["concepts"] if c["id"] == cid
                    for ev in c.get("evidence", []))
        except Exception:
            pass
        if written:
            note = "teach_back 证据已落盘"
        elif idempotent:
            note = "今日已记录过本场面试证据（幂等跳过）"
        else:
            note = "证据落盘失败（不影响流程）"
        extra.append(
            f"🎤 模拟面试结束：终评 {score} 分（{'通过' if passed else '未通过'}），{note}。")
        session.day_phase = DayPhase.STUDYING.value
        session.interview_cid = ""
        session.interview_round = 0
        session.interview_score = None

    def _next_unit_title(self, session: SessionContext) -> str | None:
        state = self._state_store.load()
        for u in self._state_store.day(state)["units"]:
            if u["status"] != "completed" and u["id"] != session.current_unit_id:
                return u["title"]
        return None
