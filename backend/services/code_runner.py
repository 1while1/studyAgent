"""代码构建/测试执行器：限时的只读子进程调用（编码验证闭环 P1-1）。

安全边界：
- 仅识别已知构建工具（maven/gradle/npm），命令为固定模板，不拼接用户输入
- cwd 限定验证根（replica 目录或项目目录），超时强杀
- verify_offline=true 时 maven 加 -o（禁网络，需依赖已缓存）
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

TAIL_CHARS = 4000  # 回喂 LLM 的日志尾部上限


def detect_build_tool(root: Path) -> str | None:
    if (root / "pom.xml").is_file():
        return "maven"
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        return "gradle"
    if (root / "package.json").is_file():
        return "npm"
    return None


def _mvn_bin() -> str:
    for name in ("mvn", "mvn.cmd", "mvn.bat"):
        hit = shutil.which(name)
        if hit:
            return hit
    raise FileNotFoundError("未找到 mvn 可执行文件（PATH 中无 Maven）")


def build_command(tool: str, kind: str, offline: bool = False) -> list[str]:
    """固定命令模板，kind: compile | test。"""
    if tool == "maven":
        mvn = _mvn_bin()
        if kind == "test":
            cmd = [mvn, "-q", "test"]
        else:
            cmd = [mvn, "-q", "-DskipTests", "compile"]
        if offline:
            cmd.insert(1, "-o")
        return cmd
    if tool == "gradle":
        gradle = shutil.which("gradle") or "gradle"
        return [gradle, "test" if kind == "test" else "compileJava", "-q"]
    if tool == "npm":
        npm = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
        return [npm, "test"] if kind == "test" else [npm, "run", "build"]
    raise ValueError(f"未知构建工具: {tool}")


def run_build(root: Path, tool: str, kind: str = "compile",
              timeout: int = 300, offline: bool = False) -> dict:
    """执行构建/测试。返回 {cmd, code, tail, seconds, timed_out}。"""
    cmd = build_command(tool, kind, offline)
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
        output = (proc.stdout or "") + (proc.stderr or "")
        return {"cmd": " ".join(cmd), "code": proc.returncode,
                "tail": output[-TAIL_CHARS:], "seconds": round(time.time() - started, 1),
                "timed_out": False}
    except subprocess.TimeoutExpired as e:
        output = ((e.stdout or "") + (e.stderr or ""))
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {"cmd": " ".join(cmd), "code": -1,
                "tail": output[-TAIL_CHARS:] + f"\n（超过 {timeout}s 被强杀）",
                "seconds": round(time.time() - started, 1), "timed_out": True}
