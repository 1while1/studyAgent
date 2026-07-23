"""QuizEngine：掌握度考核（unit_gate）与复盘拷打（day_review）共用引擎。

职责：评分标记提取、FAIL-FAST 重试、及格判定。出题/点评内容由 LLM 生成。
"""

from __future__ import annotations

import re

from ..domain.enums import QuizMode
from ..llm.base import LLMClient, Message
from ..services.config_service import ConfigService

SCORE_RE = re.compile(
    r"\*{0,2}\s*【\s*评分\s*[:：]\s*(\d+(?:\.\d+)?)\s*分?\s*】\s*\*{0,2}")


class QuizEngine:
    def __init__(self, config: ConfigService, llm: LLMClient):
        self._pass_score = float(config.get("mastery_pass_score", 3.0))
        self._min_questions = int(config.get("review_min_questions", 8))
        self._llm = llm

    def set_llm(self, llm: LLMClient) -> None:
        """运行时切换 LLM 客户端（模型配置页面保存后调用）。"""
        self._llm = llm

    @staticmethod
    def extract_score(text: str) -> float | None:
        m = SCORE_RE.search(text)
        if not m:
            return None
        score = float(m.group(1))
        return score if 1.0 <= score <= 5.0 else None  # 超出契约范围视为无效标记

    @staticmethod
    def extract_scores_by_cid(text: str, cids: list[str]) -> dict[str, float | None]:
        """逐 concept 提取 `DayN-X：【评分：X.X】`（M7 先修诊断）。

        返回 {cid: score|None}——缺失或越界（铁律 6：1.0-5.0 契约）均为 None。
        """
        out: dict[str, float | None] = {}
        for cid in cids:
            m = re.search(
                # cid 后不得紧跟单元字符（F2 修复：防 "Day5-A" 窃取
                # "Day5-AA" 的评分行——单元 id 字符集 [A-Za-z0-9_]）
                rf"{re.escape(cid)}(?![A-Za-z0-9_])[^\n【]{{0,6}}?"
                r"【\s*评分\s*[:：]\s*(\d+(?:\.\d+)?)\s*分?\s*】",
                text)
            if not m:
                out[cid] = None
                continue
            score = float(m.group(1))
            out[cid] = score if 1.0 <= score <= 5.0 else None
        return out

    def ask_and_score(self, messages: list[Message], max_retries: int = 1
                      ) -> tuple[str, float | None]:
        """请求 LLM 评价并提取【评分：X.X】。无标记则追加提醒重试，仍无 → None（不推进）。"""
        attempts = max_retries + 1
        history = list(messages)
        for attempt in range(attempts):
            response = self._llm.chat(history)
            score = self.extract_score(response)
            if score is not None:
                return response, score
            history = history + [
                {"role": "assistant", "content": response},
                {"role": "user", "content":
                    "你的回复缺少评分标记。请补充输出终期评分，格式严格为【评分：X.X】（1.0-5.0）。"},
            ]
        return response, None

    def is_pass(self, score: float, mode: QuizMode = QuizMode.UNIT_GATE) -> bool:
        return score >= self._pass_score

    @property
    def min_review_questions(self) -> int:
        return self._min_questions
