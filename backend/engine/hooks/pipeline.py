"""落盘钩子链（注册式）。新增校验/通知规则：register_post_persist 一个函数即可。"""

from __future__ import annotations

from typing import Callable

PostPersistHook = Callable[[], tuple[bool, str]]


class HookPipeline:
    def __init__(self):
        self._post_persist: list[tuple[str, PostPersistHook]] = []

    def register_post_persist(self, name: str, hook: PostPersistHook) -> None:
        self._post_persist.append((name, hook))

    def run_post_persist(self) -> tuple[bool, str]:
        outputs = []
        ok_all = True
        for name, hook in self._post_persist:
            ok, output = hook()
            outputs.append(f"[{name}] {output}")
            if not ok:
                ok_all = False
        return ok_all, "\n".join(outputs)
