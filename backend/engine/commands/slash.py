"""Slash 系统指令（v1：/compact）：即发即执行的工具指令，不走教学回合。

与 [指令]（SOP 学习流程，registry.py）命名空间并存、互不干扰：
- 输入以 `/` 开头 → 本注册表；以 `[` 开头 → CommandRegistry
- handler 签名：(deps, session) -> str（Markdown 报告，路由层作为
  message 事件一次发出）；不写入 chat_history（系统操作不污染教学上下文）

新增指令：写一个 handler 函数 + 在 SLASH_COMMANDS 注册一行即可。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ...domain.models import SessionContext
from ..context_manager import ContextManager

# /compact 保留的最近原文消息数（2 问 2 答）
_KEEP_RECENT = 4


@dataclass(frozen=True)
class SlashCommand:
    name: str                                        # 不含斜杠，如 "compact"
    desc: str                                        # 补全菜单里的说明
    handler: Callable[[object, SessionContext], str]


def _compact(deps, session: SessionContext) -> str:
    """手动压缩：保留最近 4 条原文，其余归档为 AI 摘要。

    复用 ContextManager._compress（压缩机器不变，手动构造 plan），继承全部
    护栏：概念 ID/问题数机械校验、校验失败原文全保留、摘要 4000 字上限。
    手动指令绕过失败冷却（用户显式触发），但失败仍写冷却防自动路重试风暴。
    """
    history = session.chat_history
    upto = session.archive_upto
    if upto < 0 or upto > len(history):
        upto = 0  # 同 assemble 防御：越界从全量重算
    compress_upto = max(upto, len(history) - _KEEP_RECENT)
    # 窗口首条对齐 user：保持 user/assistant 成对，不拆问答
    while compress_upto > upto \
            and history[compress_upto].get("role") != "user":
        compress_upto -= 1
    if compress_upto <= upto:
        return ("上下文还很小，无需压缩"
                f"（未归档消息 {len(history) - upto} 条，"
                f"不足 {_KEEP_RECENT} 条保留线）。")
    cm = ContextManager(deps)
    plan = {"needs_compression": True,
            "compress_from": upto, "compress_upto": compress_upto}
    try:
        ok = cm._compress(session, plan)
    except Exception:
        ok = False  # 压缩是增强不是闸门：任何异常不炸指令（§8.4）
    if not ok:
        from ..context_manager import _safe_int
        session.compress_cooldown = _safe_int(
            cm._ctx().get("compress_fail_cooldown"), 3)
        return ("压缩失败：LLM 摘要未通过机械校验（概念 ID 不全或问题计数异常），"
                "原文已全部保留、未丢数据。可稍后重试。")
    archived = compress_upto - upto
    kept = len(history) - compress_upto
    return (f"**压缩完成**\n\n"
            f"- 归档 {archived} 条消息 → AI 摘要（{len(session.archive_summary)} 字）\n"
            f"- 窗口保留最近 {kept} 条原文\n"
            f"- 原文未删除（archive_upto 指针前移），上下文占比已回落")


SLASH_COMMANDS: list[SlashCommand] = [
    SlashCommand("compact", "压缩历史上下文（保留最近 2 轮原文）", _compact),
]

_REGISTRY: dict[str, SlashCommand] = {c.name: c for c in SLASH_COMMANDS}


def info_list() -> list[dict]:
    """供前端补全菜单渲染。"""
    return [{"name": c.name, "desc": c.desc} for c in SLASH_COMMANDS]


def execute(deps, session: SessionContext, text: str) -> str:
    """分发 slash 指令。text 为原始输入（含斜杠）。未知指令返回提示。"""
    parts = text.strip()[1:].split(None, 1)
    name = parts[0].lower() if parts else ""
    cmd = _REGISTRY.get(name)
    if not cmd:
        known = "、".join(f"/{c.name}" for c in SLASH_COMMANDS)
        return f"未知系统指令：`{text.strip()}`。可用指令：{known}"
    return cmd.handler(deps, session)
