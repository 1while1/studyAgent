"""StudyMemory/Day_<NN>.md 的生成、解析与局部修改。

文件结构契约见 StudyFlow.md 第 11 节（7 个字段），validate_study.py 依赖同一口径。
所有函数都在「读出的文本」上工作并返回新文本，落盘由 backup_service 编排。
"""

from __future__ import annotations

import re
from pathlib import Path

from .config_service import ConfigService

def section_headers(replica_name: str) -> list[str]:
    """StudyMemory 必含小节（与 resources/hooks/validate_study.py 同一口径）。"""
    return [
        "### 今日导学单元",
        "### [同步] 记录",
        "### 掌握度评分（1-5分）",
        f"### {replica_name} 进度",
        "### AI 拷打评语",
        "### 推荐论文/文章阅读情况",
        "### 明日优先项",
    ]


SYNC_FIELDS = ["已掌握", "卡壳", "疑问", "代码完成"]


class MemoryStore:
    def __init__(self, config: ConfigService):
        self._dir: Path = config.docx_dir / "StudyMemory"
        self._replica: str = config.workspace.replica_name

    # ---- 文件定位 ----

    def path_for(self, day: int) -> Path:
        return self._dir / f"Day_{day:02d}.md"

    def exists(self, day: int) -> bool:
        return self.path_for(day).exists()

    def read(self, day: int) -> str:
        return self.path_for(day).read_text(encoding="utf-8")

    # ---- 生成 ----

    def render_new(self, date_str: str, units: list[dict],
                   paper: str | None = None) -> str:
        """units: [{"id": "A", "title": "..."}]"""
        lines = [f"## {date_str}", "", "### 今日导学单元"]
        for u in units:
            lines.append(f"- [ ] 单元{u['id']}：{u['title']}")
        lines += ["", "### [同步] 记录"]
        for f in SYNC_FIELDS:
            lines.append(f"- {f}：")
        lines += ["", "### 掌握度评分（1-5分）"]
        for u in units:
            lines.append(f"- 单元{u['id']}：")
        lines += [
            "", f"### {self._replica} 进度",
            "- 已完成模块：", "- 今日新增代码：", "- 待完成：",
            "", "### AI 拷打评语",
            "- 强项：", "- 风险点：", "- 建议：",
            "", "### 推荐论文/文章阅读情况",
        ]
        lines.append(f"- [ ] 论文：《{paper}》" if paper else "- 无")
        lines += ["", "### 明日优先项", "- 待生成", ""]
        return "\n".join(lines)

    # ---- 解析 ----

    @staticmethod
    def unit_checks(content: str) -> dict[str, bool]:
        """单元勾选状态：{"A": True/False}"""
        result = {}
        for line in content.splitlines():
            m = re.match(r"^\s*-\s*\[([ xX])\]\s*单元([A-Za-z0-9_]+)[:：]", line)
            if m:
                result[m.group(2)] = m.group(1).lower() == "x"
        return result

    @staticmethod
    def sync_counts(content: str) -> dict[str, int]:
        counts = {}
        in_sync = False
        for line in content.splitlines():
            if line.startswith("### [同步] 记录"):
                in_sync = True
                continue
            if in_sync and line.startswith("### "):
                break
            if in_sync:
                m = re.match(r"^-\s*(已掌握|卡壳|疑问|代码完成)[:：]\s*(.*)$", line)
                if m:
                    body = m.group(2).strip()
                    counts[m.group(1)] = (
                        0 if body in ("", "无") else len([x for x in re.split(r"[、，,]", body) if x.strip()])
                    )
        return counts

    # ---- 局部修改 ----

    @staticmethod
    def reset_for_restart(content: str) -> str:
        """「重新开始今日学习」：单元勾选重置为 [ ]，其余（[同步] 记录/评分/评语/备注）原样保留。

        数据保留规则见 SOP_开始今日学习.md FAIL-FAST 分支表。
        """
        return re.sub(r"^(\s*-\s*)\[[xX]\](\s*单元)", r"\g<1>[ ]\g<2>",
                      content, flags=re.MULTILINE)

    @staticmethod
    def set_unit_checked(content: str, unit_id: str, checked: bool,
                         note: str = "") -> str:
        out = []
        pattern = re.compile(
            rf"^(\s*-\s*)\[([ xX])\](\s*单元{re.escape(unit_id)}[:：].*?)(\s*（未掌握-跳过）)?$")
        for line in content.splitlines():
            m = pattern.match(line)
            if m:
                mark = "x" if checked else " "
                new_line = f"{m.group(1)}[{mark}]{m.group(3)}{note}"
                out.append(new_line)
            else:
                out.append(line)
        return "\n".join(out)

    @staticmethod
    def set_unit_score(content: str, unit_id: str, score: float) -> str:
        out = []
        in_scores = False
        pattern = re.compile(rf"^(\s*-\s*单元{re.escape(unit_id)}[:：])\s*.*$")
        for line in content.splitlines():
            if line.startswith("### 掌握度评分"):
                in_scores = True
            elif line.startswith("### "):
                in_scores = False
            if in_scores and pattern.match(line):
                out.append(f"{pattern.match(line).group(1)}{score}分")
            else:
                out.append(line)
        return "\n".join(out)

    @staticmethod
    def append_sync(content: str, field: str, value: str) -> str:
        if field not in SYNC_FIELDS:
            raise ValueError(f"未知 [同步] 字段: {field}")
        out = []
        in_sync = False
        pattern = re.compile(rf"^(-\s*{re.escape(field)}[:：])\s*(.*)$")
        for line in content.splitlines():
            if line.startswith("### [同步] 记录"):
                in_sync = True
            elif line.startswith("### "):
                in_sync = False
            m = pattern.match(line) if in_sync else None
            if m:
                body = m.group(2).strip()
                if body in ("", "无"):
                    out.append(f"{m.group(1)}{value}")
                else:
                    out.append(f"{m.group(1)}{body}、{value}")
            else:
                out.append(line)
        return "\n".join(out)

    @staticmethod
    def replace_section_body(content: str, header_prefix: str,
                             new_lines: list[str]) -> str:
        """整体替换某个 ### 小节的内容行（保留小节标题）。"""
        out = []
        in_section = False
        replaced = False
        for line in content.splitlines():
            if line.startswith("### "):
                if line.startswith(header_prefix):
                    in_section = True
                    out.append(line)
                    out.extend(new_lines)
                    replaced = True
                    continue
                in_section = False
            if not in_section:
                out.append(line)
        if not replaced:
            raise ValueError(f"小节不存在: {header_prefix}")
        return "\n".join(out)
