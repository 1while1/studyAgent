"""[开始今日学习]：4 步流程（历史分析 → 仓库校验 → 生成计划 → 开始导学）。

分支：
- 当日 StudyMemory 不存在 → 全新初始化
- 已存在且用户选择「重新开始今日学习」→ 重置勾选但保留 [同步] 记录/评分/评语
- 已存在且用户选择「[恢复学习]」→ 引导走恢复流程（实际由 resume handler 处理）
"""

from __future__ import annotations

import re
from datetime import date

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from ...services.study_plan import StudyPlanError
from .base import CommandHandler, CommandResult, Deps

RESTART_KEYWORDS = ("重新开始今日学习", "重新开始", "重新学习")
RESUME_KEYWORDS = ("[恢复学习]", "恢复学习")


class StartDayHandler(CommandHandler):
    name = "start_day"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "StudyState.json 不存在，请先通过 CLI 助手完成 Day 1 初始化。"
        state = deps.state_store.load()
        day = state["current_day"]
        day_data = state["days"].get(str(day), {})
        if day_data.get("active_day_completed"):
            return None  # 前一天已结束，run() 会自动递进天数
        if any(k in args for k in RESTART_KEYWORDS + RESUME_KEYWORDS):
            return None  # 用户已做出双选项选择
        if deps.memory.exists(day):
            checks = deps.memory.unit_checks(deps.memory.read(day))
            done = sum(1 for v in checks.values() if v)
            todo = len(checks) - done
            return deps.templates.render(
                "fail_fast_exists", NN=f"{day:02d}", X=str(done), Y=str(todo))
        return None

    # ---- Step 渲染 ----

    @staticmethod
    def _render_step1(deps: Deps, state: dict, day: int,
                      due: list[dict] | None = None) -> str:
        prev = state["days"].get(str(day - 1))
        prev_done = (sum(1 for u in prev.get("units", []) if u["status"] == "completed")
                     if prev else 0)
        rollback = []
        if prev:
            pass_line = deps.config.get("mastery_pass_score", 3.0)
            rollback = [f"单元{u['id']}：{u['title']}"
                        for u in prev.get("units", [])
                        if u.get("status") == "completed" and 0 < u.get("rating", 0) < pass_line]
        rollback_text = "、".join(rollback) if rollback else "无"
        due_lines = [f"- {i['type']}·Day {i['from_day']}：{i['text']}"
                     for i in (due or [])]
        due_text = "\n".join(due_lines) if due_lines else "无"
        text = deps.templates.get("step1_history")
        text = (text
                .replace("<N>", str(day))
                .replace("<日期>", prev.get("date", "无") if prev else "无")
                .replace("<X>", str(prev_done))
                .replace("<列表>", "无", 1)            # 昨日卡壳（v1 未跨日追踪）
                .replace("<列表>", rollback_text, 1)   # 昨日 < 3 分回滚项
                .replace("<列表>", due_text, 1))       # 将优先安排（含间隔复习项）
        return text

    @staticmethod
    def _render_step2(deps: Deps) -> str:
        repo = deps.config.workspace.project_dir
        scan = "✅ 一致" if repo.exists() else f"❌ 未找到目标项目目录 {repo}"
        text = deps.templates.get("step2_repo_check")
        text = text.replace("<列表>", "见 Study.md 当日大纲", 1)
        text = text.replace(
            "扫描结果：[✅ 一致 / ⚠️ 已修正 X 处 / ❌ 严重不符]",
            f"扫描结果：{scan}")
        text = text.replace("（如有差异）修正内容：<列表>\n", "")
        return text

    @staticmethod
    def _render_step3(deps: Deps, plan: dict, day: int, today: str) -> str:
        unit_lines = []
        for i, u in enumerate(plan["units"], 1):
            unit_lines.append(
                f"{i}. [ ] 单元{u['id']}：{u['title']}（预计 {u['duration']}）\n"
                f"   - 文档：{u['doc'] or '见 DocIndex'}\n"
                f"   - 核心知识点：见大纲")
        import datetime as _dt
        weekday = "一二三四五六日"[_dt.date.fromisoformat(today).weekday()]
        text = deps.templates.get("step3_plan")
        text = (text
                .replace("<N>", str(day))
                .replace("<YYYY-MM-DD>", today)
                .replace("星期X", f"星期{weekday}")
                .replace("<1 句话>", plan["goal"] or "见大纲")
                .replace("<模块>", plan["code_goal"] or "见大纲")
                .replace("<论文名>", plan["paper"] or "无")
                .replace("Section <X>", plan["paper_sections"] or "核心章节")
                .replace("<话题>", plan["qa_goal"] or "见大纲")
                .replace("<5-6h>", "5-6h"))
        text = re.sub(
            r"1\. \[ \] 单元A：.*?3\. \[ \] 单元C：.*?\n   \.\.\.",
            "\n".join(unit_lines), text, flags=re.DOTALL)
        return text

    @staticmethod
    def _render_paper(deps: Deps, plan: dict) -> str | None:
        if not plan["paper"]:
            return None
        text = deps.templates.get("paper_block")
        text = text.replace("<论文/文章名>", plan["paper"], 1)
        # 仅 1 篇时移除第 2 篇占位条目
        text = re.sub(
            r"2\. \*\*《<论文/文章名>》\*\*（<作者>, <年份>）\n"
            r"   - 重点章节：Section <X>（<章节主题>）\n"
            r"   - 面试价值：<1-2 句话>\n",
            "", text)
        text = (text
                .replace("<作者>, <年份>", "见推荐")
                .replace("<X>（<章节主题>）", "核心章节")
                .replace("<1-2 句话，说明读完能答什么面试题>", "见导学讲解"))
        return text

    @staticmethod
    def _render_unit_open(deps: Deps, unit: dict, plan: dict) -> str:
        return (deps.templates.get("unit_open")
                .replace("<标题>", unit["title"])
                .replace("<1 句话>", plan.get("goal") or "掌握本单元核心概念")
                .replace("<X>", unit.get("duration", "40min").replace("min", ""), 1)
                .replace("<1-2 个>", "面试高频考点（导学中展开）")
                .replace("<路径>", unit.get("doc") or "见 DocIndex")
                .replace("<引用>", plan.get("paper") or "无")
                .replace("<开始讲解，1 段，≤ 300 字>", "（第一段由 AI 在下方输出）"))

    # ---- 主流程 ----

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        state = deps.state_store.load()
        # 天数递进：前一天已结束 → current_day +1（AGENTS.md 执行约束 2）
        # 不在此单独落盘：递进后的 JSON 必须与 StudyMemory/Study.md 在末尾
        # 统一原子落盘——否则中间态（JSON=Day N+1，StudyMemory/Study.md 仍是
        # Day N）必被 validate 拒绝并回滚，跨日永远失败（已踩坑）
        prev_day_data = state["days"].get(str(state["current_day"]), {})
        incremented = False
        if prev_day_data.get("active_day_completed"):
            state["current_day"] += 1
            deps.state_store.ensure_day(state, state["current_day"])
            incremented = True
        day = state["current_day"]

        # 间隔复习项采集（失败不阻塞开始学习）
        try:
            from ...services.review_scheduler import collect_due
            due = collect_due(deps.config, deps.state_store, deps.memory, day)
        except Exception:
            due = []

        # 双选项分支：[恢复学习] → 引导走恢复流程（不解析当日大纲，保持原行为）
        if any(k in args for k in RESUME_KEYWORDS):
            return CommandResult(messages=["请直接发送 [恢复学习]，我会从中断单元继续。"])

        restart = any(k in args for k in RESTART_KEYWORDS)

        plan = deps.study_plan.parse_day(day)  # 可能抛 StudyPlanError → API 层转 STOP
        if not plan["units"]:
            raise StudyPlanError(f"Day {day} 大纲中未解析到导学单元")

        # 感召通道（M7 §4/§13：复习按相关性而非日历）：今日首单元的上游
        # 未达标链（先修闭包，拓扑序根基先补，含零证据节点；失败静默不阻塞）
        relevance: list[dict] = []
        try:
            from ...domain.learner import concept_id
            first_cid = concept_id(day, plan["units"][0]["id"])
            # F1 修复：读图前先 ensure（新日当日单元未注册时闭包为空 →
            # 感召静默缺失；sync/next_content 同款统一入口）
            svc = CommandHandler.learner_with_concepts(deps)
            for x in svc.unmastered_upstream([first_cid], day):
                m = re.match(r"Day(\d+)-", x["cid"])
                relevance.append({
                    "type": "上游感召",
                    "from_day": int(m.group(1)) if m else day,
                    "text": f"{x['cid']}：{x['title']}"
                            f"（掌握度 {x['mastery']:.2f}"
                            f"{'' if x['has_evidence'] else '，未学'}）"})
        except Exception:
            relevance = []
        # 合并：感召优先（相关性）+ 日历补充，总量封顶（§13 验收形态）
        max_items = int(deps.config.get("review_max_items", 6))
        merged = (relevance + due)[:max_items]

        messages: list[str] = [
            self._render_step1(deps, state, day, merged),
            self._render_step2(deps),
        ]

        today = date.today().isoformat()
        day_data = deps.state_store.ensure_day(state, day)
        day_data["date"] = today
        if not day_data["units"] or restart:
            day_data["units"] = [
                {"id": u["id"], "title": u["title"], "status": "not_started",
                 "rating": 0}
                for u in plan["units"]
            ]
        messages.append(self._render_step3(deps, plan, day, today))
        messages.append(deps.templates.get("step4_guide"))
        paper = self._render_paper(deps, plan)
        if paper:
            messages.append(paper)

        # 落盘：JSON + StudyMemory（重新开始 = 重置勾选保留记录；全新 = 渲染新文件）
        if deps.memory.exists(day) and restart:
            mem_content = deps.memory.reset_for_restart(deps.memory.read(day))
        else:
            mem_content = deps.memory.render_new(today, plan["units"],
                                                 paper=plan["paper"] or None)
        deps.backup.atomic_persist(
            {deps.state_store.path: deps.state_store.dump(state),
             deps.memory.path_for(day): mem_content,
             **({deps.config.docx_dir / "Study.md":
                 deps.study_plan.update_header(
                     deps.study_plan.read(), day,
                     state["overall_completion_percentage"])}
                if incremented else {})},
            validator=deps.validator())

        first = plan["units"][0]
        session.day_phase = DayPhase.STUDYING.value
        session.current_unit_id = first["id"]
        session.current_stage = deps.stages.first
        session.round_count = 0
        session.quiz_round = 0
        # 新的一天/重新开始 = 全新对话上下文，防止历史中的陈旧讲解让模型误以为课程已在进行
        session.chat_history = []
        session.archive_summary = ""  # M5b：归档层同步重置（防 archive_upto 越界）
        session.archive_upto = 0
        session.compress_cooldown = 0
        # R3：新开始同步清面试残留字段；M7：同步清诊断残留字段
        session.interview_cid = ""
        session.interview_round = 0
        session.interview_score = None
        session.prereq_targets = []
        session.prereq_retry = 0
        deps.session_store.save(session)

        messages.append(self._render_unit_open(deps, first, plan))
        review_prefix = ""
        rel_items = [i for i in merged if i["type"] == "上游感召"]
        cal_items = [i for i in merged if i["type"] != "上游感召"]

        def _lines(items):
            return "\n".join(f"- {i['type']}·Day {i['from_day']}：{i['text']}"
                             for i in items)

        if rel_items:
            # M7 感召形态：相关性优先分组（先修链未达标 → 日历到期）
            blocks = ["【上游感召】今日单元的先修链未达标节点"
                      f"（按拓扑序优先补）：\n{_lines(rel_items)}"]
            if cal_items:
                blocks.append(f"【间隔复习】历史薄弱项（日历到期）：\n{_lines(cal_items)}")
            review_prefix = (
                "正式开讲前，用 ≤5 分钟快速回顾以下项目"
                "（逐条向用户提问确认是否还记得，答错用一句话纠正，不展开重讲）：\n"
                + "\n\n".join(blocks) +
                "\n回顾完毕后无缝进入单元开场讲解。\n")
        elif cal_items:
            review_prefix = (  # 无感召时与 M7 前逐字节一致
                "【间隔复习】正式开讲前，用 ≤5 分钟快速回顾以下历史薄弱项"
                "（逐条向用户提问确认是否还记得，答错用一句话纠正，不展开重讲）：\n"
                f"{_lines(cal_items)}\n回顾完毕后无缝进入单元开场讲解。\n")
        return CommandResult(
            messages=messages,
            llm_instruction=(
                review_prefix +
                f"请输出单元「{first['title']}」的开场「第一段」讲解（≤300字），"
                f"然后按步骤一：文档带读，提炼本单元核心概念开始讲解。"
                f"直接输出教学内容，不要复述任何流程模板或指令文字。"),
            sop_card="")  # 纯教学内容生成：不携带 SOP 卡，防止模型复读卡片模板
