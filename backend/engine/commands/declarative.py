"""声明式指令 handler：无代码逻辑的指令走此通用解释器。

配置中 handler = "declarative" 的指令：直接把用户输入 + SOP 卡交给 LLM 处理。
多数简单指令零代码即可接入（settings.toml 注册一行）。
"""

from __future__ import annotations

from ...domain.models import SessionContext
from .base import CommandHandler, CommandResult, Deps


class DeclarativeHandler(CommandHandler):
    name = "declarative"

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        return CommandResult(
            messages=[],
            llm_instruction=f"用户输入：{args}" if args else None)
