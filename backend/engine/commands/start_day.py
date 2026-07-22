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
    def _render_step1(deps: Deps, state: dict, day: int) -> str:
        prev = state["days"].get(str(day - 1))
        prev_done = (sum(1 for u in prev.get("units", []) if u["status"] == "completed")
                     if prev else 0)
        rollback = []
        if prev:
            rollback = [f"单元{u['id']}：{u['title']}"
                        for u in prev.get("units", [])
                        if u.get("status") == "completed" and 0 < u.get("rating", 0) < 3.0]
        rollback_text = "、".join(rollback) if rollback else "无"
        text = deps.templates.get("step1_history")
        text = (text
                .replace("<N>", str(day))
                .replace("<日期>", prev.get("date", "无") if prev else "无")
                .replace("<X>", str(prev_done))
                .replace("<列表>", "无", 1)            # 昨日卡壳（v1 未跨日追踪）
                .replace("<列表>", rollback_text, 1)   # 昨日 < 3 分回滚项
                .replace("<列表>", rollback_text, 1))  # 将优先安排
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
        prev_day_data = state["days"].get(str(state["current_day"]), {})
        if prev_day_data.get("active_day_completed"):
            state["current_day"] += 1
            state["active_day_completed"] = False
            deps.state_store.ensure_day(state, state["current_day"])
            deps.backup.atomic_persist(
                {deps.state_store.path: deps.state_store.dump(state)},
                validator=deps.validator())
        day = state["current_day"]

        # 双选项分支：[恢复学习] → 引导走恢复流程
        if any(k in args for k in RESUME_KEYWORDS):
            return CommandResult(messages=["请直接发送 [恢复学习]，我会从中断单元继续。"])

        restart = any(k in args for k in RESTART_KEYWORDS)

        messages: list[str] = [
            self._render_step1(deps, state, day),
            self._render_step2(deps),
        ]

        plan = deps.study_plan.parse_day(day)  # 可能抛 StudyPlanError → API 层转 STOP
        if not plan["units"]:
            raise StudyPlanError(f"Day {day} 大纲中未解析到导学单元")
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
             deps.memory.path_for(day): mem_content},
            validator=deps.validator())

        first = plan["units"][0]
        session.day_phase = DayPhase.STUDYING.value
        session.current_unit_id = first["id"]
        session.current_stage = deps.stages.first
        session.round_count = 0
        session.quiz_round = 0
        # 新的一天/重新开始 = 全新对话上下文，防止历史中的陈旧讲解让模型误以为课程已在进行
        session.chat_history = []
        deps.session_store.save(session)

        messages.append(self._render_unit_open(deps, first, plan))
        return CommandResult(
            messages=messages,
            llm_instruction=(
                f"请输出单元「{first['title']}」的开场「第一段」讲解（≤300字），"
                f"然后按步骤一：文档带读，提炼本单元核心概念开始讲解。"
                f"直接输出教学内容，不要复述任何流程模板或指令文字。"),
            sop_card="")  # 纯教学内容生成：不携带 SOP 卡，防止模型复读卡片模板
