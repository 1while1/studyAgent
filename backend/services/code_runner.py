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

import psutil

TAIL_CHARS = 4000  # 回喂 LLM 的日志尾部上限
_STOP_GRACE = 3.0  # terminate 后等待再 kill 的宽限（秒）


def detect_build_tool(root: Path) -> str | None:
    if (root / "pom.xml").is_file():
        return "maven"
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        return "gradle"
    if (root / "package.json").is_file():
        return "npm"
    return None


def find_build_candidates(root: Path) -> list[Path]:
    """验证根候选：root 本身或其一级子目录中含构建文件的目录（按名称排序）。"""
    candidates = []
    if root.is_dir() and detect_build_tool(root):
        candidates.append(root)
    if root.is_dir():
        for child in sorted(root.iterdir(), key=lambda c: c.name.lower()):
            if child.is_dir() and not child.name.startswith(".") \
                    and detect_build_tool(child):
                candidates.append(child)
    return candidates


def resolve_verify_root(base_dir: Path, replica_name: str, project_dir: Path,
                        day: int, args: str = ""
                        ) -> tuple[Path | None, list[Path], Path]:
    """选出实际验证根。返回 (选中目录或 None, 候选列表, 搜索根)。

    优先级：args 中点名的子目录 > 当日目录 day<NN>/day<N> > 唯一候选 > None。
    """
    root = base_dir / replica_name if replica_name else project_dir
    if not root.is_dir():
        root = project_dir
    candidates = find_build_candidates(root)
    if not candidates:
        return None, [], root
    for token in args.split():
        for c in candidates:
            if c.name == token:
                return c, candidates, root
    day_names = {f"day{day:02d}", f"day{day}"}
    for c in candidates:
        if c.name.lower() in day_names:
            return c, candidates, root
    if detect_build_tool(root):
        return root, candidates, root  # 根有构建文件 = 多模块项目，从根构建
    if len(candidates) == 1:
        return candidates[0], candidates, root
    return None, candidates, root


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


def _kill_tree(proc: subprocess.Popen) -> None:
    """超时杀进程树（children 递归 + self，terminate → 宽限 → kill 残余）。

    与 process_mgr 同款策略的内联实现（services 层互不引用，禁止 import
    process_mgr）——Windows 下 maven/cmd 派生的孙进程在只杀直接子进程时会存活。
    """
    try:
        root = psutil.Process(proc.pid)
        tree = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:
        return
    for p in tree:
        try:
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(tree, timeout=_STOP_GRACE)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def run_build(root: Path, tool: str, kind: str = "compile",
              timeout: int = 300, offline: bool = False) -> dict:
    """执行构建/测试。返回 {cmd, code, tail, seconds, timed_out}。"""
    cmd = build_command(tool, kind, offline)
    started = time.time()
    proc = subprocess.Popen(
        cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
        output = (out or "") + (err or "")
        return {"cmd": " ".join(cmd), "code": proc.returncode,
                "tail": output[-TAIL_CHARS:], "seconds": round(time.time() - started, 1),
                "timed_out": False}
    except subprocess.TimeoutExpired:
        _kill_tree(proc)  # 杀整棵树：孙进程不留活口
        try:
            out, err = proc.communicate(timeout=10)  # 收割残余输出（树已死，管道 EOF）
        except subprocess.TimeoutExpired:
            out, err = "", ""  # 管道被遗孤句柄占用：放弃收割（进程树已杀）
        output = (out or "") + (err or "")
        return {"cmd": " ".join(cmd), "code": -1,
                "tail": output[-TAIL_CHARS:] + f"\n（超过 {timeout}s 被强杀）",
                "seconds": round(time.time() - started, 1), "timed_out": True}
