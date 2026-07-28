"""Slash 系统指令（v2：/compact /clear /model /usage）：即发即执行的工具指令，不走教学回合。

与 [指令]（SOP 学习流程，registry.py）命名空间并存、互不干扰：
- 输入以 `/` 开头 → 本注册表；以 `[` 开头 → CommandRegistry
- handler 签名：(deps, session, args) -> {"report": str, "clear_screen": bool}
  - report：Markdown 报告，路由层作为 message 事件一次发出
  - clear_screen：True 时路由层先发 clear 事件让前端清屏（/clear 用）
  - handler=None 为客户端指令（/usage），前端本地打开面板、不发请求
- 指令与报告不写入 chat_history（系统操作不污染教学上下文）

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
    handler: Callable[[object, SessionContext, str], dict] | None = None

    @property
    def client(self) -> bool:
        return self.handler is None                  # 客户端指令（前端本地执行）


def _compact(deps, session: SessionContext, args: str) -> dict:
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
        return {"report": ("上下文还很小，无需压缩"
                           f"（未归档消息 {len(history) - upto} 条，"
                           f"不足 {_KEEP_RECENT} 条保留线）。")}
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
        return {"report": ("压缩失败：LLM 摘要未通过机械校验"
                           "（概念 ID 不全或问题计数异常），"
                           "原文已全部保留、未丢数据。可稍后重试。")}
    archived = compress_upto - upto
    kept = len(history) - compress_upto
    return {"report": (f"**压缩完成**\n\n"
                       f"- 归档 {archived} 条消息 → AI 摘要"
                       f"（{len(session.archive_summary)} 字）\n"
                       f"- 窗口保留最近 {kept} 条原文\n"
                       f"- 原文未删除（archive_upto 指针前移），上下文占比已回落")}


def _clear(deps, session: SessionContext, args: str) -> dict:
    """清空对话历史 + 归档层（同 /api/session/reset 语义），前端清屏。"""
    n = len(session.chat_history)
    session.chat_history = []
    session.archive_summary = ""
    session.archive_upto = 0
    session.compress_cooldown = 0
    return {"report": f"对话历史已清空（{n} 条）。学习进度数据未受影响。",
            "clear_screen": True}


def _model(deps, session: SessionContext, args: str) -> dict:
    """查看/快速切换 LLM 主渠道。备用渠道与预热设置不动；只重写 [llm] 节
    （子节区 [llm.xxx] 的参数与 .env 密钥不受影响，与配置弹窗保存同口径）。"""
    from ...llm.factory import _BUILDERS, create_llm, create_llm_cheap
    from ...services.config_writer import _esc, update_toml_sections
    cfg = deps.config
    cur = cfg.llm_config.get("provider", "mock")
    fb = cfg.llm_config.get("fallback_provider", "")
    avail = "、".join(f"`{n}`" for n in _BUILDERS)
    target = args.strip().split()[0] if args.strip() else ""
    if not target:
        return {"report": (
            f"**当前模型渠道**\n\n"
            f"- 主渠道：`{cur}`\n"
            f"- 备用渠道：{('`' + fb + '`') if fb else '（无）'}\n"
            f"- 可用渠道：{avail}\n\n"
            f"切换：`/model <渠道名>`；改参数/密钥：右上角 ⚙ 模型配置。")}
    if target not in _BUILDERS:
        return {"report": f"未知渠道 `{target}`。可用渠道：{avail}"}
    if target == cur:
        return {"report": f"主渠道已是 `{target}`，无需切换。"}
    lines = ["[llm]", f'provider = "{_esc(target)}"']
    if fb:
        lines.append(f'fallback_provider = "{_esc(fb)}"')
    lines.append("warmup_on_start = "
                 f"{'true' if cfg.llm_config.get('warmup_on_start') else 'false'}")
    try:
        update_toml_sections(cfg.path, {"llm": lines})
    except Exception as e:
        return {"report": f"切换失败：写入 settings.toml 出错（{e}），配置未变。"}
    cfg.reload()
    try:
        deps.llm = create_llm(cfg)
        deps.llm_cheap = create_llm_cheap(cfg) or deps.llm
        deps.quiz.set_llm(deps.llm)
    except Exception as e:
        return {"report": (
            f"已写入 `{target}`，但新渠道构建失败（{e}）。"
            f"运行态暂保留 `{cur}`——补齐 key 或重启后生效。")}
    return {"report": (f"**已切换主渠道**：`{cur}` → `{target}`"
                       f"（备用 {('`' + fb + '`') if fb else '无'} 不变）")}


SLASH_COMMANDS: list[SlashCommand] = [
    SlashCommand("compact", "压缩历史上下文（保留最近 2 轮原文）", _compact),
    SlashCommand("clear", "清空对话历史（不影响学习数据）", _clear),
    SlashCommand("model", "查看/切换模型渠道（/model <渠道名>）", _model),
    SlashCommand("usage", "打开 Token 用量面板"),  # 客户端指令
]

_REGISTRY: dict[str, SlashCommand] = {c.name: c for c in SLASH_COMMANDS}


def info_list() -> list[dict]:
    """供前端补全菜单渲染（client=True 的由前端本地执行）。"""
    return [{"name": c.name, "desc": c.desc, "client": c.client}
            for c in SLASH_COMMANDS]


def execute(deps, session: SessionContext, text: str) -> dict:
    """分发 slash 指令。text 为原始输入（含斜杠）。

    返回 {"report": str, "clear_screen": bool}。未知指令返回提示。"""
    parts = text.strip()[1:].split(None, 1)
    name = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    cmd = _REGISTRY.get(name)
    if not cmd:
        known = "、".join(f"/{c.name}" for c in SLASH_COMMANDS)
        return {"report": f"未知系统指令：`{text.strip()}`。可用指令：{known}"}
    if cmd.client:
        return {"report": f"`/{cmd.name}` 由客户端直接执行（打开对应面板），"
                          "请从界面操作。"}
    result = cmd.handler(deps, session, args)
    result.setdefault("clear_screen", False)
    return result
