"""模板服务：从内置 resources/sop/*.md 的 <!-- template:name --> 锚点提取必输模板。

模板唯一事实源 = SOP 卡片（锚点块内原文）。改 SOP 卡 = 改程序行为。
渲染 = 仅做 <占位符> 文本替换（对应规则 10：模板字面锁定，仅占位符可替换）。
"""

from __future__ import annotations

import re
from pathlib import Path

from .config_service import ConfigService, SOP_DIR

_ANCHOR_RE = re.compile(
    r"<!-- template:(\w+) -->\s*\n(.*?)<!-- /template:\1 -->",
    re.DOTALL,
)


class TemplateError(Exception):
    pass


def _strip_fence(block: str) -> str:
    """去掉包裹模板的 ``` 文档围栏（卡片排版用，不属于模板内容）。"""
    text = block.strip("\n")
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


class TemplateService:
    def __init__(self, config: ConfigService):
        self._sop_dir: Path = SOP_DIR
        self._templates: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._templates = {}
        for md in sorted(self._sop_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            for name, block in _ANCHOR_RE.findall(text):
                body = _strip_fence(block)
                if name in self._templates and self._templates[name] != body:
                    raise TemplateError(
                        f"模板 {name} 在多个文件中定义且内容不一致（{md.name}）")
                self._templates[name] = body

    def names(self) -> list[str]:
        return sorted(self._templates)

    def get(self, name: str) -> str:
        if name not in self._templates:
            raise TemplateError(
                f"模板 {name} 不存在（可用: {', '.join(self.names())}）")
        return self._templates[name]

    def render(self, name: str, **placeholders: str) -> str:
        """仅替换 <占位符>；未提供的占位符原样保留。"""
        text = self.get(name)
        for key, value in placeholders.items():
            text = text.replace(f"<{key}>", str(value))
        return text
