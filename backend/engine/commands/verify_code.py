"""[验证代码]：在验证根执行构建/测试，结果回喂 AI 点评（P1-1 编码验证闭环）。

验证根解析（code_runner.resolve_verify_root）：replica 目录（WEB_ROOT 同级 /
workspace.replica_name）存在则在其内找，否则退回 project_dir；根目录无构建
文件时识别一级子目录（如 replica/day02 按日模块），优先级：args 点名 >
当日 dayNN > 唯一候选。命令模板固定，超时/离线走 settings。
"""

from __future__ import annotations

from ...domain.models import SessionContext
from ...services import code_runner
from ...services.config_service import WEB_ROOT
from .base import CommandHandler, CommandResult, Deps


class VerifyCodeHandler(CommandHandler):
    name = "verify_code"

    @staticmethod
    def _resolve(deps: Deps, args: str):
        state = deps.state_store.load()
        day = state.get("current_day", 1)
        ws = deps.config.workspace
        return code_runner.resolve_verify_root(
            WEB_ROOT.parent, ws.replica_name, ws.project_dir, day, args)

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "还没初始化学习数据，请先 [开始今日学习]。"
        chosen, candidates, root = self._resolve(deps, args)
        if chosen is None:
            if candidates:
                names = "、".join(c.name for c in candidates)
                return (f"发现多个可验证目录（{names}），请指明一个，"
                        f"如：[验证代码] {candidates[0].name}")
            return (f"验证根 `{root}` 及其一级子目录均未发现构建文件"
                    "（pom.xml / build.gradle / package.json）。"
                    "当前仅支持 Maven/Gradle/npm 项目；"
                    "按日编码的 replica 项目请先为当日模块生成构建文件。")
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        root, _, _ = self._resolve(deps, args)
        tool = code_runner.detect_build_tool(root)
        kind = "test" if "测试" in args else "compile"
        timeout = int(deps.config.get("verify_timeout", 300))
        offline = bool(deps.config.get("verify_offline", False))
        try:
            result = code_runner.run_build(root, tool, kind=kind,
                                           timeout=timeout, offline=offline)
        except FileNotFoundError as e:
            return CommandResult(messages=[f"无法执行构建：{e}"])
        kind_label = "测试" if kind == "test" else "编译"
        status = "✅ 成功" if result["code"] == 0 else f"❌ 失败（退出码 {result['code']}）"
        summary = (f"已在 `{root}` 执行 {kind_label}验证：\n"
                   f"- 命令：`{result['cmd']}`\n"
                   f"- 结果：{status}（耗时 {result['seconds']}s）")
        instruction = (
            "【系统任务：构建结果点评】本次回复的唯一任务是点评构建输出，"
            "与当前学习阶段无关，忽略阶段指令中的其他教学要求，点评完即止。\n"
            f"刚在验证根 {root} 执行了 `{result['cmd']}`（{kind_label}），"
            f"退出码 {result['code']}，耗时 {result['seconds']}s。"
            f"输出尾部如下：\n```\n{result['tail'] or '（无输出）'}\n```\n"
            "失败时逐条解释错误含义并给出具体修复方向（引用真实类名/文件）；"
            "成功时给予肯定，指出下一步可验证的点，并追问一个相关设计问题。")
        return CommandResult(messages=[summary], llm_instruction=instruction,
                             sop_card="")
