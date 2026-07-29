"""学习者模型 + 笔记 + 话术 + 资料库路由：/api/learner/* /api/notes/* /api/qa/* /api/materials/*。"""

from __future__ import annotations

from fastapi import APIRouter

from ..services.learner_service import LearnerService
from ..services.notes_service import NotesService
from ..services.qa_service import QaService
from ..services.materials_service import MaterialsService

learner_router = APIRouter(tags=["学习者模型", "笔记", "话术", "资料库"])


def _deps():
    from . import routes
    return routes._deps


# ---------- 学习者模型（M3） ----------

@learner_router.get("/api/learner/model")
def learner_model():
    deps = _deps()
    if deps.state_store.exists():
        state = deps.state_store.load()
    else:
        state = {"days": {}, "current_day": 1}
    try:
        from ..engine.commands.base import CommandHandler
        CommandHandler.learner_with_concepts(deps)
    except Exception:
        pass
    svc = LearnerService(deps.config)
    model = svc.get_model(state.get("current_day", 1))
    model["has_ratings_source"] = any(
        u.get("rating") for d in state.get("days", {}).values()
        for u in d.get("units", []))
    model["has_draft"] = svc.draft_path.exists()
    try:
        model["remediation_order"] = svc.remediation_order(
            state.get("current_day", 1))
    except Exception:
        model["remediation_order"] = []
    return model


@learner_router.post("/api/learner/migrate/preview")
def learner_migrate_preview():
    deps = _deps()
    if not deps.state_store.exists():
        return {"ok": False, "error": "StudyState.json 不存在"}
    state = deps.state_store.load()
    memory_by_day = {}
    for day_key in state.get("days", {}):
        d = int(day_key)
        if deps.memory.exists(d):
            memory_by_day[d] = deps.memory.read(d)
    summary = LearnerService(deps.config).migrate_preview(state, memory_by_day)
    return {"ok": True, **summary}


@learner_router.post("/api/learner/migrate/apply")
def learner_migrate_apply():
    return LearnerService(_deps().config).migrate_apply()


@learner_router.get("/api/learner/metrics/{concept_id}")
def learner_metrics(concept_id: str):
    """获取指定 concept 的学习效果度量（BKT + 三指标 + FSRS）。"""
    deps = _deps()
    svc = LearnerService(deps.config)
    bkt = svc.compute_bkt_mastery(concept_id)
    # 从 concept_id 解析天数或取当前天
    import re as _re
    m = _re.match(r"Day(\d+)-", concept_id)
    current_day = int(m.group(1)) if m else 1
    try:
        current_day = max(current_day,
                          int(deps.state_store.load().get("current_day", 1)))
    except Exception:
        pass
    metrics = svc.compute_concept_metrics(concept_id, current_day)
    fsrs = svc.compute_fsrs_interval(concept_id)
    return {
        "concept_id": concept_id,
        "bkt_mastery": bkt,
        "metrics": {
            "indicator_a": metrics.indicator_a,
            "indicator_b": metrics.indicator_b,
            "indicator_c": metrics.indicator_c,
            "mastery_score": metrics.mastery_score,
        },
        "fsrs": fsrs,
    }


# ---------- 笔记（M4 条目层） ----------

def _notes() -> NotesService:
    return NotesService(_deps().config)


def _current_day() -> int | None:
    try:
        return int(_deps().state_store.load().get("current_day", 0)) or None
    except Exception:
        return None


@learner_router.get("/api/notes")
def notes_list(status: str = "", kind: str = ""):
    svc = _notes()
    return {"ok": True,
            "notes": svc.list(status=status or None, kind=kind or None),
            "counts": svc.counts()}


@learner_router.post("/api/notes/add")
def notes_add(body: dict):
    deps = _deps()
    body = body or {}
    try:
        note = _notes().add(
            body.get("kind", "insight"), body.get("text", ""),
            concept_id=body.get("concept_id", "") or "",
            day=_current_day(), validator=deps.validator())
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if note is None:
        return {"ok": False, "error": "内容为空"}
    return {"ok": True, "note": note}


@learner_router.post("/api/notes/update")
def notes_update(body: dict):
    deps = _deps()
    body = body or {}
    try:
        note = _notes().update(body.get("id", ""), text=body.get("text"),
                               concept_id=body.get("concept_id"),
                               validator=deps.validator())
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    if note is None:
        return {"ok": False, "error": "笔记不存在"}
    return {"ok": True, "note": note}


@learner_router.post("/api/notes/resolve")
def notes_resolve(body: dict):
    """销账（M4 单一代码路径）：notes resolved + note_distilled 证据（幂等）。"""
    deps = _deps()
    from ..engine.note_actions import resolve_note
    try:
        return resolve_note(deps.config, deps.state_store,
                            (body or {}).get("id", ""),
                            validator=deps.validator())
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@learner_router.post("/api/notes/merge")
def notes_merge(body: dict):
    deps = _deps()
    body = body or {}
    keep = _notes().merge(body.get("keep", ""), body.get("others") or [],
                          validator=deps.validator())
    if keep is None:
        return {"ok": False, "error": "保留条目不存在"}
    return {"ok": True, "note": keep}


@learner_router.post("/api/notes/delete")
def notes_delete(body: dict):
    deps = _deps()
    try:
        ok = _notes().delete((body or {}).get("id", ""),
                             validator=deps.validator())
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": ok}


@learner_router.post("/api/notes/distill")
def notes_distill(body: dict):
    """日志蒸馏：StudyMemory 各天 [同步] 卡壳/疑问行 → 条目层（去重幂等）。"""
    deps = _deps()
    body = body or {}
    try:
        if body.get("day"):
            days = [int(body["day"])]
        elif deps.state_store.exists():
            days = [int(k) for k in deps.state_store.load().get("days", {})]
        else:
            days = []
    except Exception as e:
        return {"ok": False, "error": f"天数解析失败: {e}"}
    svc = _notes()
    added = 0
    for d in days:
        if deps.memory.exists(d):
            try:
                added += svc.distill_from_text(d, deps.memory.read(d),
                                               validator=deps.validator())
            except Exception:
                pass
    return {"ok": True, "added": added}


# ---------- 面试话术（M4 话术层） ----------

def _qa() -> QaService:
    return QaService(_deps().config)


@learner_router.get("/api/qa/entries")
def qa_entries():
    try:
        return {"ok": True, "entries": _qa().entries()}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "entries": []}


@learner_router.post("/api/qa/update")
def qa_update(body: dict):
    deps = _deps()
    body = body or {}
    fields = {k: body.get(k) for k in
              ("title", "tags", "code_ref", "brief", "detail", "followups")}
    try:
        entry = _qa().update_entry(body.get("id", ""),
                                   validator=deps.validator(), **fields)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    if entry is None:
        return {"ok": False, "error": "话术条目不存在"}
    return {"ok": True, "entry": entry}


@learner_router.post("/api/qa/delete")
def qa_delete(body: dict):
    deps = _deps()
    try:
        ok = _qa().delete_entry((body or {}).get("id", ""),
                                validator=deps.validator())
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": ok}


# ---------- 学习资料库 ----------

def _materials() -> MaterialsService:
    return MaterialsService(_deps().config)


@learner_router.get("/api/materials")
def materials_list():
    ms = _materials()
    ms.ensure_scanned()
    root = ms.root()
    return {"ok": True, "materials": ms.list(),
            "configured": root is not None,
            "root": str(root) if root else ""}


@learner_router.post("/api/materials/rescan")
def materials_rescan():
    ms = _materials()
    try:
        stats = ms.scan()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "stats": stats, "materials": ms.list()}


@learner_router.post("/api/materials/register")
def materials_register(body: dict):
    source = (body or {}).get("source", "")
    try:
        return _materials().register(source)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@learner_router.get("/api/materials/preview")
def materials_preview(id: str, section: str = "", line: int | None = None):
    """资料预览：章节目录 + 开头节选（弹窗阅读用）。"""
    ms = _materials()
    entry = ms.get(id)
    if not entry:
        return {"ok": False, "error": f"未注册的资料: {id}"}
    if entry["type"] == "video_link":
        return {"ok": True, "title": entry["title"],
                "content": f"视频链接：{entry['path']}\n\n（M1 仅登记，不提供内容预览）"}
    if section or line is not None:
        res = ms.read_section(id, section, line=line)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error", "读取失败")}
        return {"ok": True, "title": f"{entry['title']} · {res['section']}",
                "content": res["text"]}
    outline = ms.outline(entry)
    head = ms.read_from_start(id, 4000)
    content = f"**章节目录**\n\n{outline}\n\n---\n\n**开头节选**\n\n"
    content += head["text"] if head.get("ok") else "（无法读取内容）"
    return {"ok": True, "title": entry["title"], "content": content}
