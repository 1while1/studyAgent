"""通用阶段机解释器：stages/transitions 全部来自 settings.toml，代码不含 stage 字面量。

约定（文档化于 InteractionModel.md）：
- name 以 "quiz_" 开头的阶段 = 掌握度考核回合（QuizEngine 接管）
- next 为空串的阶段 = 终态
"""

from __future__ import annotations

from ..services.config_service import ConfigService


class StageError(Exception):
    pass


class StageMachine:
    def __init__(self, config: ConfigService):
        self._stages = config.stages
        if not self._stages:
            raise StageError("settings.toml 未定义 [[stages]]")
        self._by_name = {s["name"]: s for s in self._stages}
        if len(self._by_name) != len(self._stages):
            raise StageError("stages 存在重名")
        for s in self._stages:
            nxt = s.get("next", "")
            if nxt and nxt not in self._by_name:
                raise StageError(f"stage {s['name']} 的 next 指向未定义阶段: {nxt}")

    @property
    def first(self) -> str:
        return self._stages[0]["name"]

    @property
    def terminal(self) -> str:
        for s in self._stages:
            if not s.get("next"):
                return s["name"]
        raise StageError("未找到终态阶段（next 为空）")

    def names(self) -> list[str]:
        return [s["name"] for s in self._stages]

    def exists(self, name: str) -> bool:
        return name in self._by_name

    def info(self, name: str) -> dict:
        if name not in self._by_name:
            raise StageError(f"未知阶段: {name}")
        return self._by_name[name]

    def next_of(self, name: str) -> str | None:
        nxt = self.info(name).get("next", "")
        return nxt or None

    def advance(self, name: str) -> str:
        nxt = self.next_of(name)
        if nxt is None:
            raise StageError(f"阶段 {name} 已是终态，无法推进")
        return nxt

    @staticmethod
    def is_quiz(name: str) -> bool:
        return name.startswith("quiz_")

    def quiz_stages(self) -> list[str]:
        return [n for n in self.names() if self.is_quiz(n)]

    def instruction(self, name: str) -> str:
        return self.info(name).get("instruction", "")

    def sop_step(self, name: str) -> str:
        return self.info(name).get("sop_step", "")
