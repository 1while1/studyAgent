"""仓库扫描：生成目标项目的紧凑画像（纯函数，无状态）。

供三处复用：初始化向导预览、Project.md 生成、手动重新扫描。
"""

from __future__ import annotations

from pathlib import Path

from ..domain.paths import SKIP_DIRS

MAX_PROFILE_CHARS = 6000      # 画像总长度封顶（控制 prompt 体积）
MAX_TREE_LINES = 120          # 目录树行数封顶
TREE_DEPTH = 3                # 目录树层数
BUILD_FILES = ["pom.xml", "build.gradle", "build.gradle.kts", "package.json",
               "go.mod", "Cargo.toml", "requirements.txt", "pyproject.toml",
               "composer.json", "Gemfile"]
README_NAMES = ["README.md", "README.zh-CN.md", "README.txt", "README"]
FILE_HEAD_CHARS = 800


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

    profile = "\n".join(parts)
    if len(profile) > MAX_PROFILE_CHARS:
        profile = profile[:MAX_PROFILE_CHARS] + "\n…（画像过长，已截断）"
    return profile
