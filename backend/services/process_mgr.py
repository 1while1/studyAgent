"""进程管理（M6 实战工坊，AgentDesign §7）：起停/日志/端口探测/真实杀树。

安全设计：
- **cwd 白名单**：仅 demo 根 / replica 根 / project_dir / 当前工作区 code_roots
  （"启动原项目看效果"是合法场景；写白名单不因此放宽，仍仅 demo/replica）。
- **PID 复用守卫**：登记时存 cmdline 哈希；一切状态判断与 kill 前都重新校验
  `psutil.Process(pid).cmdline()` 哈希——失配视为已停止，绝不动 kill（防误杀
  操作系统回收后复用同 PID 的无关进程）。
- **杀树**：terminate 进程树（children(recursive=True) + 自身），3s 后 kill 残余。
- **日志**：stdout/stderr **直接重定向**到 `runtime/logs/<id>.log`（有意偏离设计
  原文"独立线程读 stdout"——直写文件抗服务重启、无管道断裂/死锁风险；
  SSE 只转 tail 的设计意图不变）。
- 注册表 `runtime/processes.json`（schema_version=1，atomic_write）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

import psutil

from .backup_service import atomic_write
from .config_service import WEB_ROOT, ConfigService, runtime_dir

_SCHEMA = {"schema_version": 1, "processes": {}}
_PORT_PROBE_TIMEOUT = 2.5    # 启动后端口快速探测窗口（秒）；慢服务靠 list() 实时探测兜底
_STOP_GRACE = 3.0            # terminate 后等待再 kill 的宽限（秒）
_REG_LOCK = threading.RLock()  # 注册表读改写互斥（M6 审查修复 B1：防并发 start 互踩丢条目/孤儿进程）
_TAIL_READ_BYTES = 256 * 1024  # logs_tail 尾部定位读取窗口（B2 修复：防大日志全量入内存）


class ProcessError(Exception):
    """白名单越界 / 进程不存在 / 状态非法等可预期失败。"""


def _cmd_hash(cmdline: list[str], cwd: str) -> str:
    raw = json.dumps({"cmd": cmdline, "cwd": cwd}, ensure_ascii=False,
                     sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class ProcessManager:
    def __init__(self, config: ConfigService):
        self._config = config
        self._dir = runtime_dir(config)
        self._logs = self._dir / "logs"
        self._logs.mkdir(parents=True, exist_ok=True)
        self._reg_path = self._dir / "processes.json"

    # ---- 注册表 ----

    # 公开入口：注册表读改写全程持锁（B1 修复）。RLock 可重入，
    # stop_all → list/stop 嵌套安全；端口快探也在锁内（正确性优先于并发度）。

    def list(self) -> list[dict]:
        with _REG_LOCK:
            return self._list_unlocked()

    def start(self, cwd: str, cmd: list[str], name: str = "") -> dict:
        with _REG_LOCK:
            return self._start_unlocked(cwd, cmd, name)

    def stop(self, pid_id: str) -> dict:
        with _REG_LOCK:
            return self._stop_unlocked(pid_id)

    def _load(self) -> dict:
        if not self._reg_path.is_file():
            return json.loads(json.dumps(_SCHEMA))
        try:
            data = json.loads(self._reg_path.read_text(encoding="utf-8"))
        except Exception:
            corrupt = self._reg_path.with_suffix(".corrupt.bak")
            self._reg_path.replace(corrupt)
            return json.loads(json.dumps(_SCHEMA))
        if not isinstance(data.get("processes"), dict):
            data["processes"] = {}
        return data

    def _save(self, data: dict) -> None:
        atomic_write(self._reg_path,
                     json.dumps(data, ensure_ascii=False, indent=1))

    # ---- cwd 白名单 ----

    def allowed_cwds(self) -> dict[str, Path]:
        """可启动进程的工作目录白名单（含"启动原项目"场景）。"""
        ws = self._config.workspace
        roots: dict[str, Path] = {"demo": Path(ws.demo_dir).resolve()}
        if ws.replica_name:
            rep = (WEB_ROOT.parent / ws.replica_name).resolve()
            if rep.is_dir():
                roots["replica"] = rep
        proj = Path(ws.project_dir).resolve()
        if proj.is_dir():
            roots["project"] = proj
        for r in self._config.code_roots:
            p = Path(r["path"])
            p = (p if p.is_absolute() else (WEB_ROOT / r["path"])).resolve()
            if p.is_dir():
                roots.setdefault(f"code:{r['name']}", p)
        return roots

    def _check_cwd(self, cwd: str) -> Path:
        cwd = (cwd or "").strip()
        if not cwd:
            raise ProcessError("cwd 不能为空")
        target = Path(cwd)
        if not target.is_absolute():
            target = (WEB_ROOT / cwd).resolve()
        target = target.resolve()
        for root in self.allowed_cwds().values():
            if target == root or root in target.parents:
                if not target.is_dir():
                    raise ProcessError(f"工作目录不存在: {cwd}")
                return target
        raise ProcessError(
            f"工作目录不在白名单内（仅 demo/replica/项目目录/代码根）: {cwd}")

    # ---- 状态 ----

    def _live_status(self, entry: dict) -> str:
        """pid 存在 + cmdline 哈希吻合 → running；否则 dead（绝不误报）。

        哈希基准是启动时从 psutil 抓取的规范化 cmdline（与运行时同口径），
        不是用户输入的 argv（python → C:\\Python314\\python.exe 这类差异
        会让输入 argv 永远对不上）。
        """
        pid = entry.get("pid")
        if not pid or not psutil.pid_exists(pid):
            return "stopped"
        try:
            proc = psutil.Process(pid)
            cmdline = proc.cmdline()
            cwd = proc.cwd()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return "stopped"
        if _cmd_hash(cmdline, cwd) != entry.get("hash"):
            return "stopped"  # PID 已被复用：登记进程已死
        return "running"

    def _list_unlocked(self) -> list[dict]:
        data = self._load()
        out = []
        changed = False
        for pid_key, e in data["processes"].items():
            status = self._live_status(e)
            if status != e.get("status"):
                e["status"] = status
                changed = True
            out.append({"id": e["id"], "name": e.get("name", ""),
                        "cmd": e["cmdline"], "cwd": e["cwd"],
                        "pid": e["pid"] if status == "running" else None,
                        "status": status,
                        "ports": self._ports(e) if status == "running"
                        else e.get("ports", []),
                        "started_at": e.get("started_at", "")})
        if changed:
            self._save(data)
        out.sort(key=lambda x: x["started_at"], reverse=True)
        return out

    def _entry(self, pid_id: str) -> dict:
        e = self._load()["processes"].get(pid_id)
        if e is None:
            raise ProcessError(f"进程不存在: {pid_id}")
        return e

    # ---- 起停 ----

    def _start_unlocked(self, cwd: str, cmd: list[str], name: str = "") -> dict:
        if not cmd or not all(isinstance(c, str) and c for c in cmd):
            raise ProcessError("cmd 必须是非空字符串数组")
        workdir = self._check_cwd(cwd)
        pid_id = uuid.uuid4().hex[:8]
        log_path = self._logs / f"{pid_id}.log"
        creationflags = (subprocess.CREATE_NEW_PROCESS_GROUP
                         if os.name == "nt" else 0)
        log_fp = open(log_path, "a", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(workdir),
                stdout=log_fp, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=(os.name != "nt"))
        except FileNotFoundError:
            log_fp.close()
            raise ProcessError(f"可执行文件未找到: {cmd[0]}")
        except Exception as e:
            log_fp.close()
            raise ProcessError(f"启动失败: {e}")
        finally:
            # Popen 已把句柄复制给子进程；父进程立即关闭自己的副本（防泄漏）
            if not log_fp.closed:
                log_fp.close()
        # 从 psutil 抓取规范化 cmdline/cwd 作为哈希基准（与 _live_status 同口径）；
        # 刚启动时进程对象偶发未就绪，短重试兜底，失败则留空哈希→只会误报 stopped
        # （fail-safe：永不误杀），绝不放行 kill。
        ps_cmd, ps_cwd = [], ""
        for _ in range(10):
            try:
                p = psutil.Process(proc.pid)
                ps_cmd, ps_cwd = p.cmdline(), p.cwd()
                if ps_cmd:
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(0.1)
        entry = {"id": pid_id, "name": name.strip() or cmd[0],
                 "cmdline": list(cmd), "cwd": str(workdir),
                 "pid": proc.pid, "hash": _cmd_hash(ps_cmd, ps_cwd),
                 "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "log_path": str(log_path), "status": "running",
                 "ports": []}
        data = self._load()
        data["processes"][pid_id] = entry
        self._save(data)
        entry["ports"] = self._probe_ports(entry)
        if entry["ports"]:
            data = self._load()
            data["processes"][pid_id]["ports"] = entry["ports"]
            self._save(data)
        return {"id": pid_id, "pid": proc.pid, "name": entry["name"],
                "ports": entry["ports"], "log": log_path.name}

    def _stop_unlocked(self, pid_id: str) -> dict:
        data = self._load()
        entry = data["processes"].get(pid_id)
        if entry is None:
            raise ProcessError(f"进程不存在: {pid_id}")
        if self._live_status(entry) != "running":
            entry["status"] = "stopped"
            self._save(data)
            return {"id": pid_id, "stopped": True, "note": "进程已停止（或 PID 被复用，未执行 kill）"}
        # 哈希再校验通过：terminate 整棵树
        killed = []
        try:
            root = psutil.Process(entry["pid"])
            tree = root.children(recursive=True) + [root]
        except psutil.NoSuchProcess:
            tree = []
        for p in tree:
            try:
                p.terminate()
                killed.append(p.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(tree, timeout=_STOP_GRACE)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        entry["status"] = "stopped"
        self._save(data)
        return {"id": pid_id, "stopped": True, "killed": killed}

    def stop_all(self) -> int:
        """清理辅助（测试/走查 finally 用）：停掉登记簿上全部活进程。"""
        n = 0
        for item in self.list():
            if item["status"] == "running":
                try:
                    self.stop(item["id"])
                    n += 1
                except ProcessError:
                    pass
        return n

    def clear_stopped(self) -> int:
        """移除登记簿中全部已停止条目（P2-5：UI「清理已停止」语义补全）。
        返回移除条数；running 条目不受影响。"""
        with _REG_LOCK:
            data = self._load()
            stopped = [k for k, e in data["processes"].items()
                       if self._live_status(e) != "running"]
            for k in stopped:
                data["processes"].pop(k)
            if stopped:
                self._save(data)
        return len(stopped)

    # ---- 日志 ----

    def logs_tail(self, pid_id: str, n: int = 200) -> dict:
        entry = self._entry(pid_id)
        path = Path(entry["log_path"])
        if not path.is_file():
            return {"id": pid_id, "lines": []}
        # 尾部定位读取（B2 修复：唠叨进程 1GB 日志也不再全量读入内存）
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - _TAIL_READ_BYTES))
            chunk = f.read().decode("utf-8", errors="replace")
        if size > _TAIL_READ_BYTES:
            chunk = chunk.split("\n", 1)[-1]  # 丢弃首行残段
        lines = chunk.splitlines()
        return {"id": pid_id, "lines": lines[-max(1, min(n, 2000)):],
                "status": self._live_status(entry)}

    def logs_stream(self, pid_id: str):
        """SSE tail 生成器：轮询文件增量；进程死且读尽后结束。"""
        entry = self._entry(pid_id)
        path = Path(entry["log_path"])
        pos = path.stat().st_size if path.is_file() else 0
        idle = 0
        while True:
            chunk = ""
            if path.is_file():
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
            if chunk:
                idle = 0
                for line in chunk.splitlines():
                    yield {"type": "log", "line": line}
            else:
                idle += 1
                if self._live_status(entry) != "running" and idle >= 2:
                    yield {"type": "end",
                           "reason": "进程已退出"}
                    return
                if idle > 3600:  # 30 分钟无输出保险丝
                    yield {"type": "end", "reason": "日志流超时"}
                    return
            time.sleep(0.5)

    # ---- 端口探测 ----

    def _tree_pids(self, entry: dict) -> set[int]:
        pids = {entry["pid"]}
        try:
            root = psutil.Process(entry["pid"])
            pids |= {c.pid for c in root.children(recursive=True)}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return pids

    def _listening_ports(self, pids: set[int]) -> list[int]:
        ports = set()
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if conn.status == "LISTEN" and conn.pid in pids \
                        and conn.laddr:
                    ports.add(conn.laddr.port)
        except (psutil.AccessDenied, PermissionError):
            pass
        return sorted(ports)

    def _ports(self, entry: dict) -> list[int]:
        return self._listening_ports(self._tree_pids(entry))

    def _probe_ports(self, entry: dict) -> list[int]:
        """启动后短窗口探测端口（快服务即时命中）；慢服务由 list() 每次
        实时探测兜底，不为它阻塞 start。"""
        deadline = time.time() + _PORT_PROBE_TIMEOUT
        while time.time() < deadline:
            if self._live_status(entry) != "running":
                return []
            ports = self._ports(entry)
            if ports:
                return ports
            time.sleep(0.3)
        return []


def split_cmd(cmd: str) -> list[str]:
    """UI 传入的单行命令字符串 → argv。

    Windows 下 shlex(posix=False) 会把引号保留为 token 的一部分
    （`"C:\\path\\python.exe" -m x` 的 argv[0] 带引号 → 可执行文件找不到），
    需再剥一层成对引号。
    """
    import shlex
    parts = shlex.split((cmd or "").strip(), posix=(os.name != "nt"))
    if os.name == "nt":
        parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p
                 for p in parts]
    return [p for p in parts if p]
