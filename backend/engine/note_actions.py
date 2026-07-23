"""笔记整理动作（M4）：跨服务编排（services 互不引用，在 engine 层组合）。

resolve_note 是「卡壳销账」的单一代码路径：笔记页手动"标记解决"与未来
AI resolve_note 工具都走这里——条目置 resolved + note_distilled 证据沉淀
（source_ref = note:{id} 幂等，重复销账不产生重复证据）。
"""

from __future__ import annotations

from ..services.config_service import ConfigService
from ..services.state_store import StateStore


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
    evidence = False
    cid = (note.get("concept_id") or "").strip()
    if cid and not note.get("merged_into"):
        try:
            evidence = LearnerService(config).add_evidence(
                cid, "note_distilled", f"note:{nid}", day)
        except Exception:
            pass  # 学习者模型写入失败不阻断销账（铁律 15）
    return {"ok": True, "note": note, "evidence": evidence}
