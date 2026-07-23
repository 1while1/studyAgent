"""领域枚举。单元 stage 名由 settings.toml 数据驱动，不在此定义。"""

from enum import Enum


class DayPhase(str, Enum):
    NOT_STARTED = "not_started"    # 当日未开始
    PLANNING = "planning"          # 开始今日学习 4 步进行中
    STUDYING = "studying"          # 导学中
    REVIEWING = "reviewing"        # 今日复盘拷打中
    INTERVIEW = "interviewing"     # 模拟面试中（M5c）
    PREREQ = "prereq_diagnosing"   # 先修诊断中（M7）
    ENDED = "ended"                # 已结束


class QuizMode(str, Enum):
    UNIT_GATE = "unit_gate"        # 单元掌握度考核（2 回合）
    DAY_REVIEW = "day_review"      # 今日复盘拷打（≥配置题量）
