# -*- coding: utf-8 -*-
"""验收第 11 组：UI/UX 手动复核项（tinyrag 工作区，Playwright）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖：
- 11.2 双主题截图复核：tutor 暖纸 vs pair IDE 深色——body[data-layout] 与
  计算背景色必须不同；截图存 runtime/_accept_g11_shots/ 供人工/AI 目检串色。
- 11.4 弹窗主按钮钉底可见：模型配置(#llm-save)/用量(#usage-auth-area)/
  demo(#demo-create)/向导(#ws-create) 的 footer 主按钮 bounding box
  必须完整落在视口内；资料弹窗无 foot 设计，校验弹窗整体在视口内。
- 11.8 toast 位置：CSS 静态校验（tutor bottom:150px 居中 / pair 右锚 220px）。
- 11.1 走查 9、11.3 走查 7、11.5 走查 9k、11.6 走查 7c/8、11.7 走查 4 引用打勾。
前提：服务 8765 运行中。结束还原：session 模式、活动工作区。
"""
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "runtime/_accept_g11_shots"
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


def btn_in_viewport(page, sel):
    """主按钮可见且完整落在视口内。"""
    loc = page.locator(sel).first
    if not loc.is_visible():
        return False, "不可见"
    bb = loc.bounding_box()
    vp = page.viewport_size
    if not bb:
        return False, "无 bbox"
    ok = (bb["y"] >= 0 and bb["x"] >= 0
          and bb["y"] + bb["height"] <= vp["height"]
          and bb["x"] + bb["width"] <= vp["width"])
    return ok, f"y={bb['y']:.0f}+{bb['height']:.0f} 视口高={vp['height']}"


def main():
    orig_ws = api("/api/workspaces")["active"]
    orig_mode = api("/api/session/mode").get("mode", "study")
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})

            # ---- 11.2 tutor 暖纸主题 ----
            page.request.post(BASE + "/api/session/mode", data={"mode": "study"})
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(1500)
            layout_t = page.evaluate("document.body.dataset.layout")
            bg_t = page.evaluate(
                "getComputedStyle(document.body).backgroundColor")
            page.screenshot(path=str(SHOTS / "tutor.png"), full_page=False)

            # ---- 11.2 pair IDE 深色主题 ----
            page.request.post(BASE + "/api/session/mode", data={"mode": "code"})
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(1500)
            layout_p = page.evaluate("document.body.dataset.layout")
            bg_p = page.evaluate(
                "getComputedStyle(document.body).backgroundColor")
            page.screenshot(path=str(SHOTS / "pair.png"), full_page=False)
            rec("11.2 双主题区分（tutor 暖纸 vs pair 深色）",
                layout_t == "tutor" and layout_p == "pair" and bg_t != bg_p,
                f"layout={layout_t}/{layout_p} bg={bg_t} vs {bg_p}")

            # ---- 11.4 弹窗主按钮钉底（pair 模式下 demo 可用） ----
            # demo 弹窗
            page.locator("#demo-new").click()
            page.wait_for_timeout(600)
            ok, d = btn_in_viewport(page, "#demo-create")
            rec("11.4 demo 弹窗主按钮钉底可见",
                page.locator("#demo-modal").is_visible() and ok, d)
            page.locator("#demo-close").click()
            page.wait_for_timeout(300)
            # 模型配置弹窗
            page.locator("#open-llm-config").click()
            page.wait_for_timeout(1000)
            ok, d = btn_in_viewport(page, "#llm-save")
            rec("11.4 模型配置主按钮钉底可见",
                page.locator("#llm-modal").is_visible() and ok, d)
            page.locator("#llm-close").click()
            page.wait_for_timeout(300)
            # 用量弹窗
            page.locator("#open-usage").click()
            page.wait_for_timeout(800)
            ok, d = btn_in_viewport(page, "#usage-auth-area")
            rec("11.4 用量弹窗底栏钉底可见",
                page.locator("#usage-auth-area").is_visible() and ok, d)
            page.locator("#usage-close").click()
            page.wait_for_timeout(300)
            # 初始化向导弹窗
            page.locator("#ws-current").click()
            page.wait_for_timeout(400)
            page.locator("#ws-menu .ws-item", has_text="新建工作区").click()
            page.wait_for_timeout(800)
            ok, d = btn_in_viewport(page, "#ws-create")
            rec("11.4 向导弹窗主按钮钉底可见",
                page.locator("#ws-modal").is_visible() and ok, d)
            page.locator("#ws-close").click()
            page.wait_for_timeout(300)
            # 资料弹窗（无 foot 设计，校验整体在视口内 + 头部关闭钮可达）
            page.locator("#open-docs").click()
            page.wait_for_timeout(1200)
            ok, d = btn_in_viewport(page, "#doc-close")
            card_bb = page.locator("#doc-modal .modal-box").first.bounding_box() \
                if page.locator("#doc-modal .modal-box").count() else None
            vp = page.viewport_size
            card_ok = bool(card_bb) and card_bb["y"] >= 0 and \
                card_bb["y"] + card_bb["height"] <= vp["height"]
            rec("11.4 资料弹窗整体视口内+关闭钮可达",
                page.locator("#doc-modal").is_visible() and ok and card_ok,
                f"{d} card_ok={card_ok}")
            page.locator("#doc-close").click()
            browser.close()

        # ---- 11.8 toast 位置（CSS 静态校验） ----
        css = (ROOT / "frontend/style.css").read_text(encoding="utf-8")
        flat = css.replace(" ", "").replace("\n", "")
        tutor_ok = ".toast{" in flat and "bottom:150px" in flat
        pair_ok = 'body[data-layout="pair"].toast' in flat and "right:220px" in flat
        rec("11.8 toast 不遮挡关键操作区（tutor 150px/pair 右锚）",
            tutor_ok and pair_ok, f"tutor_150px={tutor_ok} pair_右锚={pair_ok}")
    finally:
        api("/api/session/mode", {"mode": orig_mode})
        api("/api/workspaces/switch", {"slug": orig_ws})

    failed = [i for i, ok in RESULTS if not ok]
    print(f"\n== G11 手动项：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ==")
    print(f"截图目录: {SHOTS}")
    if failed:
        print("失败项: " + "; ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
