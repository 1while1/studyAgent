"""学习资料库：注册 / 解析（txt·md·docx·pdf）/ 索引 / 章节切片。

数据单源：
- 注册表 ``<docx_dir>/materials.json``（schema_version=1，规则 14 落盘）
- 解析缓存 ``<docx_dir>/materials/_cache/<safe_id>.txt`` + ``.index.json``

解析方案（M1 拍板）：python-docx / pypdf —— 保留标题层级，供 READ_DOC 按
章节导航（Tika 平文本会丢层级，且 Java 栈无法复用）。解析后统一 cleanup
（移植 ragent TextCleanupUtil 规则：去 BOM / 行尾空白 / 压缩连续空行 / trim）。

- 资料 id = 相对 materials_dir 的 posix 路径去扩展名（确定性、LLM 友好）
- mtime 变化自动重解析；error 条目不阻断扫描
- 敏感文件（.env/证书类）不注册不解析
- video_link / code_dir 仅登记，M1 不解析
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from .backup_service import BackupService, atomic_write
from .config_service import ConfigService, WEB_ROOT
from ..domain.paths import SKIP_DIRS
from ..domain.sensitive import is_sensitive

SCHEMA_VERSION = 1
CACHE_DIRNAME = "_cache"
TYPE_BY_EXT = {".md": "md", ".txt": "txt", ".docx": "docx", ".pdf": "pdf"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_DOCX_HEADING_STYLE_RE = re.compile(r"^(?:heading|标题)\s*(\d+)", re.IGNORECASE)
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def cleanup_text(text: str) -> str:
    """解析后文本规范化（移植 ragent TextCleanupUtil.cleanup 规则）。"""
    if not text:
        return ""
    text = text.replace("﻿", "")  # BOM
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _safe_id(doc_id: str) -> str:
    """资料 id → 缓存文件名（Windows 非法字符与路径分隔符转义）。"""
    name = doc_id.replace("/", "__").replace("\\", "__")
    return re.sub(r'[<>:"|?*]+', "_", name).strip(". ") or "doc"


class MaterialsService:
    _SCANNED: set[str] = set()  # 进程级：每个注册表只自动扫描一次
    _SCAN_LOCK = threading.Lock()

    def __init__(self, config: ConfigService):
        self._config = config

    def ensure_scanned(self) -> None:
        """首次使用前自动扫描一次（mtime 幂等，后续零成本）。"""
        key = str(self.registry_path)
        if key in self._SCANNED or self.root() is None:
            return
        with self._SCAN_LOCK:
            if key in self._SCANNED:
                return
            self._SCANNED.add(key)
            try:
                self.scan()
            except Exception:
                pass  # 扫描失败不阻断使用（注册表可手工维护）

    # ---- 路径 ----

    @property
    def registry_path(self) -> Path:
        return self._config.docx_dir / "materials.json"

    @property
    def cache_dir(self) -> Path:
        return self._config.docx_dir / "materials" / CACHE_DIRNAME

    def root(self) -> Path | None:
        raw = self._config.workspace.materials_dir
        if not raw:
            return None
        p = Path(raw)
        return p if p.is_absolute() else (WEB_ROOT / raw).resolve()

    # ---- 注册表读写 ----

    def _load(self) -> dict:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("materials"), dict):
                return data
        except Exception:
            pass
        return {"schema_version": SCHEMA_VERSION, "materials": {}}

    def _save(self, reg: dict) -> None:
        reg["schema_version"] = SCHEMA_VERSION
        BackupService(self._config).atomic_persist(
            {self.registry_path: json.dumps(reg, ensure_ascii=False, indent=2)})

    def list(self) -> list[dict]:
        """用户面清单（不含内部 mtime 等字段）。"""
        reg = self._load()
        out = []
        for e in sorted(reg["materials"].values(), key=lambda x: x["id"]):
            out.append({"id": e["id"], "title": e.get("title") or e["id"],
                        "type": e["type"], "status": e["status"],
                        "indexed_at": e.get("indexed_at", ""),
                        "headings": len(e.get("headings", [])),
                        "error": e.get("error", "")})
        return out

    def get(self, doc_id: str) -> dict | None:
        return self._load()["materials"].get(doc_id)

    # ---- 扫描与注册 ----

    def scan(self) -> dict:
        """遍历 materials_dir 注册新文件、重解析变动文件、清理消失文件。"""
        root = self.root()
        reg = self._load()
        materials = reg["materials"]
        stats = {"scanned": 0, "new": 0, "reparsed": 0, "removed": 0, "errors": 0}
        if not root or not root.is_dir():
            self._save(reg)
            return stats

        found: dict[str, dict] = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".")
                           and d != CACHE_DIRNAME]
            for f in filenames:
                ext = Path(f).suffix.lower()
                if ext not in TYPE_BY_EXT or is_sensitive(f):
                    continue
                full = Path(dirpath, f)
                rel = full.relative_to(root).as_posix()
                doc_id = rel[: -len(ext)]
                found[doc_id] = {"path": full, "rel": rel, "type": TYPE_BY_EXT[ext]}
        stats["scanned"] = len(found)

        # 清理已消失的扫描条目（手工注册条目保留）
        for doc_id in [i for i, e in materials.items()
                       if e.get("source") == "scan" and i not in found]:
            del materials[doc_id]
            stats["removed"] += 1

        for doc_id, info in found.items():
            full = info["path"]
            try:
                mtime = full.stat().st_mtime
            except OSError:
                continue
            old = materials.get(doc_id)
            if old and old.get("mtime") == mtime and old.get("status") == "parsed":
                continue  # 未变化
            existed_parsed = bool(old and old.get("status") == "parsed")
            entry = {"id": doc_id, "path": str(full), "rel": info["rel"],
                     "type": info["type"], "source": "scan",
                     "title": full.stem, "mtime": mtime}
            entry = self._parse_entry(entry)
            materials[doc_id] = entry
            if entry["status"] == "error":
                stats["errors"] += 1
            elif existed_parsed:
                stats["reparsed"] += 1
            else:
                stats["new"] += 1
        self._save(reg)
        return stats

    def register(self, source: str) -> dict:
        """手工注册：绝对路径文件（解析）或 http(s) 链接（video_link 仅登记）。"""
        source = (source or "").strip().strip("`")
        if not source:
            return {"ok": False, "error": "路径/链接不能为空"}
        reg = self._load()
        materials = reg["materials"]
        if _URL_RE.match(source):
            slug = re.sub(r"[^\w]+", "-", source)[:60].strip("-")
            doc_id = f"videos/{slug}"
            if doc_id in materials:
                return {"ok": False, "error": f"已注册: {doc_id}"}
            materials[doc_id] = {
                "id": doc_id, "path": source, "rel": "", "type": "video_link",
                "source": "manual", "title": source, "status": "registered",
                "indexed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            self._save(reg)
            return {"ok": True, "id": doc_id, "type": "video_link"}
        p = Path(source)
        if not p.is_absolute():
            p = (WEB_ROOT / source).resolve()
        if is_sensitive(p.name):
            return {"ok": False, "error": "敏感文件不允许注册"}
        if not p.is_file():
            return {"ok": False, "error": f"文件不存在: {source}"}
        ext = p.suffix.lower()
        if ext not in TYPE_BY_EXT:
            return {"ok": False, "error": f"不支持的类型: {ext or '(无扩展名)'}"}
        root = self.root()
        try:
            rel = p.relative_to(root).as_posix() if root else p.name
        except ValueError:
            rel = p.name
        doc_id = rel[: -len(ext)]
        base, n = doc_id, 2
        while doc_id in materials:
            doc_id = f"{base}-{n}"
            n += 1
        entry = {"id": doc_id, "path": str(p), "rel": rel,
                 "type": TYPE_BY_EXT[ext], "source": "manual",
                 "title": p.stem, "mtime": p.stat().st_mtime}
        materials[doc_id] = self._parse_entry(entry)
        self._save(reg)
        e = materials[doc_id]
        return {"ok": e["status"] == "parsed", "id": doc_id, "type": e["type"],
                "error": e.get("error", "")}

    # ---- 解析 ----

    def _parse_entry(self, entry: dict) -> dict:
        """解析单条资料 → 缓存 txt + index；失败置 error 不抛。"""
        try:
            text = self._extract_text(Path(entry["path"]), entry["type"])
            text = cleanup_text(text)
            cap = int(self._config.get("materials_cache_max_chars", 500000))
            if len(text) > cap:
                text = text[:cap] + f"\n（已截断：原文超 {cap} 字符）"
            index = self._build_index(text)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            safe = _safe_id(entry["id"])
            atomic_write(self.cache_dir / f"{safe}.txt", text)
            atomic_write(self.cache_dir / f"{safe}.index.json",
                         json.dumps(index, ensure_ascii=False, indent=1))
            entry.update({
                "status": "parsed",
                "headings": index["headings"],
                "indexed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "error": ""})
        except Exception as e:
            entry.update({"status": "error", "error": str(e)[:200],
                          "headings": []})
        return entry

    def _extract_text(self, path: Path, doc_type: str) -> str:
        if doc_type in ("md", "txt"):
            try:
                return path.read_text(encoding="utf-8")  # 严格 UTF-8 主路径
            except UnicodeDecodeError:
                pass
            try:
                # 仅严格 GBK 成功才按 GBK（真 GBK 文件）
                return path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                # 含坏字节的 UTF-8：替换符兜底——保住其余中文，不整体转 GBK 乱码
                return path.read_text(encoding="utf-8", errors="replace")
        if doc_type == "docx":
            try:
                return self._extract_docx_styled(path)
            except Exception:
                # 部分转换工具产的 docx 有悬空关系（python-docx 报
                # "no item named 'NULL'"）→ 回退裸 XML 解析（纯 stdlib）
                return self._extract_docx_raw(path)
        if doc_type == "pdf":
            from pypdf import PdfReader  # 懒加载
            reader = PdfReader(str(path))
            parts = []
            for i, page in enumerate(reader.pages, 1):
                parts.append(f"## 第 {i} 页")
                parts.append(page.extract_text() or "")
            return "\n".join(parts)
        raise ValueError(f"不支持解析的类型: {doc_type}")

    def _extract_docx_styled(self, path: Path) -> str:
        """python-docx 主路径：按段落样式名识别标题（保层级）。"""
        import docx  # python-docx（懒加载，仅解析 docx 时需要）
        doc = docx.Document(str(path))
        lines = []
        for para in doc.paragraphs:
            t = para.text.strip()
            if not t:
                lines.append("")
                continue
            style = para.style.name if para.style is not None else ""
            m = _DOCX_HEADING_STYLE_RE.match(style or "")
            if m:
                lines.append("#" * min(int(m.group(1)), 6) + " " + t)
            elif style.lower() == "title":
                lines.append("# " + t)
            else:
                lines.append(t)
        return "\n".join(lines)

    @staticmethod
    def _extract_docx_raw(path: Path) -> str:
        """docx 兜底解析（stdlib zipfile + XML）： styles.xml 建 styleId→标题
        层级映射，document.xml 逐段提文本。兼容 python-docx 打不开的损坏关系包。"""
        import xml.etree.ElementTree as ET
        import zipfile
        W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(path) as z:
            style_level: dict[str, int] = {}
            if "word/styles.xml" in z.namelist():
                sroot = ET.fromstring(z.read("word/styles.xml"))
                for st in sroot.iter(W + "style"):
                    sid = st.get(W + "styleId") or ""
                    name_el = st.find(W + "name")
                    name = (name_el.get(W + "val") if name_el is not None else "") or ""
                    m = _DOCX_HEADING_STYLE_RE.match(name)
                    if m:
                        style_level[sid] = min(int(m.group(1)), 6)
                    elif name.lower() == "title":
                        style_level[sid] = 1
            root = ET.fromstring(z.read("word/document.xml"))
        lines = []
        for p in root.iter(W + "p"):
            texts = [t.text or "" for t in p.iter(W + "t")]
            line = "".join(texts).strip()
            level = 0
            ppr = p.find(W + "pPr")
            if ppr is not None:
                pst = ppr.find(W + "pStyle")
                if pst is not None:
                    level = style_level.get(pst.get(W + "val") or "", 0)
            if not line:
                lines.append("")
            elif level:
                lines.append("#" * level + " " + line)
            else:
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _build_index(text: str) -> dict:
        """按标题行切段。返回 {headings, chunks}；无标题时全文为单一 chunk。"""
        lines = text.split("\n")
        headings = []
        for i, line in enumerate(lines, 1):
            m = _HEADING_RE.match(line)
            if m:
                headings.append({"level": len(m.group(1)),
                                 "title": m.group(2), "line": i})
        chunks = []
        bounds = [h["line"] for h in headings]
        if bounds and bounds[0] > 1 and any(l.strip() for l in lines[: bounds[0] - 1]):
            chunks.append({"id": "s0", "title": "（篇首）",
                           "start_line": 1, "end_line": bounds[0] - 1})
        for n, h in enumerate(headings):
            end = (bounds[n + 1] - 1) if n + 1 < len(bounds) else len(lines)
            chunks.append({"id": f"s{len(chunks)}", "title": h["title"],
                           "start_line": h["line"], "end_line": end})
        if not chunks and lines:
            chunks.append({"id": "s0", "title": "（全文）",
                           "start_line": 1, "end_line": len(lines)})
        return {"headings": headings, "chunks": chunks}

    # ---- 缓存读取 ----

    def _load_cache(self, entry: dict) -> tuple[list[str], dict] | None:
        safe = _safe_id(entry["id"])
        txt = self.cache_dir / f"{safe}.txt"
        idx = self.cache_dir / f"{safe}.index.json"
        if not txt.exists() or not idx.exists():
            return None
        try:
            lines = txt.read_text(encoding="utf-8").split("\n")
            index = json.loads(idx.read_text(encoding="utf-8"))
            return lines, index
        except Exception:
            return None

    def _ensure_parsed(self, entry: dict) -> dict:
        """缓存缺失或源文件 mtime 变化时重解析（读路径的唯一写）。"""
        stale = entry.get("status") != "parsed"
        if not stale:
            try:
                stale = Path(entry["path"]).stat().st_mtime != entry.get("mtime")
            except OSError:
                stale = False  # video_link 等无磁盘文件
        if stale or self._load_cache(entry) is None:
            if Path(entry.get("path", "")).is_file():
                try:
                    entry["mtime"] = Path(entry["path"]).stat().st_mtime
                except OSError:
                    pass
                reg = self._load()
                reg["materials"][entry["id"]] = self._parse_entry(dict(entry))
                self._save(reg)
                entry = reg["materials"][entry["id"]]
        return entry

    def outline(self, entry: dict) -> str:
        headings = entry.get("headings") or []
        if not headings:
            return "（该资料无章节结构，可用 [READ_DOC:资料id#全文] 读取开头部分）"
        rows = [f"- {h['title']}（第 {h['line']} 行）" for h in headings[:60]]
        more = f"\n…（共 {len(headings)} 章，仅列前 60）" if len(headings) > 60 else ""
        return f"共 {len(headings)} 章：\n" + "\n".join(rows) + more

    def read_section(self, doc_id: str, section: str | None = None,
                     max_lines: int | None = None,
                     line: int | None = None) -> dict:
        """READ_DOC 取内容：section 省略 → 章节目录；否则切片。

        `line`（章节起始行号）优先精确命中（目录条目携带）——标题子串
        模糊命中在重名章节（"总结/附录"类）会静默错切前一同名章。
        """
        entry = self.get(doc_id)
        if not entry:
            return {"ok": False, "error": f"未注册的资料: {doc_id}",
                    "candidates": self.suggest_docs(doc_id)}
        entry = self._ensure_parsed(entry)
        if entry["status"] != "parsed":
            return {"ok": False, "id": doc_id,
                    "error": f"资料未解析（{entry['status']}）：{entry.get('error', '')}"}
        cache = self._load_cache(entry)
        if cache is None:
            return {"ok": False, "id": doc_id, "error": "解析缓存缺失"}
        lines, index = cache
        if not section and line is None:
            return {"ok": True, "kind": "outline", "id": doc_id,
                    "title": entry["title"], "outline": self.outline(entry)}
        max_lines = max_lines or int(self._config.get("ai_read_max_lines", 200))
        hit = None
        if line is not None:
            hit = next((c for c in index["chunks"]
                        if c["start_line"] == line), None)
            if hit is None:  # 行号落在章内：取包含它的章
                hit = next((c for c in index["chunks"]
                            if c["start_line"] <= line <= c["end_line"]), None)
        if hit is None and section:
            q = section.strip().strip("# ").lower()
            hit = next((c for c in index["chunks"]
                        if q and q in c["title"].lower()), None)
            if hit is None and q in ("全文", "开头", "篇首") and index["chunks"]:
                hit = index["chunks"][0]
        if hit is None:
            return {"ok": False, "id": doc_id,
                    "error": f"未找到章节: {section or f'第 {line} 行'}",
                    "outline": self.outline(entry)}
        s, e = hit["start_line"], hit["end_line"]
        truncated = ""
        if e - s + 1 > max_lines:
            e = s + max_lines - 1
            truncated = f"（已截断：仅前 {max_lines} 行）"
        return {"ok": True, "kind": "content", "id": doc_id,
                "title": entry["title"], "section": hit["title"],
                "lines": f"L{s}-L{e}", "total_lines": len(lines),
                "truncated": truncated,
                "text": "\n".join(lines[s - 1: e])}

    def read_from_start(self, doc_id: str, max_chars: int) -> dict:
        """备课预取：从头取前 max_chars（按行截断）。"""
        entry = self.get(doc_id)
        if not entry:
            return {"ok": False}
        entry = self._ensure_parsed(entry)
        if entry["status"] != "parsed":
            return {"ok": False}
        cache = self._load_cache(entry)
        if cache is None:
            return {"ok": False}
        lines, _ = cache
        out, total = [], 0
        for line in lines:
            if total + len(line) + 1 > max_chars:
                if not out and max_chars > 0:
                    out.append(line[:max_chars])  # 单行超预算：硬截断
                break
            out.append(line)
            total += len(line) + 1
        text = "\n".join(out)
        return {"ok": True, "id": doc_id, "title": entry["title"],
                "text": text, "truncated": len(text) < len("\n".join(lines))}

    # ---- id 解析与候选 ----

    @staticmethod
    def _norm(token: str) -> str:
        t = token.strip().strip("`").replace("\\", "/").lstrip("./").lstrip("/")
        return re.sub(r"\.(md|txt|docx|pdf)$", "", t, flags=re.IGNORECASE).lower()

    def resolve_doc(self, token: str) -> dict | None:
        """单元 doc token → 注册条目：精确 id → 互含后缀 → 文件名词干。"""
        t = self._norm(token)
        if not t:
            return None
        materials = self._load()["materials"]
        for doc_id, e in materials.items():
            if doc_id.lower() == t:
                return e
        for doc_id, e in materials.items():
            il = doc_id.lower()
            # 后缀匹配一律带 "/" 分隔符边界（防 token 尾部巧合重叠错配短 id 资料）
            if il.endswith("/" + t) or t.endswith("/" + il) or t == il:
                return e
        stem = t.split("/")[-1]
        if len(stem) < 4:  # 词干兜底防误命中（"ai" 这类短词不猜）
            return None
        for doc_id, e in materials.items():
            if stem in doc_id.lower().split("/")[-1]:
                return e
        return None

    def suggest_docs(self, token: str, limit: int = 5) -> list[str]:
        t = self._norm(token)
        stem = t.split("/")[-1]
        hits = [i for i in self._load()["materials"]
                if stem and stem in i.lower()]
        if not hits and len(stem) >= 4:
            hits = [i for i in self._load()["materials"]
                    if stem[: max(4, len(stem) // 2)] in i.lower()]
        return sorted(hits)[:limit]

    # ---- 注入文本 ----

    def catalog(self, max_lines: int | None = None) -> str:
        """注入 system prompt 的资料清单（空库返回 ""）。"""
        entries = self.list()
        if not entries:
            return ""
        max_lines = max_lines or int(self._config.get("materials_catalog_max_lines", 60))
        rows = []
        for e in entries:
            mark = {"parsed": f"{e['headings']} 章",
                    "error": "解析失败", "registered": "未解析"}.get(e["status"], e["status"])
            rows.append(f"- `{e['id']}`（{e['type']}，{mark}）")
        more = ""
        if len(rows) > max_lines:
            more = f"\n…（共 {len(rows)} 项，仅列前 {max_lines}）"
            rows = rows[:max_lines]
        return "\n".join(rows) + more

    def prefetch(self, tokens: list[str], max_chars: int | None = None) -> dict:
        """备课预取：按单元 doc tokens 从头取教材片段，总量封顶。

        返回 {"text": 注入文本（空=无命中）, "sources": [命中的资料 id]}。
        """
        self.ensure_scanned()
        max_chars = max_chars or int(self._config.get("materials_prefetch_max_chars", 6000))
        blocks, sources = [], []
        budget = max_chars
        for token in tokens:
            if budget <= 200:
                break
            entry = self.resolve_doc(token)
            if not entry or entry["id"] in sources:
                continue
            got = self.read_from_start(entry["id"], budget)
            if not got.get("ok") or not got["text"].strip():
                continue
            blocks.append(f"=== 资料《{got['title']}》（{got['id']}）"
                          f"{'（开头节选）' if got['truncated'] else ''} ===\n{got['text']}")
            sources.append(got["id"])
            budget -= len(got["text"])
        return {"text": "\n\n".join(blocks), "sources": sources}
