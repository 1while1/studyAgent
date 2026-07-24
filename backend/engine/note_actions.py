"""笔记整理动作（M4）：跨服务编排（services 互不引用，在 engine 层组合）。

resolve_note 是「卡壳销账」的单一代码路径：笔记页手动"标记解决"与未来
AI resolve_note 工具都走这里——条目置 resolved + note_distilled 证据沉淀
（source_ref = note:{id} 幂等，重复销账不产生重复证据）。
question 类条目销账时同步摘除当日 StudyMemory 疑问行的「（待解答）」后缀。
"""

from __future__ import annotations

import re

from ..services.config_service import ConfigService
from ..services.state_store import StateStore

# StudyMemory [同步] 疑问条目的固定后缀（sync handler 追加时同款字面量）
_PENDING_SUFFIX = "（待解答）"


def _clear_pending_suffix(config: ConfigService, note: dict, day: int,
                          validator=None) -> None:
    """销账 question 条目后，摘掉 StudyMemory 疑问行中对应项的「（待解答）」。

    行内条目按 、/，/, 切分（分隔符保界防子串误摘），仅摘除去后缀后与
    条目文本相等的那一项；规则 14 落盘。任何异常静默——增强不是闸门，
    不阻断销账主流程。
    """
    try:
        if (note.get("kind") or "") != "question":
            return
        text = (note.get("text") or "").strip()
        mem_day = note.get("created_day") or day
        if not text or not mem_day:
            return
        from ..services.backup_service import BackupService
        from ..services.memory_store import MemoryStore
        memory = MemoryStore(config)
        if not memory.exists(mem_day):
            return
        out, changed, in_sync = [], False, False
        for line in memory.read(mem_day).splitlines():
            if line.startswith("### [同步] 记录"):
                in_sync = True
            elif line.startswith("### "):
                in_sync = False
            m = (re.match(r"^(-\s*疑问[:：])(.*)$", line)
                 if in_sync and not changed else None)
            if m and _PENDING_SUFFIX in m.group(2):
                body, n = re.subn(
                    rf"(^|[、，,]){re.escape(text)}{re.escape(_PENDING_SUFFIX)}"
                    rf"(?=$|[、，,])",
                    lambda mm: mm.group(1) + text, m.group(2), count=1)
                if n:
                    line, changed = m.group(1) + body, True
            out.append(line)
        if changed:
            BackupService(config).atomic_persist(
                {memory.path_for(mem_day): "\n".join(out)},
                validator=validator)
    except Exception:
        pass  # 后缀摘除失败不阻断销账


def resolve_note(config: ConfigService, state_store: StateStore, nid: str,
                 validator=None) -> dict:
    """销账：NotesService.resolve + （挂接了 concept 且非合并残骸时）写证据。

    返回 {"ok", "note"?, "evidence": 是否真正写入证据, "error"?}。
    """
    from ..services.learner_service import LearnerService
    from ..services.notes_service import NotesService

    try:
        day = int(state_store.load().get("current_day", 0))
    except Exception:
        day = 0
    note = NotesService(config).resolve(nid, day=day or None,
                                        validator=validator)
    if note is None:
        return {"ok": False, "error": "笔记不存在"}
    _clear_pending_suffix(config, note, day, validator)
    evidence = False
    cid = (note.get("concept_id") or "").strip()
    if cid and not note.get("merged_into"):
        try:
            evidence = LearnerService(config).add_evidence(
                cid, "note_distilled", f"note:{nid}", day)
        except Exception:
            pass  # 学习者模型写入失败不阻断销账（铁律 15）
    return {"ok": True, "note": note, "evidence": evidence}
