"""settings.toml 节区级更新器（stdlib 无 TOML 写库，按节替换保结构）。

只重写指定 [section] 块，文件其余内容（stages/commands 等）原样保留。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .backup_service import atomic_write


class ConfigWriteError(Exception):
    pass


def update_toml_sections(path: Path, sections: dict[str, list[str]]) -> None:
    """sections: {"llm": ["[llm]", "provider = ...", ...], ...}"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    replaced = set()
    while i < len(lines):
        m = re.match(r"^\[([^\[\]]+)\]\s*$", lines[i].strip())
        if m and m.group(1) in sections:
            name = m.group(1)
            out.extend(sections[name])
            replaced.add(name)
            i += 1
            comments = []
            while i < len(lines) and not re.match(r"^\s*\[", lines[i]):
                if lines[i].strip().startswith("#"):
                    comments.append(lines[i])
                i += 1  # 跳过旧节区正文（保留节区外内容）
            # 旧节区内的独立注释行保留到新区块末尾（防 UI 保存吞注释）
            out.extend(comments)
            continue
        out.append(lines[i])
        i += 1
    missing = set(sections) - replaced
    if missing:
        raise ConfigWriteError(f"settings.toml 中未找到节区: {missing}")
    atomic_write(path, "\n".join(out) + "\n")


def update_env_file(path: Path, values: dict[str, str]) -> None:
    """更新 .env 中的键（存在则替换，不存在则追加）。空值跳过。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done = set()
    out = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                done.add(key)
                continue
        out.append(line)
    for key, value in values.items():
        if key not in done:
            out.append(f"{key}={value}")
    atomic_write(path, "\n".join(out) + "\n")
    for key, value in values.items():  # 运行时立即生效
        os.environ[key] = value


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def update_code_roots(path: Path, roots: list[dict]) -> None:
    """重写 settings.toml 中全部 [[code_roots]] 数组节（其余内容原样保留）。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "[[code_roots]]":
            i += 1
            # 跳过该数组节的键值行与空行，直到下一个节头
            while i < len(lines) and not re.match(r"^\s*\[", lines[i]):
                i += 1
            # 去掉可能残留的空行
            while out and out[-1].strip() == "":
                out.pop()
            out.append("")
            continue
        out.append(lines[i])
        i += 1
    for root in roots:
        out.append("")
        out.append("[[code_roots]]")
        out.append(f'name = "{_esc(root["name"])}"')
        out.append(f'path = "{_esc(root["path"])}"')
        if root.get("workspace"):
            out.append(f'workspace = "{_esc(root["workspace"])}"')
    atomic_write(path, "\n".join(out) + "\n")


def _esc(value) -> str:
    """TOML 基本字符串转义。"""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def update_workspaces(path: Path, workspaces: list[dict], active: str) -> None:
    """重写 settings.toml 的 active_workspace 顶层键与全部 [[workspaces]] 数组节。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    active_written = False
    while i < len(lines):
        line = lines[i]
        if line.strip() == "[[workspaces]]":
            i += 1
            while i < len(lines) and not re.match(r"^\s*\[", lines[i]):
                i += 1
            while out and out[-1].strip() == "":
                out.pop()
            out.append("")
            continue
        if re.match(r"^active_workspace\s*=", line.strip()):
            out.append(f'active_workspace = "{_esc(active)}"')
            active_written = True
            i += 1
            continue
        out.append(line)
        i += 1
    if not active_written:
        # 顶层键必须位于任何节区之前
        insert_at = next((idx for idx, l in enumerate(out)
                          if l.strip().startswith("[")), len(out))
        out.insert(insert_at, f'active_workspace = "{_esc(active)}"')
    for w in workspaces:
        out.append("")
        out.append("[[workspaces]]")
        for key, value in w.items():
            if isinstance(value, int):
                out.append(f"{key} = {value}")
            else:
                out.append(f'{key} = "{_esc(value)}"')
    atomic_write(path, "\n".join(out) + "\n")
