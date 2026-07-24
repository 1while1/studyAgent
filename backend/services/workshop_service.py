"""实战工坊写路径（M6，AgentDesign §7/§12）：demo/replica 白名单 + 正规工程脚手架。

- 写白名单仅 demo 根（`Workspace.demo_dir`）与 replica 根
  （`WEB_ROOT.parent/<replica_name>`，存在时）；原项目（project_dir / 各 code_roots）
  永远只读（§7 硬规）。
- 代码文件落盘走 `atomic_write`（tmp+os.replace）：validate_study 是 docx 专用
  校验器，代码文件无 validator 可挂，原子替换保住崩溃安全（规则 14 的代码文件形态，
  有意偏离已记入 docs/DevLog.md）。
- 敏感文件（domain/sensitive）一律拒写；脚手架复制后做 `{{name}}` token 替换；
  首个 demo 创建时自动为当前工作区注册 demo 代码根（settings `[[code_roots]]`）。
- 不进 Deps：与 MaterialsService 同模式，由 routes / 工具上下文按需构造。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..domain.sensitive import is_sensitive
from .backup_service import atomic_write
from .config_service import RESOURCES_DIR, WEB_ROOT, ConfigService

SCAFFOLDS_DIR = RESOURCES_DIR / "scaffolds"

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class WorkshopError(Exception):
    """白名单越界 / 敏感文件 / 脚手架参数非法等可预期失败。"""


class WorkshopService:
    def __init__(self, config: ConfigService):
        self._config = config

    # ---- 根目录 ----

    def demo_root(self) -> Path:
        return Path(self._config.workspace.demo_dir).resolve()

    def replica_root(self) -> Path | None:
        ws = self._config.workspace
        if not ws.replica_name:
            return None
        p = (WEB_ROOT.parent / ws.replica_name).resolve()
        return p if p.is_dir() else None

    def writable_roots(self) -> dict[str, Path]:
        """写白名单：{别名: 绝对路径}。原项目根永远不在其中。"""
        roots = {"demo": self.demo_root()}
        rep = self.replica_root()
        if rep is not None:
            roots["replica"] = rep
        return roots

    # ---- 脚手架 ----

    def scaffold_types(self) -> list[dict]:
        out = []
        if SCAFFOLDS_DIR.is_dir():
            for d in sorted(SCAFFOLDS_DIR.iterdir(), key=lambda x: x.name):
                if d.is_dir() and any(d.iterdir()):
                    out.append({"type": d.name,
                                "description": _scaffold_description(d)})
        return out

    def scaffold_create(self, stype: str, name: str) -> dict:
        """复制脚手架到 demo 根下的 <name>/ 并做 {{name}} 替换。

        返回 {name, path（demo 别名路径）, files, code_root}；失败抛 WorkshopError。
        """
        stype = (stype or "").strip()
        name = (name or "").strip()
        src = SCAFFOLDS_DIR / stype
        if not stype or not src.is_dir():
            raise WorkshopError(
                f"未知脚手架类型: {stype or '（空）'}"
                f"（可用: {[t['type'] for t in self.scaffold_types()]}）")
        if not _NAME_RE.match(name):
            raise WorkshopError(
                f"非法 demo 名称: {name or '（空）'}（仅限字母/数字/_/-，≤40 字符）")
        demo = self.demo_root()
        target = (demo / name).resolve()
        if demo != target.parent:
            raise WorkshopError("目标路径越出 demo 根（拒绝）")
        if target.exists() and any(target.iterdir()):
            raise WorkshopError(f"demo 已存在且非空: {name}")
        # 先注册代码根（注册失败什么都不产生，可直接重试——M6 审查修复 A1）
        code_root = self._ensure_demo_code_root()
        target.mkdir(parents=True, exist_ok=True)
        try:
            files = _copy_scaffold(src, target, name)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)  # 复制中途失败回滚，允许重入
            raise
        return {"name": name, "path": f"demo/{name}", "files": files,
                "code_root": code_root,
                "abs_path": str(target)}

    # ---- 写路径 ----

    def resolve_write(self, alias_path: str) -> Path:
        """把 `demo/...` / `replica/...` 别名路径解析为白名单内的绝对路径。"""
        alias_path = (alias_path or "").strip().replace("\\", "/")
        alias, _, rel = alias_path.partition("/")
        roots = self.writable_roots()
        if alias not in roots:
            raise WorkshopError(
                f"路径须以白名单别名开头（{sorted(roots)}）：{alias_path or '（空）'}")
        if not rel:
            raise WorkshopError("缺少相对路径（不可直接写根目录）")
        root = roots[alias]
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise WorkshopError(f"路径越出白名单根（拒绝）: {alias_path}")
        if is_sensitive(target.name):
            raise WorkshopError("敏感文件（密钥/证书类）不允许写入")
        return target

    def write_alias(self, alias_path: str, content: str) -> dict:
        """AI edit_file 工具的落盘入口：别名路径 + 全量内容。"""
        target = self.resolve_write(alias_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content)
        return {"path": alias_path, "bytes": len(content.encode("utf-8"))}

    def save_via_root(self, root_name: str, rel: str, content: str) -> dict:
        """UI 保存入口：按代码根名解析后做白名单包含校验。"""
        root_name = (root_name or "").strip()
        rel = (rel or "").strip()
        raw = None
        for r in self._config.code_roots:
            if r["name"] == root_name:
                raw = r["path"]
                break
        if raw is None:
            raise WorkshopError(f"未配置的项目根: {root_name or '（空）'}")
        p = Path(raw)
        root = p if p.is_absolute() else (WEB_ROOT / raw).resolve()
        root = root.resolve()
        # 代码根必须与某个白名单根重合或位于其内部（replica/demo 子目录也算可写；
        # 反向——代码根是白名单根的祖先——不允许，防止写范围被放大到白名单之外）
        writable = any(root == w or w in root.parents
                       for w in self.writable_roots().values())
        if not writable:
            raise WorkshopError(
                f"项目根「{root_name}」为只读（仅 demo / replica 白名单可写）")
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise WorkshopError(f"路径越出项目根（拒绝）: {rel}")
        if is_sensitive(target.name):
            raise WorkshopError("敏感文件（密钥/证书类）不允许写入")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content)
        return {"root": root_name, "path": rel,
                "bytes": len(content.encode("utf-8"))}

    def editable(self, root_name: str, rel: str) -> bool:
        """/api/code/file 的可编辑标记：任何异常一律 False（只读是安全缺省）。"""
        try:
            raw = next((r["path"] for r in self._config.code_roots
                        if r["name"] == root_name), None)
            if raw is None:
                return False
            p = Path(raw)
            root = (p if p.is_absolute() else (WEB_ROOT / raw).resolve()).resolve()
            target = (root / rel).resolve()
            if root != target and root not in target.parents:
                return False
            if is_sensitive(target.name):
                return False
            return any(root == w or w in root.parents
                       for w in self.writable_roots().values())
        except Exception:
            return False

    def file_mtime(self, root_name: str, rel: str) -> float | None:
        """代码根内文件的 mtime（UI 保存冲突检测，Y11）；任何失败返回 None。"""
        try:
            raw = next((r["path"] for r in self._config.code_roots
                        if r["name"] == (root_name or "").strip()), None)
            if raw is None:
                return None
            p = Path(raw)
            root = (p if p.is_absolute() else (WEB_ROOT / raw).resolve()).resolve()
            target = (root / (rel or "").strip()).resolve()
            if root != target and root not in target.parents:
                return None
            return target.stat().st_mtime
        except Exception:
            return None

    # ---- demo 代码根注册 ----

    def _ensure_demo_code_root(self) -> str:
        """为当前工作区注册 demo 代码根（幂等；已存在则直接返回根名）。

        ⚠️ 写 settings 必须基于**全量未过滤**根清单（M6 审查修复 R1）：
        config.code_roots 按当前工作区过滤，用它重写会丢别的工作区的根。
        """
        slug = self._config.workspace.slug
        name = "demo"
        all_roots = list(self._config.data.get("code_roots", []))
        for r in all_roots:
            if r["name"] == name and r.get("workspace", slug) == slug:
                return name
        demo = self.demo_root()
        try:
            raw = demo.relative_to(WEB_ROOT).as_posix()
        except ValueError:
            raw = str(demo)
        from .config_writer import update_code_roots
        update_code_roots(self._config.path, all_roots + [
            {"name": name, "path": raw, "workspace": slug}])
        self._config.reload()
        return name


def _scaffold_description(src: Path) -> str:
    readme = src / "README.md"
    if readme.is_file():
        for line in readme.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:80]
    return ""


def _copy_scaffold(src: Path, target: Path, name: str) -> int:
    """复制脚手架树并做 {{name}} 文本替换。返回文件数。"""
    count = 0
    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        dest = target / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = item.read_text(encoding="utf-8")
        dest.write_text(text.replace("{{name}}", name), encoding="utf-8")
        count += 1
    return count
