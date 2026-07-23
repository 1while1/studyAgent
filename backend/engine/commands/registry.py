"""指令注册表：触发词 → handler。声明式配置与代码 handler 混合挂载。

新增指令两条路：
1. settings.toml [commands."新指令"] handler = "declarative"（零代码）
2. 在 commands/ 下写 handler 文件 + 在此 _CODE_HANDLERS 注册
"""

from __future__ import annotations

from ...services.config_service import ConfigService
from .base import CommandHandler
from .code_mode import CodeModeHandler
from .day_review import DayReviewHandler
from .declarative import DeclarativeHandler
from .end_day import EndDayHandler
from .interview import InterviewHandler
from .jump_day import JumpDayHandler
from .next_content import NextContentHandler
from .prereq import PrereqHandler
from .resume import ResumeHandler
from .start_day import StartDayHandler
from .sync import SyncHandler
from .verify_code import VerifyCodeHandler

_CODE_HANDLERS: dict[str, type[CommandHandler]] = {
    "start_day": StartDayHandler,
    "resume": ResumeHandler,
    "next_content": NextContentHandler,
    "sync": SyncHandler,
    "code_mode": CodeModeHandler,
    "day_review": DayReviewHandler,
    "end_day": EndDayHandler,
    "jump_day": JumpDayHandler,
    "verify_code": VerifyCodeHandler,
    "interview": InterviewHandler,
    "prereq": PrereqHandler,
    "declarative": DeclarativeHandler,
}


def register_handler(name: str, cls: type[CommandHandler]) -> None:
    _CODE_HANDLERS[name] = cls


# 纯文本别名：FAIL-FAST 双选项等场景要求用户回复的无括号短语
_ALIASES = {
    "重新开始今日学习": "开始今日学习",
    "重新开始": "开始今日学习",
    "恢复学习": "恢复学习",
}


class CommandRegistry:
    def __init__(self, config: ConfigService):
        self._entries: dict[str, dict] = {}
        for trigger, entry in config.commands.items():
            handler_name = entry.get("handler", "declarative")
            if handler_name not in _CODE_HANDLERS:
                raise RuntimeError(f"指令 [{trigger}] 注册了未知 handler: {handler_name}")
            self._entries[trigger] = {
                "handler": _CODE_HANDLERS[handler_name](),
                "sop_card": entry.get("sop_card", ""),
                "mode": entry.get("mode", ""),
            }

    def triggers(self) -> list[str]:
        return list(self._entries)

    def match(self, text: str) -> tuple[dict, str] | None:
        """匹配用户输入中的 [指令] 或纯文本别名。返回 (entry, args) 或 None。"""
        stripped = text.strip()
        for alias, trigger in _ALIASES.items():
            if stripped == alias or stripped == f"[{alias}]":
                entry = self._entries.get(trigger)
                if entry:
                    return entry, alias
        for trigger, entry in self._entries.items():
            token = f"[{trigger}]"
            if token in text:
                args = text.split(token, 1)[1].strip()
                return entry, args
        return None

    def info_list(self) -> list[dict]:
        """供前端动态渲染指令按钮。"""
        return [{"trigger": t, "sop_card": e["sop_card"], "mode": e["mode"]}
                for t, e in self._entries.items()]
