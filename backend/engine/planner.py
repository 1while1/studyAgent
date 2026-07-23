"""PlannerEngine（M5c，AgentDesign §8.1/§8.2）：agent 模式的回合引擎。

plan-act-observe 在单个流式回合内完成：本引擎只在附加指令中给出 ACTION
契约与工具清单；LLM 输出的 [ACTION:{...}] 标记由 ToolUseLoop 截获，经
tool_registry 执行并注入结果续写。动作边界是契约（{action,args,reason}），
测试断言动作序列，不断言自由文本（§8.2 硬规）。

纪律：阶段机不介入 agent 会话；StudyState 写入只能经 persist_state 工具
白名单间接写（§8.2）；确定性指令永不过 planner（§8.1，command 路由 guard）。
"""

from __future__ import annotations

from ..domain.models import SessionContext
from .tool_registry import build_default_registry
from .turn_engine import TurnEngine

_CONTRACT = (
    "你可以通过 ACTION 标记调用工具获取真实数据或执行动作。契约：\n"
    "- 格式：[ACTION:{\"action\":\"工具名\",\"args\":{...},"
    "\"reason\":\"一句话理由\"}]\n"
    "- 必须独立一行输出，禁止反引号包裹；输出标记后立即停止该段回复，"
    "系统会执行工具并把结果注入给你继续。\n"
    "- 禁止编造工具执行结果；工具失败时按注入的错误修正或如实告知。\n"
    "- 可用工具：\n")


class PlannerEngine(TurnEngine):
    """agent 模式引擎：ACTION 契约 + 工具清单注入。"""

    def __init__(self, deps):
        self._deps = deps

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        lines = []
        for s in build_default_registry().schemas("marker"):
            params = ",".join(s["params"].get("properties", {}).keys()) or "无"
            lines.append(f"  - {s['name']}（{s['permission']}，"
                         f"参数：{params}）：{s['description']}")
        return _CONTRACT + "\n".join(lines)

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        return []  # action 已在流内执行；阶段机不介入 agent 会话
