"""指令 handler 接口与依赖容器。

每个 SOP 卡对应一个 handler 文件，实现 CommandHandler；handler 之间禁止互相 import。
新增指令：写一个 handler + 在 settings.toml [commands] 注册。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ...domain.models import SessionContext
from ...engine.hooks.pipeline import HookPipeline
from ...engine.prompt_builder import PromptBuilder
from ...engine.quiz_engine import QuizEngine
from ...engine.session_store import SessionStore
from ...engine.stage_machine import StageMachine
from ...llm.base import LLMClient
from ...services.backup_service import BackupService
from ...services.config_service import ConfigService
from ...services.memory_store import MemoryStore
from ...services.state_store import StateStore
from ...services.study_plan import StudyPlanStore
from ...services.template_service import TemplateService


@dataclass
class Deps:
    """handler 可用依赖（由 api 层组装注入）。"""
    config: ConfigService
    state_store: StateStore
    memory: MemoryStore
    study_plan: StudyPlanStore
    templates: TemplateService
    backup: BackupService
    stages: StageMachine
    llm: LLMClient
    quiz: QuizEngine
    prompts: PromptBuilder
    hooks: HookPipeline
    session_store: SessionStore

    def validator(self):
        from ...engine.hooks.validate_hook import make_validator
        return make_validator(self.config)


@dataclass
class CommandResult:
    """handler 执行结果。

    messages: 直接渲染给用户的消息块（模板输出，按顺序展示）
    llm_instruction: 若非 None，API 层随后以此调用 LLM 流式生成后续内容
    """
    messages: list[str] = field(default_factory=list)
    llm_instruction: str | None = None
    sop_card: str | None = None   # None=用注册表配置的卡；""=明确不携带；其余=指定卡文件名


class CommandHandler(ABC):
    name: str = ""

    @abstractmethod
    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        """返回 None = 通过；返回字符串 = STOP 消息（直接展示给用户，流程终止）。"""

    @abstractmethod
    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        """执行主流程。实现内负责 session 修改 + session_store.save。"""

    # ---- 共用工具 ----

    @staticmethod
    def read_sop_card(deps: Deps, filename: str) -> str:
        from ...services.config_service import SOP_DIR
        path = SOP_DIR / filename
        return path.read_text(encoding="utf-8") if path.exists() else ""
