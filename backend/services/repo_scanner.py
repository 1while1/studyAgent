"""仓库扫描：生成目标项目的紧凑画像（纯函数，无状态）。

供三处复用：初始化向导预览、Project.md 生成、手动重新扫描。
"""

from __future__ import annotations

from pathlib import Path

from ..domain.paths import SKIP_DIRS

MAX_PROFILE_CHARS = 9000      # 画像总长度封顶（控制 prompt 体积）
MAX_TREE_LINES = 120          # 目录树行数封顶
TREE_DEPTH = 3                # 目录树层数
BUILD_FILES = ["pom.xml", "build.gradle", "build.gradle.kts", "package.json",
               "go.mod", "Cargo.toml", "requirements.txt", "pyproject.toml",
               "composer.json", "Gemfile"]
README_NAMES = ["README.md", "README.zh-CN.md", "README.txt", "README"]
FILE_HEAD_CHARS = 800

ENTRY_NAMES = {"main.py", "__main__.py", "app.py", "manage.py", "main.go",
               "index.js", "Program.cs"}
ENTRY_SCAN_DEPTH = 10         # Maven 标准布局 + 包名层级较深
ENTRY_VISIT_CAP = 20000       # 入口扫描最多访问的文件数（防巨型仓库拖慢）
ENTRY_CAP = 15
DEP_EDGE_CAP = 30
CONFIG_CAP = 3
CONFIG_HEAD_CHARS = 400


def _walk_files(root: Path, depth: int, budget: list[int] | None = None):
    """深度受限的文件遍历（跳过 SKIP_DIRS 与点目录），budget 为剩余访问量。"""
    def walk(d: Path, level: int):
        if level > depth or (budget is not None and budget[0] <= 0):
            return
        try:
            children = sorted(d.iterdir(), key=lambda c: c.name.lower())
        except (PermissionError, OSError):
            return
        for c in children:
            if budget is not None:
                budget[0] -= 1
                if budget[0] <= 0:
                    return
            if c.name.startswith(".") or c.name in SKIP_DIRS:
                continue
            if c.is_dir():
                yield from walk(c, level + 1)
            else:
                yield c
    yield from walk(root, 1)


def _find_entries(root: Path) -> list[str]:
    """入口识别：SpringBoot 启动类 / 常见脚本入口，返回相对路径（≤ENTRY_CAP）。"""
    hits = []
    for f in _walk_files(root, ENTRY_SCAN_DEPTH, [ENTRY_VISIT_CAP]):
        if f.name in ENTRY_NAMES:
            hits.append(str(f.relative_to(root)).replace("\\", "/"))
        elif f.suffix == ".java" and f.stem.endswith("Application"):
            head = _read_head(f, 2000)
            if "@SpringBootApplication" in head:
                hits.append(str(f.relative_to(root)).replace("\\", "/"))
        if len(hits) >= ENTRY_CAP:
            break
    return hits


def _module_edges(root: Path, module_dirs: list[str]) -> list[str]:
    """模块依赖线索：模块 a 的构建文件文本中出现模块 b 的名字 → a → b。"""
    edges = []
    for a in module_dirs:
        for bf in BUILD_FILES:
            f = root / a / bf
            if not f.is_file():
                continue
            text = _read_head(f, 20000)
            for b in module_dirs:
                if a != b and b in text:
                    edges.append(f"{a} → {b}")
            break  # 每模块只看第一个命中的构建文件
        if len(edges) >= DEP_EDGE_CAP:
            break
    return edges[:DEP_EDGE_CAP]


def _find_configs(root: Path) -> list[Path]:
    hits = []
    for f in _walk_files(root, 5):
        if f.name.startswith("application") and \
                f.suffix in (".yml", ".yaml", ".properties"):
            hits.append(f)
            if len(hits) >= CONFIG_CAP:
                break
    return hits


def _tree(root: Path) -> list[str]:
    lines = [f"{root.name}/"]
    count = 0

    def walk(d: Path, depth: int, prefix: str) -> None:
        nonlocal count
        if depth > TREE_DEPTH or count >= MAX_TREE_LINES:
            return
        try:
            children = sorted(
                (c for c in d.iterdir()
                 if not c.name.startswith(".") and c.name not in SKIP_DIRS),
                key=lambda c: (c.is_file(), c.name.lower()))
        except PermissionError:
            return
        for child in children:
            if count >= MAX_TREE_LINES:
                return
            count += 1
            suffix = "/" if child.is_dir() else ""
            lines.append(f"{prefix}├── {child.name}{suffix}")
            if child.is_dir():
                walk(child, depth + 1, prefix + "│   ")

    walk(root, 1, "")
    if count >= MAX_TREE_LINES:
        lines.append("├── …（树过大，已截断）")
    return lines


def _read_head(path: Path, chars: int = FILE_HEAD_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:chars]


def scan(project_dir: str | Path) -> str:
    """生成项目画像文本。目录不存在时抛 FileNotFoundError。"""
    root = Path(project_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"项目目录不存在: {root}")

    parts = [f"# 项目画像：{root.name}", "", "## 目录结构", "```"]
    parts += _tree(root)
    parts.append("```")

    builds = [f for f in BUILD_FILES if (root / f).is_file()]
    # 一级子目录的构建文件也纳入（多模块项目）
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name not in SKIP_DIRS \
                and not child.name.startswith("."):
            for f in BUILD_FILES:
                if (child / f).is_file():
                    builds.append(f"{child.name}/{f}")
    if builds:
        parts += ["", "## 构建文件"]
        for b in dict.fromkeys(builds):  # 去重保序
            head = _read_head(root / b)
            if head:
                parts += [f"### {b}", "```", head, "```"]

    for name in README_NAMES:
        p = root / name
        if p.is_file():
            parts += ["", "## README", _read_head(p, 1000)]
            break

    entries = _find_entries(root)
    if entries:
        parts += ["", "## 入口识别"]
        parts += [f"- {e}" for e in entries]

    module_dirs = [c.name for c in sorted(root.iterdir())
                   if c.is_dir() and not c.name.startswith(".")
                   and c.name not in SKIP_DIRS
                   and any((c / bf).is_file() for bf in BUILD_FILES)]
    edges = _module_edges(root, module_dirs)
    if edges:
        parts += ["", "## 模块依赖线索（构建文件交叉引用）"]
        parts += [f"- {e}" for e in edges]

    configs = _find_configs(root)
    if configs:
        parts += ["", "## 关键配置"]
        for c in configs:
            rel = str(c.relative_to(root)).replace("\\", "/")
            parts += [f"### {rel}", "```", _read_head(c, CONFIG_HEAD_CHARS), "```"]

    profile = "\n".join(parts)
    if len(profile) > MAX_PROFILE_CHARS:
        profile = profile[:MAX_PROFILE_CHARS] + "\n…（画像过长，已截断）"
    return profile
