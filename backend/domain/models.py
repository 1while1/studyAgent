"""纯领域模型：零 IO、零 LLM 依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
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
    archive_summary: str = ""         # 归档层：历史压缩摘要（有损缓存，M5b）
    archive_upto: int = 0             # 归档层：摘要覆盖到的 chat_history 下标
    compress_cooldown: int = 0        # 压缩失败冷却回合数（R2：防失败重试风暴）
    interview_cid: str = ""           # 模拟面试知识点 concept id（M5c；空=非面试中）
    interview_round: int = 0          # 面试回合（0=待口述评估，1/2=追问回合）
    interview_score: float | None = None  # 面试口述分（独立于 quiz pending_score，R4）
    prereq_targets: list | None = None   # 先修诊断目标 [{cid,title,question}]（M7；空/None=非诊断中）
    prereq_retry: int = 0                # 诊断评分机械校验已重试次数
    chat_history: list[dict] = field(default_factory=list)  # [{role, content}]
    # ---- 上下文账本（M8 上下文仪表）：最近一轮 API 实测 usage ----
    ctx_prompt_tokens: int = 0        # 最近实测轮 prompt_tokens（system+历史+用户消息）
    ctx_completion_tokens: int = 0    # 最近实测轮 completion_tokens（回复已入历史）
    ctx_measured: bool = False        # 最近一轮是否有真实 usage（网关降级轮=False→估算）
    # 校准系数（实测 prompt / 本地估算 prompt）：仪表显示 = 当前装配估算 × 系数。
    # 同一会话状态下刷新/重启显示稳定；0 = 从未实测过（纯估算口径）
    ctx_calib: float = 0.0
    # ---- M1.2 教学行动策略 ----
    pending_teaching_suggestion: Optional[dict] = None  # 教学建议（to_dict 序列化）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionContext":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
