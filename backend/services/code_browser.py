"""代码浏览器服务：项目根解析、目录树、文件读取（只读，带穿越防护）。"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .config_service import ConfigService, WEB_ROOT
from ..domain.paths import SKIP_DIRS
from ..domain.sensitive import is_sensitive

MAX_FILE_BYTES = 1024 * 1024  # 1MB 上限
INDEX_TTL = 60  # 文件索引缓存秒数（resolve 后缀搜索用）
INDEX_CAP = 30000  # 单根索引文件数上限


def _is_sensitive(name: str) -> bool:
    """兼容别名：实现已迁至 domain.sensitive（materials 等共用）。"""
    return is_sensitive(name)

TEXT_EXTS = {
    ".java", ".xml", ".yml", ".yaml", ".properties", ".md", ".txt", ".json",
    ".py", ".js", ".ts", ".html", ".css", ".sql", ".toml", ".gradle", ".vue",
    ".jsx", ".tsx", ".go", ".rs", ".c", ".h", ".cpp", ".sh", ".bat", ".gitignore",
}

LANG_MAP = {
    ".java": "java", ".xml": "xml", ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".html": "xml", ".css": "css", ".sql": "sql", ".md": "markdown",
    ".properties": "properties", ".gradle": "groovy", ".sh": "bash",
    ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".vue": "xml", ".jsx": "javascript", ".tsx": "typescript",
}

class CodeBrowserError(Exception):
    pass


class CodeBrowser:
    def __init__(self, config: ConfigService):
        self._config = config
        self._index_cache: dict[str, tuple[float, list[str]]] = {}

    # ---- 项目根 ----

    def roots(self) -> list[dict]:
        result = []
        for r in self._config.code_roots:
            p = self._resolve_root(r["path"])
            result.append({"name": r["name"], "path": r["path"],
                           "exists": p is not None and p.is_dir()})
        return result

    def _resolve_root(self, raw: str) -> Path | None:
        p = Path(raw)
        if not p.is_absolute():
            p = (WEB_ROOT / raw).resolve()
        return p

    def root_path(self, name: str) -> Path:
        for r in self._config.code_roots:
            if r["name"] == name:
                p = self._resolve_root(r["path"])
                if p and p.is_dir():
                    return p
                raise CodeBrowserError(f"项目根目录不存在: {r['path']}")
        raise CodeBrowserError(f"未配置的项目根: {name}")

    def _safe_join(self, root: Path, rel: str) -> Path:
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise CodeBrowserError("非法路径（越出项目根）")
        return target

    # ---- 目录树（懒加载单层） ----

    def list_dir(self, root_name: str, rel: str = "") -> list[dict]:
        root = self.root_path(root_name)
        target = self._safe_join(root, rel) if rel else root
        if not target.is_dir():
            raise CodeBrowserError(f"不是目录: {rel}")
        entries = []
        for child in sorted(target.iterdir(),
                            key=lambda c: (c.is_file(), c.name.lower())):
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if child.is_dir():
                entries.append({"name": child.name, "type": "dir"})
            elif child.suffix.lower() in TEXT_EXTS or not child.suffix:
                entries.append({"name": child.name, "type": "file",
                                "size": child.stat().st_size})
        return entries

    # ---- 文件读取 ----

    def read_file(self, root_name: str, rel: str) -> dict:
        root = self.root_path(root_name)
        target = self._safe_join(root, rel)
        if _is_sensitive(target.name):
            raise CodeBrowserError("敏感文件（密钥/证书类）不允许在线查看")
        if not target.is_file():
            raise CodeBrowserError(f"文件不存在: {rel}")
        size = target.stat().st_size
        if size > MAX_FILE_BYTES:
            raise CodeBrowserError(f"文件过大（{size // 1024}KB > 1MB），不支持在线查看")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise CodeBrowserError("二进制或无法识别的编码，不支持查看")
        return {
            "content": content,
            "lines": content.count("\n") + 1,
            "lang": LANG_MAP.get(target.suffix.lower(), "plaintext"),
            "path": rel,
            "root": root_name,
        }

    # ---- 路径解析（AI 回答中的代码引用 → 真实文件） ----

    def resolve(self, query: str) -> dict | None:
        """三级解析：根名前缀 → 直接相对路径 → 后缀索引搜索。

        返回 {"root": name, "path": rel} 或 None。
        """
        q = query.strip().strip("`").replace("\\", "/")
        q = re.sub(r":L?\d+(?:-L?\d+)?$", "", q)  # 剥离行号后缀（:L4-L11）
        q = q.lstrip("./").lstrip("/")
        if not q:
            return None
        roots = [(r["name"], self._resolve_root(r["path"]))
                 for r in self._config.code_roots]
        roots = [(n, p) for n, p in roots if p is not None and p.is_dir()]
        # 1) 根名前缀（如 <根名>/infra-ai/pom.xml）
        for name, root in roots:
            if q == name or q.startswith(name + "/"):
                rel = q[len(name):].lstrip("/")
                if rel and self._is_file(root, rel):
                    return {"root": name, "path": rel}
        # 2) 直接相对路径（如 infra-ai/pom.xml）
        for name, root in roots:
            if self._is_file(root, q):
                return {"root": name, "path": q}
        # 3) 后缀索引搜索（如 core/prompt_manager.py 或 prompt_manager.py）
        best: dict | None = None
        ql = q.lower()
        for name, root in roots:
            for rel in self._index(name, root):
                rl = rel.lower()
                if rl == ql or rl.endswith("/" + ql):
                    if best is None or len(rel) < len(best["path"]):
                        best = {"root": name, "path": rel}
        return best

    def _is_file(self, root: Path, rel: str) -> bool:
        try:
            return self._safe_join(root, rel).is_file()
        except CodeBrowserError:
            return False

    def suggest(self, query: str, limit: int = 5) -> list[dict]:
        """resolve 未命中时的模糊候选，供 AI 纠正路径。

        两级匹配：完整文件名子串（优先）→ 词干最长前缀（≥6 字符）子串，
        后者兼容 Java 命名后缀差异（Entity/DO/DTO/VO 互换，如
        CouponTemplateEntity vs CouponTemplateDO）。
        """
        q = query.strip().strip("`").replace("\\", "/")
        q = re.sub(r":L?\d+(?:-L?\d+)?$", "", q).lower()
        base = q.split("/")[-1]
        stem = base.rsplit(".", 1)[0]
        hits: list[tuple[tuple, dict]] = []
        for r in self._config.code_roots:
            root = self._resolve_root(r["path"])
            if not root or not root.is_dir():
                continue
            for rel in self._index(r["name"], root):
                rl = rel.lower()
                if base and base in rl:
                    key = (0, -len(base), len(rel))
                else:
                    cut = 0
                    for c in range(len(stem), 5, -1):
                        if stem[:c] in rl:
                            cut = c
                            break
                    if not cut:
                        continue
                    key = (1, -cut, len(rel))
                hits.append((key, {"root": r["name"], "path": rel}))
        hits.sort(key=lambda h: h[0])
        return [h[1] for h in hits[:limit]]

    def _index(self, name: str, root: Path) -> list[str]:
        now = time.time()
        ts, files = self._index_cache.get(name, (0.0, []))
        if now - ts < INDEX_TTL:
            return files
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                if _is_sensitive(f):
                    continue
                files.append(str(Path(dirpath, f).relative_to(root))
                             .replace("\\", "/"))
            if len(files) >= INDEX_CAP:
                break
        self._index_cache[name] = (now, files)
        return files
