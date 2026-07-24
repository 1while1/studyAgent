"""process_mgr（M6 进程管理）测试：真实起停/杀树/端口探测/PID 复用守卫。

§13 验收关键：真实杀树（父进程 spawn python -m http.server 子进程 → stop 后
父子双亡、端口释放）。安全关键：cmdline 哈希失配的登记项绝不可被 kill。
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import ConfigService
from backend.services.process_mgr import ProcessError, ProcessManager

PY = sys.executable


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _port_free(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class TestProcessMgr(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="procmgr_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        self.demo = self.tmp / "demo"
        self.demo.mkdir()
        self.proj = self.tmp / "projA"
        self.proj.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.proj.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n'
            f'demo_dir = "{self.demo.as_posix()}"\n'
            'replica_name = ""\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        self.mgr = ProcessManager(self.config)

    def tearDown(self):
        self.mgr.stop_all()  # 失败残留兜底：绝不把测试进程留在系统上
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 白名单 ----

    def test_cwd_whitelist(self):
        with self.assertRaises(ProcessError):
            self.mgr.start(str(self.tmp), [PY, "-V"])       # tmp 根不在白名单
        with self.assertRaises(ProcessError):
            self.mgr.start("C:/Windows", [PY, "-V"])        # 系统目录
        with self.assertRaises(ProcessError):
            self.mgr.start("", [PY, "-V"])                  # 空 cwd
        with self.assertRaises(ProcessError):
            self.mgr.start(str(self.demo), [])              # 空 cmd
        with self.assertRaises(ProcessError):
            self.mgr.start(str(self.demo), ["no_such_exe_zzz"])  # 无可执行文件

    # ---- 起停 + 端口 + 日志 ----

    def test_http_server_lifecycle(self):
        port = _free_port()
        r = self.mgr.start(str(self.demo),
                           [PY, "-m", "http.server", str(port),
                            "--bind", "127.0.0.1"], name="web")
        self.assertIn(port, r["ports"])          # 端口探测命中
        lst = self.mgr.list()
        self.assertEqual(lst[0]["status"], "running")
        self.assertEqual(lst[0]["pid"], r["pid"])
        # 触发一条访问日志，验证 stdout/stderr 直写日志文件
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
        time.sleep(0.5)
        tail = self.mgr.logs_tail(r["id"])
        self.assertTrue(any("GET" in line for line in tail["lines"]))
        # 停止 → 进程亡 + 端口释放 + 状态回读 stopped
        out = self.mgr.stop(r["id"])
        self.assertTrue(out["stopped"])
        deadline = time.time() + 5
        while time.time() < deadline and not _port_free(port):
            time.sleep(0.2)
        self.assertTrue(_port_free(port))
        self.assertEqual(self.mgr.list()[0]["status"], "stopped")
        self.assertIsNone(self.mgr.list()[0]["pid"])

    # ---- 真实杀树（§13 验收） ----

    def test_kill_process_tree(self):
        port = _free_port()
        # 父进程：spawn http.server 子进程后沉睡（模拟"服务启动脚本"形态）
        parent_src = (
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable,'-m','http.server','{port}',"
            "'--bind','127.0.0.1'])\n"
            "time.sleep(120)\n")
        r = self.mgr.start(str(self.demo), [PY, "-c", parent_src],
                           name="tree")
        # 等子进程接管端口
        deadline = time.time() + 10
        while time.time() < deadline and _port_free(port):
            time.sleep(0.2)
        self.assertFalse(_port_free(port), "子进程未监听端口（测试前提失败）")
        import psutil
        children_before = psutil.Process(r["pid"]).children(recursive=True)
        self.assertEqual(len(children_before), 1)
        child_pid = children_before[0].pid
        out = self.mgr.stop(r["id"])
        self.assertTrue(out["stopped"])
        self.assertIn(child_pid, out["killed"])      # 子进程被纳入杀树
        deadline = time.time() + 5
        while time.time() < deadline and not _port_free(port):
            time.sleep(0.2)
        self.assertTrue(_port_free(port))            # 端口随树释放
        self.assertFalse(psutil.pid_exists(r["pid"]))
        self.assertFalse(psutil.pid_exists(child_pid))

    # ---- PID 复用守卫 ----

    def test_pid_reuse_guard(self):
        """登记项指向无关真实进程（本测试进程自身）且哈希不符 → 报 stopped、拒绝 kill。"""
        data = self.mgr._load()
        data["processes"]["fake01"] = {
            "id": "fake01", "name": "ghost", "cmdline": ["ghost"],
            "cwd": str(self.demo), "pid": os.getpid(),
            "hash": "0" * 40, "started_at": "2026-01-01 00:00:00",
            "log_path": str(self.tmp / "runtime" / "logs" / "fake01.log"),
            "status": "running", "ports": []}
        self.mgr._save(data)
        lst = self.mgr.list()
        fake = next(x for x in lst if x["id"] == "fake01")
        self.assertEqual(fake["status"], "stopped")   # 哈希不符 → 已停止
        self.assertIsNone(fake["pid"])
        out = self.mgr.stop("fake01")                 # 绝不 kill 本测试进程
        self.assertTrue(out["stopped"])
        self.assertIn("未执行 kill", out["note"])
        self.assertTrue(os.getpid() > 0)              # 我们还活着（废话但重要）
        with self.assertRaises(ProcessError):
            self.mgr.stop("no_such_id")

    # ---- 注册表损坏恢复 ----

    def test_corrupt_registry_recovers(self):
        reg = self.tmp / "runtime" / "processes.json"
        reg.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.mgr.list(), [])
        self.assertTrue((self.tmp / "runtime" / "processes.corrupt.bak")
                        .is_file())

    # ---- 日志流（SSE tail 生成器） ----

    def test_logs_stream_live_and_end(self):
        r = self.mgr.start(
            str(self.demo),
            [PY, "-c", "import time;print('l1',flush=True);"
                       "time.sleep(4);print('l2',flush=True)"],
            name="echo")
        events = list(self.mgr.logs_stream(r["id"]))
        kinds = [e["type"] for e in events]
        self.assertIn("log", kinds)
        self.assertEqual(kinds[-1], "end")
        lines = [e.get("line", "") for e in events if e["type"] == "log"]
        self.assertTrue(any("l2" in line for line in lines))

    # ---- M6 审查修复回归 ----

    def test_concurrent_start_registers_all(self):
        """B1：并发 start 不互踩丢条目（注册表读改写持锁）。"""
        import threading
        import backend.services.process_mgr as pm_mod
        old_probe = pm_mod._PORT_PROBE_TIMEOUT
        pm_mod._PORT_PROBE_TIMEOUT = 0.2  # 测试提速：无端口进程不等满窗口
        results = []
        try:
            def worker(tag):
                results.append(self.mgr.start(
                    str(self.demo),
                    [PY, "-c", "import time;time.sleep(30)"], name=tag))
            threads = [threading.Thread(target=worker, args=(f"c{i}",))
                       for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            pm_mod._PORT_PROBE_TIMEOUT = old_probe
        self.assertEqual(len(results), 4)
        ids = {r["id"] for r in results}
        self.assertEqual(len(ids), 4)
        registered = {p["id"] for p in self.mgr.list()}
        self.assertTrue(ids <= registered)  # 无互踩丢条目 → 无孤儿进程
        for r in results:
            self.mgr.stop(r["id"])

    def test_logs_tail_big_file(self):
        """B2：大日志只读尾部窗口，tail 仍正确。"""
        r = self.mgr.start(
            str(self.demo),
            [PY, "-c", "import sys\nfor _ in range(5000): sys.stdout.write('x'*100+'\\n')\n"
                       "sys.stdout.flush()\nimport time\ntime.sleep(30)"],
            name="biglog")
        try:
            tail = self.mgr.logs_tail(r["id"], 50)
            self.assertEqual(len(tail["lines"]), 50)
            self.assertTrue(all(line == "x" * 100 for line in tail["lines"][-5:]))
        finally:
            self.mgr.stop(r["id"])

    def test_process_stop_bad_id_type(self):
        """Y4：服务层对非法 id 形态明确 ProcessError（路由层 ok=False 见路由测试）。"""
        with self.assertRaises(ProcessError):
            self.mgr.stop(str(["x"]))


class TestProcessRoutes(unittest.TestCase):
    """路由级：进程 API 的 ok/error 契约与 SSE 日志流。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="proc_rt_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        self.demo = self.tmp / "demo"
        self.demo.mkdir()
        self.proj = self.tmp / "projA"
        self.proj.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress", "completed"]\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[stages]]\nname = "teaching"\nnext = ""\n'
            'sop_step = "步骤一"\ninstruction = "讲"\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.proj.as_posix()}"\n'
            f'session_path = "{(self.tmp / "session.json").as_posix()}"\n'
            f'demo_dir = "{self.demo.as_posix()}"\n'
            'replica_name = ""\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        from backend.api import routes
        from backend.engine.orchestrator import ChatOrchestrator
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.tmp / "session.json")
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        self.routes = routes
        self.mgr = ProcessManager(self.config)

    def tearDown(self):
        self.mgr.stop_all()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_api_lifecycle(self):
        port = _free_port()
        r = self.routes.process_start({
            "cwd": str(self.demo),
            "cmd": f'"{PY}" -m http.server {port} --bind 127.0.0.1',
            "name": "api-web"})
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIn(port, r["ports"])
        lst = self.routes.process_list()
        self.assertTrue(lst["ok"])
        self.assertEqual(lst["processes"][0]["status"], "running")
        self.assertIn("demo", lst["allowed_cwds"])
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
        time.sleep(0.5)
        logs = self.routes.process_logs(r["id"], 50)
        self.assertTrue(logs["ok"])
        self.assertTrue(any("GET" in line for line in logs["lines"]))
        out = self.routes.process_stop({"id": r["id"]})
        self.assertTrue(out["ok"])
        self.assertTrue(out["stopped"])

    def test_api_clear_stopped(self):
        """clear-stopped 端点：已停止条目真移除，running 不受影响。"""
        r = self.routes.process_start({
            "cwd": str(self.demo),
            "cmd": [PY, "-c", "import time;time.sleep(30)"],
            "name": "keep"})
        self.assertTrue(r["ok"], r.get("error"))
        keep_id = r["id"]
        r2 = self.routes.process_start({
            "cwd": str(self.demo),
            "cmd": [PY, "-c", "import time;time.sleep(1)"],
            "name": "gone"})
        gone_id = r2["id"]
        self.routes.process_stop({"id": gone_id})
        out = self.routes.process_clear_stopped()
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["cleared"], 1)
        lst = self.routes.process_list()["processes"]
        ids = [p["id"] for p in lst]
        self.assertNotIn(gone_id, ids)      # 已停止条目被移除
        self.assertIn(keep_id, ids)         # running 保留
        self.routes.process_stop({"id": keep_id})

    def test_api_rejects(self):
        r = self.routes.process_start({"cwd": "C:/Windows", "cmd": f'"{PY}" -V'})
        self.assertFalse(r["ok"])                    # 白名单外 cwd
        r = self.routes.process_start({"cwd": str(self.demo), "cmd": ""})
        self.assertFalse(r["ok"])                    # 空 cmd
        r = self.routes.process_start({"cwd": str(self.demo), "cmd": None})
        self.assertFalse(r["ok"])                    # 缺 cmd
        r = self.routes.process_stop({"id": "ghost99"})
        self.assertFalse(r["ok"])                    # 不存在
        r = self.routes.process_logs("ghost99")
        self.assertFalse(r["ok"])
        # Y4：非法类型也走 ok=False 契约，不冒 500
        r = self.routes.process_stop({"id": ["x"]})
        self.assertFalse(r["ok"])
        r = self.routes.process_stop(None)
        self.assertFalse(r["ok"])

    def test_api_log_stream_sse(self):
        r = self.routes.process_start({
            "cwd": str(self.demo),
            "cmd": [PY, "-c", "import time;print('s1',flush=True);"
                              "time.sleep(4);print('s2',flush=True)"],
            "name": "sse"})
        self.assertTrue(r["ok"], r.get("error"))
        resp = self.routes.process_logs_stream(r["id"])

        async def drive():
            chunks = []
            async for chunk in resp.body_iterator:
                chunks.append(chunk)
            return "".join(chunks)
        import asyncio
        text = asyncio.run(asyncio.wait_for(drive(), timeout=30))
        self.assertIn('"log"', text)
        self.assertIn("s2", text)
        self.assertIn('"end"', text)


if __name__ == "__main__":
    unittest.main()
