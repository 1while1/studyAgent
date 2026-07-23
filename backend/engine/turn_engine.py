"""turn_engine 接口（M5a，AgentDesign §8.2）：双系统并存的关键。

- `TurnEngine`：聊天回合引擎接口（instruction_for + post_process 两方法）。
  现有 ChatOrchestrator 为第一个实现（导学模式），PlannerEngine 为第二个
  （agent 模式，M5c 填充，此处仅占位 stub）。
- 路由按 `session.mode` + feature flag（`agent_mode_enabled`）二选一，
  同一 session 不混跑；stage machine 继续独占 StudyState 写入，planner
  未来只能经 persist_state 工具间接写。
- 旧指令在 agent 会话返回固定提示 `AGENT_COMMAND_HINT`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.models import SessionContext

# agent 会话中收到旧导学指令时的固定提示（§8.2 硬规）
AGENT_COMMAND_HINT = "该指令请在导学模式使用。"


class TurnEngine(ABC):
    """聊天回合引擎：生成 LLM 附加指令 + LLM 回复后的状态处理。"""

    @abstractmethod
    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        """生成本次回复的附加指令（无附加指令返回空串）。"""

    @abstractmethod
    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        """LLM 回复完成后的状态处理。返回需要追加展示给用户的消息块。"""


class PlannerEngine(TurnEngine):
    """agent 模式引擎（M5c 实现 plan-act-observe；M5a 仅占位）。

    默认不可达：`agent_mode_enabled` 默认关闭且 session.mode 默认 study。
    """

    def instruction_for(self, session: SessionContext, user_text: str) -> str:
        return ("（系统：agent 模式建设中，当前版本仅支持导学模式；"
                "请正常提问或切换回导学流程。）")

    def post_process(self, session: SessionContext, assistant_text: str
                     ) -> list[str]:
        return []


def build_turn_engine(session: SessionContext, deps, tutor: TurnEngine
                      ) -> TurnEngine:
    """按 session.mode + feature flag 选择引擎（同一 session 确定性不混跑）。

    tutor：调用方已构建的导学引擎单例（ChatOrchestrator）。
    """
    if (getattr(session, "mode", "study") == "code"
            and deps.config.get("agent_mode_enabled", False)):
        return PlannerEngine()
    return tutor
