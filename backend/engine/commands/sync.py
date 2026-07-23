"""[同步] XXX：5 种子类型落盘（已掌握/卡壳/疑问/面试话术/代码完成）。"""

from __future__ import annotations

import re

from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps

SUBTYPES = {
    "已掌握": "mastered",
    "卡壳": "stuck",
    "疑问": "questions",
    "面试话术": None,       # 写入 InterviewQA.md
    "代码完成": "code_completed",
}


class SyncHandler(CommandHandler):
    name = "sync"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        m = re.match(r"^\s*(已掌握|卡壳|疑问|面试话术|代码完成)\s+(.+)$", args)
        if not m:
            return "未识别子类型或内容为空，可选：已掌握/卡壳/疑问/面试话术/代码完成。\n用法：[同步] 已掌握 XXX"
        state = deps.state_store.load()
        if not deps.memory.exists(state["current_day"]):
            return "当日 StudyMemory 不存在，请先 [开始今日学习]。"
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        m = re.match(r"^\s*(已掌握|卡壳|疑问|面试话术|代码完成)\s+(.+)$", args)
        subtype, content_text = m.group(1), m.group(2).strip()
        state = deps.state_store.load()
        day = state["current_day"]
        messages: list[str] = []
        llm_instruction = None

        if subtype == "面试话术":
            from ...services.qa_service import QaService
            entry = (deps.templates.get("interview_qa_entry")
                     .replace("<问题标题>", content_text)
                     .replace("<模块>", "待补").replace("<技术点>", "待补")
                     .replace("<文件路径>:<行号>", "待补")
                     .replace("<N>", str(day)).replace("<场景>", "[同步] 面试话术"))
            # M4：话术层收编——落盘走 QaService（剥离骨架占位行），
            # 条目内容可在话术页编辑补全，或由复盘拷打反喂自动产出
            QaService(deps.config).add_entry(entry, validator=deps.validator())
            messages.append(f"已追加面试话术到 InterviewQA.md：\n- 标题：{content_text}")
            llm_instruction = (
                f"请围绕「{content_text}」补全 InterviewQA 条目内容：30秒精简版、2分钟展开版、"
                f"至少 3 个追问预案（Q/A 格式）。生成后我会更新到文件。")
        else:
            # 落盘：StudyMemory + JSON sync_records
            deps.state_store.add_sync_record(
                state, SUBTYPES[subtype], content_text)
            mem = deps.memory.read(day)
            suffix = "（待解答）" if subtype == "疑问" else ""
            mem = deps.memory.append_sync(mem, subtype, content_text + suffix)
            deps.backup.atomic_persist(
                {deps.state_store.path: deps.state_store.dump(state),
                 deps.memory.path_for(day): mem},
                validator=deps.validator())

            # 条目层（M4）：已掌握/卡壳/疑问同步进 notes.json
            # source_ref 带内容哈希——同文重复 [同步] 不产生重复条目
            try:
                import hashlib
                from ...domain.learner import concept_id
                from ...services.notes_service import NotesService
                kind = {"已掌握": "mastered", "卡壳": "stuck",
                        "疑问": "question"}.get(subtype)
                if kind:
                    unit = session.current_unit_id or ""
                    slug = hashlib.sha1(
                        content_text.encode("utf-8")).hexdigest()[:6]
                    NotesService(deps.config).add(
                        kind, content_text,
                        concept_id=concept_id(day, unit) if unit else "",
                        source_ref=f"Day{day}-{unit}:sync:{kind}:{slug}",
                        needs_review=not unit, day=day,
                        validator=deps.validator())
            except Exception:
                pass  # 笔记层写入失败不阻断 [同步]

            if subtype == "已掌握":
                try:
                    self.learner_with_concepts(deps).record_sync(
                        day, session.current_unit_id, "sync_mastered")
                except Exception:
                    pass
                messages.append(deps.templates.render("sync_mastered", XXX=content_text))
            elif subtype == "卡壳":
                try:
                    self.learner_with_concepts(deps).record_sync(
                        day, session.current_unit_id, "sync_stuck")
                except Exception:
                    pass
                messages.append(f"已记录卡壳：「{content_text}」，复盘时会重点拷问。")
                llm_instruction = f"请用画图/类比/简化的方式重新讲解：{content_text}"
            elif subtype == "疑问":
                llm_instruction = f"请立即解答用户疑问：{content_text}"
                messages.append(f"你的疑问：{content_text}\n（解答后我会标记为「已解答」）")
            elif subtype == "代码完成":
                messages.append(deps.templates.render("sync_code_done", XXX=content_text))

        # 综合确认
        counts = deps.memory.sync_counts(deps.memory.read(day))
        messages.append(
            deps.templates.get("sync_summary")
            .replace("<位置>", "StudyMemory + StudyState.json")
            .replace("<X>", str(counts.get("已掌握", 0)))
            .replace("<Y>", str(counts.get("卡壳", 0)))
            .replace("<Z>", str(counts.get("疑问", 0))))
        return CommandResult(messages=messages, llm_instruction=llm_instruction,
                             sop_card="SOP_同步.md")
