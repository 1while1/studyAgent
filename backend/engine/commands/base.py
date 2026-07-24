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
    llm_cheap: LLMClient      # cheap 档（M5b：v1 仅上下文压缩用；无独立配置时 = llm）
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
        if not path.exists():
            return ""
        # 消费处占位替换（模板单源不动，铁律 1）：工作区名在 handler 读卡时注入
        ws = deps.config.workspace
        return (path.read_text(encoding="utf-8")
                .replace("<复现名>", ws.replica_name)
                .replace("<项目名>", ws.project_dir.name))

    @staticmethod
    def learner_with_concepts(deps: Deps):
        """学习者模型写入统一入口（M3）：同步 concepts + materials 挂接后返回服务。

        concepts 挂接材料需要 study_plan（doc tokens）与 materials_service
        （resolve_doc）编排——service 互不引用，故在此（engine 层）组装。
        """
        from ...domain.learner import concept_id
        from ...services.learner_service import LearnerService
        from ...services.materials_service import MaterialsService
        from ...services.study_plan import extract_doc_paths
        svc = LearnerService(deps.config)
        try:
            state = deps.state_store.load()
        except Exception:
            return svc
        ms = MaterialsService(deps.config)
        mats: dict[str, list[str]] = {}
        for day_key in state.get("days", {}):
            try:
                plan = deps.study_plan.parse_day(int(day_key))
            except Exception:
                continue  # 未细化天无 doc 信息，跳过不阻塞
            for u in plan.get("units", []):
                ids = []
                for token in extract_doc_paths(u.get("doc", "")):
                    try:
                        e = ms.resolve_doc(token)
                    except Exception:
                        e = None
                    if e:
                        ids.append(e["id"])
                if ids:
                    mats[concept_id(int(day_key), u["id"])] = ids
        svc.ensure_concepts(state, mats)
        return svc


def render_mastery_check(state_store, stages, templates, session,
                         preselect: str | None = "需巩固") -> str:
    """掌握情况检查渲染（InteractionModel §3 决策 2：两个触发源共用同一函数）。

    调用方：[下一内容] 命令（preselect="需巩固" 保守默认）与 orchestrator
    回合复习自动触发（preselect=None 选项原样，由用户自评）。
    只读渲染，不改动任何状态。
    """
    state = state_store.load()
    unit = next((u for u in state_store.day(state)["units"]
                 if u["id"] == session.current_unit_id), None)
    title = (unit or {}).get("title", "当前单元")
    done_stages = []
    names = stages.names()
    if session.current_stage in names:
        done_stages = names[: names.index(session.current_stage) + 1]
    check = (templates.get("mastery_check")
             .replace("<填入>", title, 1)
             .replace("<填入>",
                      "、".join(stages.sop_step(s) for s in done_stages)
                      or "见讲解记录", 1)
             .replace("<填入>", "见对话记录", 1))
    if preselect:
        check = check.replace("[已掌握 / 基本掌握 / 需巩固]", f"[{preselect}]")
    if any(s == "coding" for s in done_stages):
        check = check.replace("[已完成 / 进行中 / 未开始 / 不适用]", "[已完成]")
    return check
