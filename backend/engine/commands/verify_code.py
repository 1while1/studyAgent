"""[验证代码]：在验证根执行构建/测试，结果回喂 AI 点评（P1-1 编码验证闭环）。

验证根：replica 目录（WEB_ROOT 同级 / workspace.replica_name）存在则用之，
否则退回当前工作区的 project_dir。命令模板固定，超时/离线走 settings。
"""

from __future__ import annotations

from ...domain.models import SessionContext
from ...services import code_runner
from ...services.config_service import WEB_ROOT
from .base import CommandHandler, CommandResult, Deps


class VerifyCodeHandler(CommandHandler):
    name = "verify_code"

    @staticmethod
    def verify_root(deps: Deps):
        ws = deps.config.workspace
        replica = WEB_ROOT.parent / ws.replica_name if ws.replica_name else None
        if replica and replica.is_dir():
            return replica
        return ws.project_dir

    def fail_fast(self, deps: Deps, session: SessionContext,
                  args: str, mode: str = "") -> str | None:
        if not deps.state_store.exists():
            return "还没初始化学习数据，请先 [开始今日学习]。"
        root = self.verify_root(deps)
        if not code_runner.detect_build_tool(root):
            return (f"验证根 `{root}` 未发现构建文件（pom.xml / build.gradle / "
                    f"package.json）。当前仅支持 Maven/Gradle/npm 项目。")
        return None

    def run(self, deps: Deps, session: SessionContext,
            args: str, mode: str = "") -> CommandResult:
        root = self.verify_root(deps)
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
            f"刚在验证根 {root} 执行了 `{result['cmd']}`（{kind_label}），"
            f"退出码 {result['code']}，耗时 {result['seconds']}s。"
            f"输出尾部如下：\n```\n{result['tail'] or '（无输出）'}\n```\n"
            "请点评：失败时逐条解释错误含义并给出具体修复方向（引用真实类名/文件）；"
            "成功时给予肯定，指出下一步可验证的点，并追问一个相关设计问题。")
        return CommandResult(messages=[summary], llm_instruction=instruction,
                             sop_card="")
