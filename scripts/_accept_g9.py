# -*- coding: utf-8 -*-
"""验收第 9 组：上下文与模型渠道 e2e 手动项（tinyrag 工作区 + 服务重启）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖：
- 9.5 fallback e2e：provider=openai_compat（401 风控必失败）+ fallback=mock，
  POST /api/chat 应得到完整回复；agent.log 出现 openai_compat ok=false 的 llm 行。
  （mock 不记账——factory 注释「假模型不记账」，故 fallback 生效以 SSE 文本佐证。）
- 9.6 warmup e2e：provider=deepseek_official（402 余额不足，调用必失败但
  ObservedLLM 仍会记 task=warmup 行），warmup_on_start=false 重启无新增
  warmup 行；=true 重启出现新 warmup 行。warmup 对 mock 短路（app.py），
  故必须用真实渠道驱动。
- 9.1/9.2 test_context_manager、9.3/9.4 走查 6 直接引用打勾。
结束还原：llm-config 原值、活动工作区、tinyrag session.json，服务保持运行。
"""
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g9_bak"
AGENT_LOG = ROOT / "runtime/agent.log"
RESULTS = []


def rec(item, ok, detail=""):
    print(("✅" if ok else "❌") + f" {item}" + (f" — {detail}" if detail else ""), flush=True)
    RESULTS.append((item, ok))


def api(path, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read()[:200]}"}


def sse_chat(text):
    """POST /api/chat 读完全部 SSE，返回 (deltas 拼接文本, 事件类型列表)。"""
    req = urllib.request.Request(
        BASE + "/api/chat", data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    body = urllib.request.urlopen(req, timeout=180).read().decode("utf-8", "replace")
    deltas, events = [], []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        events.append(ev.get("type"))
        if ev.get("type") == "delta":
            deltas.append(ev.get("content", ""))
    return "".join(deltas), events


def llm_lines_since(n):
    """agent.log 第 n 行之后（不含）的 kind=llm 记录。"""
    if not AGENT_LOG.exists():
        return []
    out = []
    for line in AGENT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[n:]:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") == "llm":
            out.append(r)
    return out


def log_line_count():
    if not AGENT_LOG.exists():
        return 0
    return len(AGENT_LOG.read_text(encoding="utf-8", errors="replace").splitlines())


def set_llm_config(provider, fallback, warmup):
    r = api("/api/llm-config", {
        "provider": provider, "fallback_provider": fallback,
        "warmup_on_start": warmup, "sections": {}})
    assert r.get("ok"), f"保存 llm-config 失败: {r}"


def restart_service():
    """杀掉 8765 占用进程并重新拉起 uvicorn，等待就绪。"""
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if ":8765" in line and "LISTEN" in line:
            subprocess.run(["taskkill", "/PID", line.split()[-1], "/F"],
                           capture_output=True)
    time.sleep(2)
    log = open(ROOT / "runtime/_accept_g9_server.log", "ab")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api.app:app",
         "--host", "127.0.0.1", "--port", "8765"],
        cwd=ROOT, stdout=log, stderr=log,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    for _ in range(90):
        try:
            urllib.request.urlopen(BASE + "/api/workspaces", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    orig = api("/api/llm-config")
    orig_ws = api("/api/workspaces")["active"]
    if BAK.exists():
        shutil.rmtree(BAK)
    BAK.mkdir(parents=True)
    shutil.copy2(WS / "session.json", BAK / "session.json")
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    try:
        # ---- 9.5 主渠道失败 → 备用渠道接管（e2e） ----
        set_llm_config("openai_compat", "mock", False)
        n0 = log_line_count()
        text, events = sse_chat("打个招呼")
        new_llm = llm_lines_since(n0)
        primary_fail = any(r.get("provider") == "openai_compat" and not r.get("ok")
                           for r in new_llm)
        replied = "done" in events and "error" not in events and bool(text.strip())
        rec("9.5 主渠道 401 → mock 接管出完整回复", primary_fail and replied,
            f"primary_fail={primary_fail} replied={replied} "
            f"len={len(text)} head={text[:30]!r}")

        # ---- 9.6 启动预热（e2e，真实渠道驱动） ----
        set_llm_config("deepseek_official", "", False)
        assert restart_service(), "重启服务失败（warmup=false）"
        n1 = log_line_count()
        time.sleep(8)  # 给潜在预热线程留窗口
        warm_off = [r for r in llm_lines_since(n1) if r.get("task") == "warmup"]
        rec("9.6 warmup_on_start=false → 无预热调用", len(warm_off) == 0,
            f"新增 warmup 行={len(warm_off)}")

        set_llm_config("deepseek_official", "", True)
        assert restart_service(), "重启服务失败（warmup=true）"
        n2 = log_line_count()
        warm_on = []
        for _ in range(15):  # 402 失败也应记账，最多等 30s
            warm_on = [r for r in llm_lines_since(n2) if r.get("task") == "warmup"]
            if warm_on:
                break
            time.sleep(2)
        rec("9.6 warmup_on_start=true → 启动即发预热调用", len(warm_on) >= 1,
            f"新增 warmup 行={len(warm_on)} "
            f"ok={warm_on[0].get('ok') if warm_on else '-'}")
    finally:
        set_llm_config(orig.get("provider", "mock"),
                       orig.get("fallback_provider", ""),
                       bool(orig.get("warmup_on_start", False)))
        restart_service()  # 原配置重启，服务恢复原状
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK, ignore_errors=True)

    failed = [i for i, ok in RESULTS if not ok]
    print(f"\n== G9 手动项：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ==")
    if failed:
        print("失败项: " + "; ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
