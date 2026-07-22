"""StudyState.json 读写（单一事实源）。

只负责 JSON 层面的读写与枚举校验；落盘编排（备份→写→校验→回滚）见 backup_service。
"""

from __future__ import annotations

import json
from pathlib import Path

from .config_service import ConfigService


class StateStoreError(Exception):
    pass


class StateStore:
    def __init__(self, config: ConfigService):
        self._config = config
        self.path: Path = config.docx_dir / "StudyState.json"

    # ---- 读 ----

    def load(self) -> dict:
        if not self.path.exists():
            raise StateStoreError(f"StudyState.json 不存在: {self.path}")
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise StateStoreError(f"StudyState.json 解析失败: {e}") from e

    def exists(self) -> bool:
        return self.path.exists()

    # ---- 写（仅内存对象 → 字符串，真正落盘走 backup_service.atomic_persist） ----

    def dump(self, state: dict) -> str:
        self._validate(state)
        return json.dumps(state, ensure_ascii=False, indent=2) + "\n"

    def _validate(self, state: dict) -> None:
        allowed = set(self._config.get("status_enum", []))
        current_day = state.get("current_day")
        if not isinstance(current_day, int):
            raise StateStoreError(f"current_day 非法: {current_day!r}")
        for day_key, day_data in state.get("days", {}).items():
            for unit in day_data.get("units", []):
                status = unit.get("status")
                if status not in allowed:
                    raise StateStoreError(
                        f"Day {day_key} 单元 {unit.get('id')}: 非法状态 {status!r}")

    # ---- 领域操作（在 load 出的 dict 上工作，返回修改后的 dict） ----

    @staticmethod
    def day(state: dict, day: int | None = None) -> dict:
        day = day or state["current_day"]
        return state["days"][str(day)]

    def ensure_day(self, state: dict, day: int) -> dict:
        key = str(day)
        if key not in state["days"]:
            state["days"][key] = {
                "date": "",
                "units": [],
                "sync_records": {"mastered": [], "stuck": [], "questions": [],
                                 "code_completed": []},
                "review_completed": False,
                "review_score": 0.0,
            }
        return state["days"][key]

    def set_unit(self, state: dict, unit_id: str, *, status: str | None = None,
                 rating: float | None = None, day: int | None = None) -> dict:
        for unit in self.day(state, day)["units"]:
            if unit["id"] == unit_id:
                if status is not None:
                    unit["status"] = status
                if rating is not None:
                    unit["rating"] = rating
                return unit
        raise StateStoreError(f"单元 {unit_id} 不存在于 Day {day or state['current_day']}")

    def add_sync_record(self, state: dict, subtype: str, content: str,
                        day: int | None = None) -> None:
        records = self.day(state, day).setdefault("sync_records", {})
        records.setdefault(subtype, []).append(content)

    def recompute_percentage(self, state: dict) -> None:
        total = self._config.workspace.total_days
        completed = sum(
            1 for d in state["days"].values()
            if d.get("review_completed") or d.get("active_day_completed")
        )
        state["overall_completion_percentage"] = round(completed * 100 / total)
