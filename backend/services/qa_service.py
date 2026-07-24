"""面试话术层服务（M4）：InterviewQA.md 的结构化解析、渲染与落盘。

条目格式契约 = resources/sop/SOP_同步.md 的 interview_qa_entry 锚点模板：
  ## <问题标题>
  **标签**：#<模块> #<技术点>
  **关联代码**：`<文件路径>:<行号>`
  **精简版（30秒）**：<内容>
  **展开版（2分钟）**：<内容>
  **追问预案**：- Q: ... A: ...（≥3 组）
  **产出来源**：Day <N> <场景>

解析规则：`## ` 标题且块内含 `**产出来源**：` = 条目；其前文（文件头与
「问题模板」「已累积话术」等固定小节）= preamble 原样保留；条目共 5 个加粗
字段，标签/来源行冒号全半角均容忍。entry id = sha1(title+source)[:8]
（仅单次请求内定位用，内容变则 id 变）。渲染一律用全角冒号（end_day 按
`**产出来源**：Day {day} ` 前缀统计条数，此契约不可破）。
"""

from __future__ import annotations

import hashlib
import re

from .backup_service import BackupService
from .config_service import ConfigService

# 骨架模板中的占位行，首次追加真实条目时剥离
PLACEHOLDER_LINES = ("（待产生）", "（学习开始后自动累积）")

_FIELD_RE = re.compile(r"^\*\*(.+?)\*\*[:：]\s*(.*)$")
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_QA_Q_RE = re.compile(r"^\s*-\s*Q[:：]\s*(.*)$")
_QA_A_RE = re.compile(r"^\s+A[:：]\s*(.*)$")
_SOURCE_MARK = "**产出来源**"

_BRIEF_LABEL = "精简版（30秒）"
_DETAIL_LABEL = "展开版（2分钟）"

# 固定小节标题（骨架模板区，永不视为条目）
RESERVED_HEADINGS = {"问题模板", "已累积话术"}
# 已知字段名：只有这些 `**X**：` 行才是字段分隔，内容里的加粗行不误切
_KNOWN_FIELDS = {"标签", "关联代码", _BRIEF_LABEL, _DETAIL_LABEL,
                 "追问预案", "产出来源"}


def _entry_id(title: str, source: str) -> str:
    return hashlib.sha1(f"{title}|{source}".encode("utf-8")).hexdigest()[:8]


def _parse_block(block: str) -> dict | None:
    """单个 `## ` 块 → 条目 dict；非条目（保留小节/无产出来源）返回 None。"""
    if _SOURCE_MARK not in block:
        return None
    lines = block.splitlines()
    m = _HEADING_RE.match(lines[0]) if lines else None
    if not m or m.group(1) in RESERVED_HEADINGS:
        return None
    entry = {"title": m.group(1), "tags": [], "code_ref": "",
             "brief": "", "detail": "", "followups": [], "source": ""}
    field: str | None = None
    buf: list[str] = []

    def flush():
        nonlocal buf, field
        if field is None:
            return
        body = "\n".join(buf).strip()
        if field == "标签":
            entry["tags"] = re.findall(r"#([^\s#]+)", body)
        elif field == "关联代码":
            entry["code_ref"] = body.strip("`").strip()
        elif field == _BRIEF_LABEL:
            entry["brief"] = body
        elif field == _DETAIL_LABEL:
            entry["detail"] = body
        elif field == "追问预案":
            qas, q, a = [], None, None
            for ln in body.splitlines():
                mq, ma = _QA_Q_RE.match(ln), _QA_A_RE.match(ln)
                if mq:
                    if q is not None:
                        qas.append((q, a or ""))
                    q, a = mq.group(1).strip(), None
                elif ma and q is not None:
                    a = ma.group(1).strip()
            if q is not None:
                qas.append((q, a or ""))
            entry["followups"] = qas
        elif field == "产出来源":
            entry["source"] = body.splitlines()[0].strip() if body else ""
        buf, field = [], None

    for line in lines[1:]:
        fm = _FIELD_RE.match(line)
        if fm and fm.group(1).strip() in _KNOWN_FIELDS:
            flush()
            field, buf = fm.group(1).strip(), [fm.group(2)]
        else:
            buf.append(line)
    flush()
    entry["id"] = _entry_id(entry["title"], entry["source"])
    return entry


def render_entry(entry: dict) -> str:
    """条目 dict → canonical markdown（全角冒号，产出来源契约行）。"""
    tags = " ".join(t if t.startswith("#") else f"#{t}"
                    for t in entry.get("tags", [])) or "#待补"
    code_ref = entry.get("code_ref") or "待补"
    followups = entry.get("followups") or [("待补", "待补")]
    qa_lines = []
    for q, a in followups:
        qa_lines.append(f"- Q: {q}")
        qa_lines.append(f"  A: {a}")
    return (f"## {entry['title']}\n\n"
            f"**标签**：{tags}\n"
            f"**关联代码**：`{code_ref}`\n\n"
            f"**精简版（30秒）**：\n{entry.get('brief', '')}\n\n"
            f"**展开版（2分钟）**：\n{entry.get('detail', '')}\n\n"
            f"**追问预案**：\n" + "\n".join(qa_lines) + "\n\n"
            f"**产出来源**：{entry.get('source', '')}")


def parse(md: str) -> dict:
    """全文 → {"preamble": str, "entries": [...], "tail": str}。

    preamble = 首个条目前的全部内容（原样）；tail = 条目区中无法解析为
    条目的尾部内容（原样保留，防手工编辑内容丢失）。
    """
    lines = md.splitlines()
    starts = [i for i, ln in enumerate(lines) if _HEADING_RE.match(ln)]
    first_entry_idx = None
    for k, i in enumerate(starts):
        nxt = starts[k + 1] if k + 1 < len(starts) else len(lines)
        if _parse_block("\n".join(lines[i:nxt])) is not None:
            first_entry_idx = i
            break
    if first_entry_idx is None:
        return {"preamble": md.rstrip(), "entries": [], "tail": ""}
    preamble = "\n".join(lines[:first_entry_idx]).rstrip()
    entries, tail_blocks = [], []
    region_starts = [i for i in starts if i >= first_entry_idx] + [len(lines)]
    for k in range(len(region_starts) - 1):
        block = "\n".join(lines[region_starts[k]:region_starts[k + 1]])
        entry = _parse_block(block)
        # 坏块仅自身进 tail，其后合法条目仍正常解析（修复：一个坏块
        # 曾使其后全部条目降级进 tail）
        if entry is not None:
            entries.append(entry)
        else:
            tail_blocks.append(block)
    return {"preamble": preamble, "entries": entries,
            "tail": "\n\n".join(tail_blocks).strip()}


def render(preamble: str, entries: list[dict], tail: str = "") -> str:
    parts = []
    if preamble.strip():
        parts.append(preamble.rstrip())
    parts.extend(render_entry(e) for e in entries)
    if tail.strip():
        parts.append(tail.rstrip())
    return "\n\n".join(parts) + "\n"


def validate_capture(md: str) -> list[dict] | None:
    """拷打反喂产物的机械校验：返回合法条目列表，全不合法返回 None。

    每条必须含 5 个加粗字段（标签/关联代码/精简版/展开版/追问预案/产出来源
    中的标签、精简版、展开版、追问预案、产出来源）且追问预案 ≥ 3 组 Q/A。
    """
    blocks = re.split(r"(?=^## )", md, flags=re.MULTILINE)
    valid = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        entry = _parse_block(block)
        if entry is None:
            continue
        if not entry["brief"] or not entry["detail"]:
            continue
        if len(entry["followups"]) < 3:
            continue
        valid.append(entry)
    return valid or None


class QaService:
    def __init__(self, config: ConfigService):
        self._config = config
        self.path = config.docx_dir / "InterviewQA.md"

    # ---- 读写 ----

    def _read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _save(self, md: str, validator=None) -> None:
        BackupService(self._config).atomic_persist({self.path: md},
                                                   validator=validator)

    # ---- 查询 ----

    def entries(self) -> list[dict]:
        return parse(self._read())["entries"]

    # ---- 写入 ----

    def add_entry(self, raw_md: str, validator=None) -> None:
        """追加条目原文（sync/capture 共用）。首次追加剥离骨架占位行。"""
        old = self._read()
        lines = [ln for ln in old.splitlines()
                 if ln.strip() not in PLACEHOLDER_LINES]
        old = "\n".join(lines).rstrip()
        new = (old + "\n\n" + raw_md.strip() + "\n") if old else raw_md.strip() + "\n"
        self._save(new, validator=validator)

    def update_entry(self, entry_id: str, validator=None, **fields) -> dict | None:
        """按 id 更新字段（title/tags/code_ref/brief/detail/followups）。"""
        doc = parse(self._read())
        target = None
        for e in doc["entries"]:
            if e["id"] == entry_id:
                target = e
                break
        if target is None:
            return None
        for k in ("title", "tags", "code_ref", "brief", "detail", "followups"):
            if k in fields and fields[k] is not None:
                target[k] = fields[k]
        target["id"] = _entry_id(target["title"], target["source"])
        self._save(render(doc["preamble"], doc["entries"], doc["tail"]),
                   validator=validator)
        return target

    def delete_entry(self, entry_id: str, validator=None) -> bool:
        doc = parse(self._read())
        before = len(doc["entries"])
        doc["entries"] = [e for e in doc["entries"] if e["id"] != entry_id]
        if len(doc["entries"]) == before:
            return False
        self._save(render(doc["preamble"], doc["entries"], doc["tail"]),
                   validator=validator)
        return True
