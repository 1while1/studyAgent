"""笔记条目层服务（M4）：notes.json 的 CRUD、合并与日志蒸馏。

数据单源（工作区 docx_dir，规则 14 落盘）：
- `notes.json`（schema_version=1）：{notes: [{id, kind, text, status,
  concept_id, needs_review, source_ref, created_day?, resolved_day?, merged_into?}]}
  kind ∈ {stuck, question, mastered, insight}；status ∈ {open, resolved}
  可选字段缺失被容忍（M3 迁移产物只有核心字段）。

销账（resolve）只改条目状态；note_distilled 证据沉淀由
engine/note_actions.py 编排（services 互不引用），
source_ref = note:{id} 幂等保证重复销账不产生重复证据。
"""

from __future__ import annotations

import hashlib
import re
import uuid

from .backup_service import BackupService
from .config_service import ConfigService
from .repository import JsonRepository

SCHEMA_VERSION = 1
KINDS = ("stuck", "question", "mastered", "insight")
STATUSES = ("open", "resolved")
# StudyMemory [同步] 记录中疑问条目的固定后缀（sync handler 追加）
_PENDING_SUFFIX = "（待解答）"


def _slug(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]


def new_id() -> str:
    return f"n-{uuid.uuid4().hex[:8]}"


class NotesService:
    def __init__(self, config: ConfigService):
        self._config = config
        docx_dir = config.docx_dir
        self._repo = JsonRepository(docx_dir)
        self._notes_file = "notes"
        self.path = docx_dir / "notes.json"  # backward compat

    # ---- 读写 ----

    def _load(self) -> dict:
        default = {"schema_version": SCHEMA_VERSION, "notes": []}
        # Pre-check: detect corrupt / malformed file and back up before
        # the repository silently returns None.
        if self.path.exists():
            try:
                raw = self.path.read_text(encoding="utf-8")
            except Exception as e:
                self._backup_and_log(e)
                return default
            try:
                import json
                parsed = json.loads(raw)
                if not (isinstance(parsed, dict) and isinstance(parsed.get("notes"), list)):
                    self._backup_and_log(ValueError("structure mismatch"))
                    return default
            except Exception as e:
                self._backup_and_log(e)
                return default
        return self._repo.load(self._notes_file) or default

    def _backup_and_log(self, exc) -> None:
        try:
            import shutil
            bak = self.path.with_suffix(self.path.suffix + ".corrupt.bak")
            shutil.copy2(self.path, bak)
        except Exception:
            pass
        from .observer import get_observer
        get_observer(self._config).log_tool(
            "silent_notes_load", False,
            f"notes.json: {repr(exc)[:200]}")

    def _save(self, data: dict, validator=None) -> None:
        data["schema_version"] = SCHEMA_VERSION
        backup = BackupService(self._config)
        backup.backup(self.path)
        self._repo.save(self._notes_file, data)
        if validator is not None:
            ok, output = validator()
            if not ok:
                backup.restore(self.path)
                from .backup_service import PersistError
                raise PersistError(output)

    # ---- 查询 ----

    def list(self, status: str | None = None,
             kind: str | None = None) -> list[dict]:
        notes = list(self._load()["notes"])
        if status:
            notes = [n for n in notes if n.get("status") == status]
        if kind:
            notes = [n for n in notes if n.get("kind") == kind]
        return notes

    def get(self, nid: str) -> dict | None:
        for n in self._load()["notes"]:
            if n.get("id") == nid:
                return n
        return None

    def counts(self) -> dict:
        notes = self._load()["notes"]
        return {
            "total": len(notes),
            "open": sum(1 for n in notes if n.get("status") != "resolved"),
            "resolved": sum(1 for n in notes if n.get("status") == "resolved"),
            "needs_review": sum(1 for n in notes if n.get("needs_review")),
        }

    # ---- 写入 ----

    def add(self, kind: str, text: str, concept_id: str = "",
            source_ref: str = "", needs_review: bool = False,
            day: int | None = None, validator=None) -> dict | None:
        """新增条目。source_ref 非空时按之幂等（重复写返回 None）。"""
        if kind not in KINDS:
            raise ValueError(f"未知笔记类型: {kind}")
        text = (text or "").strip()
        if not text:
            return None
        data = self._load()
        if source_ref and any(n.get("source_ref") == source_ref
                              for n in data["notes"]):
            return None
        note = {"id": new_id(), "kind": kind, "text": text,
                "status": "open", "concept_id": concept_id or "",
                "needs_review": bool(needs_review),
                "source_ref": source_ref or f"manual:{_slug(text)}"}
        if day is not None:
            note["created_day"] = day
        data["notes"].append(note)
        self._save(data, validator=validator)
        return note

    def update(self, nid: str, text: str | None = None,
               concept_id: str | None = None, validator=None) -> dict | None:
        """编辑文本/挂接 concept。挂接非空 concept 后清除 needs_review。"""
        data = self._load()
        for n in data["notes"]:
            if n.get("id") != nid:
                continue
            if text is not None:
                t = text.strip()
                if t:
                    n["text"] = t
            if concept_id is not None:
                n["concept_id"] = concept_id.strip()
                if n["concept_id"]:
                    n["needs_review"] = False
            self._save(data, validator=validator)
            return n
        return None

    def resolve(self, nid: str, day: int | None = None,
                validator=None) -> dict | None:
        """销账：status → resolved（幂等，已 resolved 原样返回）。"""
        data = self._load()
        for n in data["notes"]:
            if n.get("id") != nid:
                continue
            if n.get("status") != "resolved":
                n["status"] = "resolved"
                if day is not None:
                    n["resolved_day"] = day
                self._save(data, validator=validator)
            return n
        return None

    def merge(self, keep_id: str, other_ids: list[str],
              validator=None) -> dict | None:
        """合并：keep 吸收其余条文本；其余条 resolved + merged_into（不写证据）。"""
        data = self._load()
        by_id = {n.get("id"): n for n in data["notes"]}
        keep = by_id.get(keep_id)
        if keep is None:
            return None
        parts = [keep.get("text", "")]
        changed = False
        for oid in other_ids:
            other = by_id.get(oid)
            if other is None or oid == keep_id:
                continue
            if other.get("merged_into"):
                continue  # 已合并过，不重复吸收
            parts.append(other.get("text", ""))
            other["status"] = "resolved"
            other["merged_into"] = keep_id
            changed = True
        if changed:
            keep["text"] = "\n---\n".join(p for p in parts if p)
            self._save(data, validator=validator)
        return keep

    def delete(self, nid: str, validator=None) -> bool:
        data = self._load()
        before = len(data["notes"])
        data["notes"] = [n for n in data["notes"] if n.get("id") != nid]
        if len(data["notes"]) == before:
            return False
        self._save(data, validator=validator)
        return True

    # ---- 日志蒸馏 ----

    def distill_from_text(self, day: int, content: str,
                          validator=None) -> int:
        """从 StudyMemory 文本的 [同步] 卡壳/疑问行蒸馏条目。

        行格式 `- 卡壳：A、B`（可能多项）；疑问条目剥除「（待解答）」后缀。
        去重：同 kind 下与既有条目文本相等或互为子串即跳过
        （live sync 已写入的条目不会被日志蒸馏重复）。
        蒸馏条目 needs_review=True、concept_id 空，挂接留人工确认。
        """
        data = self._load()
        added = 0
        for kind, label in (("stuck", "卡壳"), ("question", "疑问")):
            m = re.search(rf"^- {label}：(.+)$", content, re.MULTILINE)
            if not m:
                continue
            body = m.group(1).strip()
            if body in ("无", "无。", ""):
                continue
            items = [x.strip() for x in re.split(r"[、，,]", body) if x.strip()]
            for idx, item in enumerate(items):
                if item.endswith(_PENDING_SUFFIX):
                    item = item[:-len(_PENDING_SUFFIX)].strip()
                if not item:
                    continue
                texts = [n.get("text", "") for n in data["notes"]
                         if n.get("kind") == kind]
                if any(item == t or (t and (item in t or t in item))
                       for t in texts):
                    continue
                data["notes"].append({
                    "id": new_id(), "kind": kind, "text": item,
                    "status": "open", "concept_id": "",
                    "needs_review": True,
                    "source_ref": f"memory:Day{day}:{kind}:{idx}",
                    "created_day": day})
                added += 1
        if added:
            self._save(data, validator=validator)
        return added
