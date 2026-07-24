# -*- coding: utf-8 -*-
"""验收第 8 组：双模式手动项（tinyrag 工作区，API + Playwright）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖：8.2 code 模式 planner 武装检查（服务端会话 mode=code + flag 开）/
8.5 刷新后模式状态恢复（服务端 mode 定初始布局）。
8.1/8.4 走查 8b、8.3 test_planner R2（allow_actions=False 静默丢弃）、
8.6 test_arch_fixes 🟡-9（切模式清字段+note）打勾。
前提：服务 8765 运行中。结束还原：活动工作区、tinyrag session、模式。
"""
import json
import shutil
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g8_bak"
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


def main():
    orig_ws = api("/api/workspaces")["active"]
    if BAK.exists():
        shutil.rmtree(BAK)
    BAK.mkdir(parents=True)
    shutil.copy2(WS / "session.json", BAK / "session.json")
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    orig_mode = api("/api/session/mode")
    try:
        # ---- 8.2 code 模式：服务端落盘 + planner 武装前提（mode=code） ----
        r = api("/api/session/mode", {"mode": "code"})
        saved = json.loads((WS / "session.json").read_text(encoding="utf-8"))
        rec("8.2 code 模式服务端落盘", r.get("ok", True) and saved.get("mode") == "code",
            f"mode={saved.get('mode')}")

        # ---- 8.5 刷新后模式状态恢复：服务端 mode=code → 初始布局 pair ----
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(1500)
            layout = page.evaluate("document.body.dataset.layout")
            rec("8.5 刷新恢复：mode=code → 初始布局 pair", layout == "pair",
                f"layout={layout}")
            # 还原 study → 刷新回 tutor
            page.request.post(BASE + "/api/session/mode", data={"mode": "study"})
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(1500)
            layout = page.evaluate("document.body.dataset.layout")
            rec("8.5 刷新恢复：mode=study → 初始布局 tutor", layout == "tutor",
                f"layout={layout}")
            browser.close()
    finally:
        api("/api/session/mode", {"mode": orig_mode.get("mode", "study")})
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK)

    fails = [i for i, ok in RESULTS if not ok]
    print(f"\n== G8 手动项：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ==")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
