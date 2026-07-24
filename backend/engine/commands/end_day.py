"""[结束今日学习]：6 步收尾（汇总 → StudyMemory → InterviewQA → StudyReview → Study.md → 明日预告）。

Step 5 内含「次日滚动细化」：若 Day N+1 在 Study.md 中还是粗纲，
调用 LLM 生成细化小节（注入昨日学习反馈），与主批次同一原子落盘；
失败保留粗纲并警告，不阻塞结束流程。
"""

from __future__ import annotations

import re

from ...domain.enums import DayPhase
from ...domain.models import SessionContext
from ...services.config_service import PROMPTS_DIR
from ...services.study_plan import (StudyPlanError, check_unit_docs,
                                    parse_day_text)
from .base import CommandHandler, CommandResult, Deps


class EndDayHandler(CommandHandler):
    name = "end_day"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "今日还没 [开始今日学习]，无内容可结束。"
        if session.day_phase == DayPhase.INTERVIEW.value:
            return "模拟面试进行中，请先完成本场面试再结束今日学习。"
        if session.day_phase == DayPhase.PREREQ.value:
            return "先修诊断进行中，请先完成本场诊断再结束今日学习。"
        state = deps.state_store.load()
        day = state["current_day"]
        if not deps.memory.exists(day):
            return "今日还没 [开始今日学习]，无内容可结束。"
        checks = deps.memory.unit_checks(deps.memory.read(day))
        if not any(checks.values()) and args.strip() not in ("确定", "跳过复盘"):
            return "今天还没完成任何单元，确定结束？如确定请回 [结束今日学习] 确定。"
        day_data = deps.state_store.day(state)
        if not day_data.get("review_completed") and args.strip() not in ("跳过复盘", "确定"):
            return ("今日尚未复盘，建议先 [开始今日复盘] 再结束。\n"
                    "要跳过复盘直接结束吗？回 [结束今日学习] 跳过复盘 / 先复盘")
        return None

    # ---- 次日滚动细化 ----

    @staticmethod
    def _memory_excerpt(content: str) -> str:
        """当日 StudyMemory 摘录：卡壳/疑问/AI 拷打评语/明日优先项。"""
        parts = []
        for field in ("卡壳", "疑问"):
            m = re.search(rf"^-\s*{field}[:：]\s*(.+)$", content, re.MULTILINE)
            if m and m.group(1).strip() not in ("", "无"):
                parts.append(f"{field}：{m.group(1).strip()}")
        for header in ("### AI 拷打评语", "### 明日优先项"):
            m = re.search(rf"{re.escape(header)}\n(.*?)(?=\n### |\Z)",
                          content, re.DOTALL)
            if m and m.group(1).strip() and m.group(1).strip() != "- 待生成":
                parts.append(f"{header[4:]}：{m.group(1).strip()}")
        return "\n".join(parts) or "无"

    def _detail_next_day(self, deps: Deps, day: int, study_content: str,
                         memory_content: str) -> tuple[str, str | None]:
        """Day day+1 为粗纲时生成细化小节并拼入。返回 (新内容, 警告或 None)。"""
        ws = deps.config.workspace
        if day + 1 > ws.total_days:
            return study_content, None
        try:
            if deps.study_plan.parse_day(day + 1)["units"]:
                return study_content, None  # 已细化，向后兼容跳过
        except StudyPlanError:
            pass

        m = re.search(rf"^## Day {day + 1} \|.*?(?=^## Day \d+ \||\Z)",
                      study_content, re.MULTILINE | re.DOTALL)
        coarse = (m.group(0).strip() if m else
                  f"## Day {day + 1} | （粗纲缺失，请依学习路径自定主题）")
        neighbor_lines = []
        for n in (day, day + 2):
            nm = re.search(rf"^## Day {n} \|[^\n]*", study_content,
                           re.MULTILINE)
            if nm:
                neighbor_lines.append(nm.group(0))
        proj = deps.config.docx_dir / "Project.md"
        project_md = (proj.read_text(encoding="utf-8")
                      if proj.exists() else "（无 Project.md）")
        prompt = (PROMPTS_DIR / "detail_day_md.md").read_text(encoding="utf-8")
        prompt = (prompt
                  .replace("<title>", ws.title)
                  .replace("<goal>", ws.goal)
                  .replace("<day>", str(day + 1))
                  .replace("<total_days>", str(ws.total_days))
                  .replace("<replica_name>", ws.replica_name)
                  .replace("<coarse_section>", coarse)
                  .replace("<neighbor_context>",
                           "\n".join(neighbor_lines) or "无")
                  .replace("<feedback>", self._memory_excerpt(memory_content))
                  .replace("<project_md>", project_md))
        max_tokens = int(deps.config.get("init_max_tokens", 8192))
        errors = ""
        for _ in range(2):  # 首次 + 带错重试 1 次
            p = prompt if not errors else (
                f"{prompt}\n\n【上次输出未通过程序校验】\n{errors}\n"
                "请修正后重新完整输出（仍禁止任何前言后语）。")
            text = deps.llm.chat([{"role": "user", "content": p}],
                                 max_tokens=max_tokens).strip()
            if text.startswith("```") and text.endswith("```"):
                text = "\n".join(text.splitlines()[1:-1]).strip()
            try:
                parsed = parse_day_text(text, day + 1, ws.replica_name)
                if parsed["units"]:
                    doc_errors = check_unit_docs(parsed["units"],
                                                 ws.project_dir)
                    if not doc_errors:
                        return (deps.study_plan.replace_day_section(
                            study_content, day + 1, text), None)
                    errors = "；".join(doc_errors[:3])
                else:
                    errors = "单元数为 0"
            except StudyPlanError as e:
                errors = str(e)
        return study_content, (
            f"⚠️ Day {day + 1} 细化小节生成失败（{errors}），已保留粗纲；"
            "可重发 [结束今日学习] 触发重试，或手动细化 Study.md。")

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        state = deps.state_store.load()
        day = state["current_day"]
        day_data = deps.state_store.day(state)
        content = deps.memory.read(day)
        messages: list[str] = []

        # ---- Step 1: [同步] 汇总 ----
        counts = deps.memory.sync_counts(content)
        pending_q = content.count("（待解答）")
        # 「已解决」只读计数：notes.json 当日创建的已销账卡壳条目
        # （铁律 16 单一路径语义不变，此处只读不写）
        from ...services.notes_service import NotesService
        resolved_stuck = sum(
            1 for n in NotesService(deps.config).list(status="resolved",
                                                      kind="stuck")
            if n.get("created_day") == day)
        summary = (deps.templates.get("end_step1_sync")
                   .replace("<N> 项", f"{counts.get('已掌握', 0)} 项", 1)
                   .replace("<N> 项（其中已解决 <X> 项）",
                            f"{counts.get('卡壳', 0)} 项（其中已解决 {resolved_stuck} 项）")
                   .replace("<N> 项（已解答 <X> / 待解答 <Y>）",
                            f"{counts.get('疑问', 0)} 项（已解答 {counts.get('疑问', 0) - pending_q} / 待解答 {pending_q}）")
                   .replace("<N> 模块", f"{counts.get('代码完成', 0)} 模块"))
        if pending_q:
            summary = (summary
                       .replace("(如有「待解答」)", "")
                       .replace("<Y>", str(pending_q)))
        else:
            # 无待解答疑问：警告行整行移除（含前导空行），不留未替换占位符
            summary = summary.replace(
                "\n\n(如有「待解答」)⚠️ 仍有 <Y> 个待解答疑问，"
                "建议补充 `[同步] 疑问 XXX` 解答完再结束。", "")
        messages.append(summary)

        # ---- Step 2: 完善 StudyMemory 与 JSON ----
        units = day_data["units"]
        done_n = sum(1 for u in units if u["status"] == "completed")
        for u in units:
            if u["status"] in ("not_started", "in_progress"):
                u["status"] = "postponed"
        day_data["active_day_completed"] = True
        deps.state_store.recompute_percentage(state)
        # 空字段补"无"
        for field in ["已掌握", "卡壳", "疑问", "代码完成"]:
            content = re.sub(rf"^(- {field}：)\s*$", rf"\g<1>无", content,
                             flags=re.MULTILINE)

        # ---- Step 3: 面试话术统计 ----
        qa_path = deps.config.docx_dir / "InterviewQA.md"
        qa_count = 0
        if qa_path.exists():
            qa_count = qa_path.read_text(encoding="utf-8").count(
                f"**产出来源**：Day {day} ")
        if qa_count:
            step3 = (deps.templates.get("end_step3_qa")
                     .replace("1. <问题标题 1>\n2. <问题标题 2>\n...",
                              f"（共 {qa_count} 条，见 InterviewQA.md）")
                     .replace("<N>", str(qa_count)))
            messages.append(step3)
        else:
            messages.append("今日未产生新面试话术，建议明日有意识地输出 30 秒/2 分钟版回答。")

        # ---- Step 4: LLM 生成 StudyReview ----
        module_name = units[0]["title"] if units else "综合"
        review_prompt = [
            {"role": "system", "content":
                "你是技术复盘文档撰写助手。按给定 Markdown 模板生成详细复盘资料。"},
            {"role": "user", "content":
                f"请为 Day {day} 学习生成详细复盘文档。主模块：{module_name}。\n"
                f"单元：{'、'.join(u['title'] for u in units)}。\n"
                f"必须严格按以下模板结构（7 个二级标题齐全），总字数 ≥ "
                f"{deps.config.get('study_review_min_chars', 3000)} 字：\n\n"
                + deps.templates.get("study_review_doc")
                .replace("<复现名>", deps.config.workspace.replica_name)},
        ]
        review_text = deps.llm.chat(review_prompt)
        min_chars = int(deps.config.get("study_review_min_chars", 3000))
        if len(review_text) < min_chars:
            review_prompt.append({"role": "assistant", "content": review_text})
            review_prompt.append({"role": "user", "content":
                f"当前仅 {len(review_text)} 字，不足 {min_chars} 字。请扩充各章节深度后重新输出完整文档。"})
            review_text = deps.llm.chat(review_prompt)
        review_dir = deps.config.docx_dir / "StudyReview"
        review_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r"[\\/:*?\"<>|]", "_", module_name)[:30]
        review_path = review_dir / f"Day_{day:02d}-{safe_name}.md"

        # ---- Step 5: Study.md（含次日滚动细化） ----
        study_content = deps.study_plan.read()
        study_content = deps.study_plan.mark_day_done(study_content, day)
        study_content = deps.study_plan.update_header(
            study_content, day, state["overall_completion_percentage"])
        study_content, detail_warn = self._detail_next_day(
            deps, day, study_content, content)
        if detail_warn:
            messages.append(detail_warn)

        # ---- 统一落盘（备份 → 写 → 校验 → 失败回滚） ----
        deps.backup.atomic_persist(
            {deps.state_store.path: deps.state_store.dump(state),
             deps.memory.path_for(day): content,
             review_path: review_text,
             deps.config.docx_dir / "Study.md": study_content},
            validator=deps.validator())

        # ---- Step 6: 明日预告 ----
        try:
            next_plan = deps.study_plan.parse_day(day + 1)
            next_title = next_plan["goal"] or f"Day {day + 1}"
            next_units = str(len(next_plan["units"]))
            next_code = next_plan["code_goal"] or "见大纲"
            next_paper = next_plan["paper"] or "见大纲"
        except Exception:
            next_title, next_units, next_code, next_paper = f"Day {day + 1}", "?", "见大纲", "见大纲"
        total = deps.config.workspace.total_days
        step6 = (deps.templates.get("end_step6")
                 .replace("<N> 完成", f"{day} 完成")
                 .replace("<X> / 25", f"{state['overall_completion_percentage'] * total // 100} / {total}")
                 .replace("<Y>%", f"{state['overall_completion_percentage']}%")
                 .replace("<完成 X / 计划 Y>", f"完成 {done_n} / 计划 {len(units)}")
                 .replace("<完成 X 个>", f"完成 {counts.get('代码完成', 0)} 个")
                 .replace("<追加 N 条>", f"追加 {qa_count} 条")
                 .replace("<YYYY-MM-DD>-<模块>", f"Day_{day:02d}-{safe_name}")
                 .replace("<字数>", str(len(review_text)))
                 .replace("<标题>", next_title, 1)
                 .replace("<X> 个", f"{next_units} 个")
                 .replace("<模块>", next_code)
                 .replace("<标题>", next_paper, 1)
                 .replace("<N+1>", str(day + 1)))
        import re as _re
        step6 = _re.sub(r"明日优先项（昨日 < 3 分回滚）：\n1\. <项 1>\n2\. <项 2>",
                        "明日优先项（昨日 < 3 分回滚）：\n- 见 StudyMemory 明日优先项", step6)
        messages.append(step6)

        session.day_phase = DayPhase.ENDED.value
        session.current_stage = ""  # 🟡-2：阶段随结束复位（残留阶段指令不再注入）
        deps.session_store.save(session)
        return CommandResult(messages=messages)
