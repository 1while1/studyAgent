# -*- coding: utf-8 -*-
"""验收第 10 组：可观测与安全手动项（tinyrag 工作区）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖 10.6 会话并发：两个并发 HTTP 客户端（等价双标签页）同时 POST /api/chat，
断言两轮都完整回复（done 无 error）且 session chat_history 尾部严格
user→assistant 交替、不丢不串（流程锁 threading.Lock 串行化整个流）；
随后 Playwright 开一个页面确认两条问答都在渲染历史中可见。
10.1 手动查 agent.log（llm/tool 条目字段齐全；plan 记账见 test_planner:
185/253，prefetch 记账=log_tool 见 observer.py:252 + test_materials
TestPrefetchOrchestration）；10.2/10.3/10.4 走查 9e；10.5 单测
（test_review_batch 代码浏览器拒读 .env / test_materials skip_sensitive
资料解析拒读 / AI READ 复用 code_browser 同一拒读链路）。
前提：服务 8765 运行中。结束还原：llm-config、活动工作区、tinyrag session。
"""
import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g10_bak"
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


def sse_chat(text, out):
    req = urllib.request.Request(
        BASE + "/api/chat", data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        body = urllib.request.urlopen(req, timeout=180).read().decode("utf-8", "replace")
    except Exception as e:
        out["error"] = str(e)
        return
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
    out["text"] = "".join(deltas)
    out["events"] = events


def main():
    orig = api("/api/llm-config")
    orig_ws = api("/api/workspaces")["active"]
    if BAK.exists():
        shutil.rmtree(BAK)
    BAK.mkdir(parents=True)
    shutil.copy2(WS / "session.json", BAK / "session.json")
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    r = api("/api/llm-config", {"provider": "mock", "fallback_provider": "",
                                "warmup_on_start": False, "sections": {}})
    assert r.get("ok"), f"切 mock 失败: {r}"
    try:
        before = json.loads((WS / "session.json").read_text(encoding="utf-8"))
        n_hist = len(before.get("chat_history", []))

        # ---- 10.6 双客户端并发发消息 ----
        ra, rb = {}, {}
        ta = threading.Thread(target=sse_chat, args=("并发问题甲", ra))
        tb = threading.Thread(target=sse_chat, args=("并发问题乙", rb))
        ta.start(); tb.start(); ta.join(); tb.join()

        ok_a = "done" in ra.get("events", []) and "error" not in ra.get("events", []) \
            and bool(ra.get("text", "").strip())
        ok_b = "done" in rb.get("events", []) and "error" not in rb.get("events", []) \
            and bool(rb.get("text", "").strip())
        rec("10.6 并发两轮都完整回复", ok_a and ok_b,
            f"甲 done={'done' in ra.get('events', [])} len={len(ra.get('text', ''))} "
            f"乙 done={'done' in rb.get('events', [])} len={len(rb.get('text', ''))} "
            f"err={ra.get('error') or rb.get('error') or '-'}")

        after = json.loads((WS / "session.json").read_text(encoding="utf-8"))
        tail = after.get("chat_history", [])[n_hist:]
        users = [m["content"] for m in tail if m.get("role") == "user"]
        roles = [m.get("role") for m in tail]
        alternates = all(roles[i] != roles[i + 1]
                         for i in range(len(roles) - 1)) and len(tail) == 4
        rec("10.6 历史不丢不串（4 条严格交替）",
            sorted(users) == sorted(["并发问题甲", "并发问题乙"]) and alternates,
            f"roles={roles} users={users}")

        # ---- 10.6 前端渲染一致性：刷新后两条问答都在 ----
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(2000)
            html = page.content()
            rec("10.6 前端历史渲染两条并发消息",
                "并发问题甲" in html and "并发问题乙" in html,
                f"甲={'并发问题甲' in html} 乙={'并发问题乙' in html}")
            browser.close()
    finally:
        api("/api/llm-config", {
            "provider": orig.get("provider", "mock"),
            "fallback_provider": orig.get("fallback_provider", ""),
            "warmup_on_start": bool(orig.get("warmup_on_start", False)),
            "sections": {}})
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK, ignore_errors=True)

    failed = [i for i, ok in RESULTS if not ok]
    print(f"\n== G10 手动项：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ==")
    if failed:
        print("失败项: " + "; ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
