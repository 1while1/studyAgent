"""Study.md 中 Day N 计划大纲解析（服务层，零依赖其他 service）。"""

from __future__ import annotations

import re
from pathlib import Path

from .config_service import ConfigService


class StudyPlanError(Exception):
    pass


def parse_day_text(text: str, day: int, replica_name: str = "replica") -> dict:
    """解析文本中 `## Day N | ...` 小节。返回 {date, goal, units, code_goal, paper, qa_goal}。

    units: [{"id","title","doc","duration"}]。找不到小节抛 StudyPlanError。
    """
    m = re.search(rf"^## Day {day} \|\s*(.+)$", text, re.MULTILINE)
    if not m:
        raise StudyPlanError(
            f"Study.md 中未找到 '## Day {day} |' 详细小节")
    start = m.end()
    nxt = re.search(r"^## Day \d+ \|", text[start:], re.MULTILINE)
    section = text[start: start + nxt.start()] if nxt else text[start:]

    result = {"date": m.group(1).strip(), "goal": "", "units": [],
              "code_goal": "", "paper": "", "paper_sections": "",
              "qa_goal": ""}

    g = re.search(r"\*\*目标\*\*[:：]\s*(.+)", section)
    if g:
        result["goal"] = g.group(1).strip()
    for um in re.finditer(
            r"^\d+\.\s*\[[ xX]\]\s*单元([A-Za-z0-9_]+)[:：](.+?)（预计\s*(.+?)）",
            section, re.MULTILINE):
        unit = {"id": um.group(1), "title": um.group(2).strip(),
                "duration": um.group(3).strip(), "doc": ""}
        tail = section[um.end(): um.end() + 300]
        d = re.search(r"-\s*文档[:：]\s*(.+)", tail)
        if d:
            unit["doc"] = d.group(1).strip()
        result["units"].append(unit)
    c = re.search(r"\*\*编码目标\*\*[:：]\s*(.+)", section)
    if c:
        # 去掉与模板重复的前缀（模板含 "<replica_name> 完成 <模块>"）
        result["code_goal"] = re.sub(
            rf"^{re.escape(replica_name)}\s*完成\s*", "", c.group(1).strip())
    p = re.search(r"\*\*推荐论文\*\*[:：]\s*《(.+?)》(?:\s*—\s*重点读\s*(.+))?", section)
    if p:
        result["paper"] = p.group(1).strip()
        result["paper_sections"] = (p.group(2) or "").strip()
    q = re.search(r"\*\*面试话术目标\*\*[:：]\s*(.+)", section)
    if q:
        # 模板含 产出"<话题>"的 30 秒/2 分钟版回答，仅提取话题本体
        m = re.search(r'产出"(.+?)"的', q.group(1))
        result["qa_goal"] = m.group(1) if m else q.group(1).strip()
    return result


class StudyPlanStore:
    def __init__(self, config: ConfigService):
        self._path: Path = config.docx_dir / "Study.md"
        self._replica: str = config.workspace.replica_name

    def read(self) -> str:
        return self._path.read_text(encoding="utf-8")

    def parse_day(self, day: int) -> dict:
        """解析当前工作区 Study.md 的 `## Day N |` 小节。"""
        try:
            return parse_day_text(self.read(), day, self._replica)
        except StudyPlanError as e:
            raise StudyPlanError(
                f"{e}（该天通常由前一日 [结束今日学习] 自动滚动细化；"
                f"可重发 [结束今日学习] 触发重试，或手动细化 Study.md）") from e

    def replace_day_section(self, content: str, day: int,
                            new_section: str) -> str:
        """把 `## Day N |` 小节整体替换为 new_section；标题不存在则追加到文末。"""
        m = re.search(rf"^## Day {day} \|.*$", content, re.MULTILINE)
        if not m:
            return content.rstrip() + "\n\n" + new_section.strip() + "\n"
        nxt = re.search(r"^## Day \d+ \|", content[m.end():], re.MULTILINE)
        end = m.end() + nxt.start() if nxt else len(content)
        return (content[:m.start()] + new_section.strip() + "\n\n"
                + content[end:].lstrip("\n"))

    def mark_day_done(self, content: str, day: int) -> str:
        """Day N 标题加 ✅（幂等）。"""
        return re.sub(rf"^(## Day {day} \|[^\n✅]*?)\s*$",
                      r"\1 ✅", content, count=1, flags=re.MULTILINE)

    def update_header(self, content: str, current_day: int,
                      percentage: int) -> str:
        content = re.sub(r"当前天数：Day\s*\d+", f"当前天数：Day {current_day}",
                         content, count=1)
        content = re.sub(r"整体完成度：\d+(?:\.\d+)?%", f"整体完成度：{percentage}%",
                         content, count=1)
        return content
