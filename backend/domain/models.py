"""纯领域模型：零 IO、零 LLM 依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from .enums import DayPhase


@dataclass
class UnitState:
    id: str
    title: str
    status: str = "not_started"   # 取值集合由 settings.toml status_enum 定义
    rating: float = 0.0
    ahead: bool = False


@dataclass
class SessionContext:
    """运行时会话上下文（持久化到 study-web/runtime/session.json，与 docx 状态分离）。"""
    day_phase: str = DayPhase.NOT_STARTED.value
    current_unit_id: str | None = None
    current_stage: str = ""           # 取 settings.toml stages 的 name
    round_count: int = 0              # 当前单元内对话轮次（回合复习用）
    quiz_round: int = 0               # 掌握度考核进行到的回合（0/1/2）
    pending_score: float | None = None  # LLM 已给出但未确认落盘的评分
    force_skip: bool = False          # 本单元走强制跳过分支
    review_question_count: int = 0    # 今日复盘已问题数
    review_msg_start: int = 0         # 复盘开始的 chat_history 下标（拷打反喂转录切片）
    pending_qa_capture: bool = False  # 复盘评分落盘后待执行的拷打反喂标记
    mode: str = "study"               # 会话级 agent 模式（study|code，M5a 引入；引擎路由依据）
    chat_history: list[dict] = field(default_factory=list)  # [{role, content}]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionContext":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
