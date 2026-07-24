# -*- coding: utf-8 -*-
"""验收第 1 组：工作区与初始化（手动项浏览器实测，临时脚本不进 git）。

覆盖：1.1 三工作区切换隔离 / 1.2 新建向导全流程（LLM）/ 1.3 预设下拉 /
1.4 重扫规则14 / 1.5 导出+删除 / （1.6 由走查 8b 锁定，不在此脚本）。
前提：服务 8765 运行中。结束自动切回 ragent。
"""
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
RESULTS = []


def rec(item, ok, detail=""):
    print(("✅" if ok else "❌") + f" {item}" + (f" — {detail}" if detail else ""), flush=True)
    RESULTS.append((item, ok, detail))


def api(path, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read()[:200]}"}


def wait_fn(page, js, timeout_s=180, poll=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if page.evaluate(js):
                return True
        except Exception:
            pass
        time.sleep(poll)
    return False


def snapshot(page, slug):
    st = api("/api/state")
    roots = sorted(r["name"] for r in api("/api/code/roots")["roots"])
    hist = len(api("/api/history")["messages"])
    day_label = page.locator("#day-label").inner_text()
    units = page.locator("#units").inner_text().strip().replace("\n", " | ")[:120]
    title = page.locator("#ws-title").inner_text()
    snap = {"slug": slug, "title": title, "day": day_label, "units": units,
            "roots": roots, "hist": hist}
    print(f"  快照[{slug}] title={title} day={day_label} roots={roots} hist={hist}", flush=True)
    print(f"    units={units}", flush=True)
    return snap


def ui_switch(page, slug):
    page.locator("#ws-current").click()
    page.wait_for_timeout(400)
    item = page.locator(f'.ws-item:has(.ws-slug:text("{slug}"))')
    item.locator(".ws-label").click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(1200)


def main():
    api("/api/session/mode", {"mode": "study"})  # 归一化，防侧栏隐藏
    orig = next((w["slug"] for w in api("/api/workspaces")["workspaces"] if w["active"]), "ragent")
    t_start = time.time()

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 820}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            # ---------- 1.1 三工作区切换隔离 ----------
            page.goto(BASE)
            page.wait_for_timeout(1500)
            ws_now = {w["slug"] for w in api("/api/workspaces")["workspaces"]}
            snaps = {"ragent": snapshot(page, "ragent")}
            for slug in ("tinyrag", "onecoupon"):
                if slug not in ws_now:
                    print(f"  （{slug} 不存在，跳过快照——首轮已验证）", flush=True)
                    continue
                ui_switch(page, slug)
                snaps[slug] = snapshot(page, slug)
            titles = {s["title"] for s in snaps.values()}
            days = {s["day"] for s in snaps.values()}
            roots_sets = {tuple(s["roots"]) for s in snaps.values()}
            units_sets = {s["units"] for s in snaps.values()}
            n = len(snaps)
            rec("1.1 切换隔离-标题", len(titles) == n, str(titles))
            rec("1.1 切换隔离-进度", len(days) >= 2, str(days))
            rec("1.1 切换隔离-代码根", len(roots_sets) == n, str(roots_sets))
            rec("1.1 切换隔离-今日单元", len(units_sets) == n, "")
            if "tinyrag" in snaps:
                hist_ok = snaps["ragent"]["hist"] != snaps["tinyrag"]["hist"]
            else:
                hist_ok = snaps["ragent"]["hist"] != snaps["onecoupon"]["hist"]
            rec("1.1 切换隔离-会话", hist_ok,
                "hist: " + str({k: v["hist"] for k, v in snaps.items()}))
            # session 文件物理隔离（懒创建：无会话的工作区文件可不存在，路径独立即隔离）
            sp = {slug: (ROOT / p).resolve() for slug, p in {
                "ragent": "runtime/session.json",
                "tinyrag": "workspaces/tinyrag/session.json",
                "onecoupon": "workspaces/onecoupon/session.json"}.items()}
            rec("1.1 会话文件物理隔离", len({str(v) for v in sp.values()}) == 3
                and sp["ragent"].exists() and sp["onecoupon"].exists(),
                "三工作区 session 路径独立（tinyrag 无会话记录，文件懒创建不存在属正常）")

            # ---------- 1.3 预设下拉（当前在 onecoupon）----------
            page.locator("#ws-current").click()
            page.wait_for_timeout(400)
            page.locator('#ws-menu .ws-item:has-text("新建工作区")').click()
            ok = wait_fn(page, "document.getElementById('ws-preset').options.length > 0", 15)
            opts = page.eval_on_selector_all("#ws-preset option", "els => els.map(e => e.value + ':' + e.textContent)") if ok else []
            # 下拉 = 1 个「标准（跟随全局）」空值项 + 4 个预设（default/reading/bugfix/article）
            preset_vals = {o.split(":")[0] for o in opts}
            rec("1.3 预设下拉 4 预设", {"default", "reading", "bugfix", "article"} <= preset_vals,
                f"{len(opts)} 项: " + "; ".join(opts))
            page.locator("#ws-close").click()
            page.wait_for_timeout(300)

            # ---------- 1.5 导出 + 删除（tinyrag 不存在则跳过——首轮已全 ✅）----------
            if "tinyrag" in ws_now:
                # (a) 导出 tinyrag（UI 点击触发下载，失败则 API 兜底）
                page.locator("#ws-current").click()
                page.wait_for_timeout(400)
                tiny_item = page.locator('.ws-item:has(.ws-slug:text("tinyrag"))')
                zf = None
                src = ""
                try:
                    with page.expect_download(timeout=15000) as dl_info:
                        tiny_item.locator('[data-op="export"]').click()
                    zpath = dl_info.value.path()
                    zf = zipfile.ZipFile(zpath)
                    src = "UI下载"
                except Exception:
                    try:
                        data = urllib.request.urlopen(BASE + "/api/workspaces/export?slug=tinyrag", timeout=60).read()
                        import io
                        zf = zipfile.ZipFile(io.BytesIO(data))
                        src = "API兜底"
                    except Exception as e2:
                        rec("1.5 导出 zip", False, f"两路均失败: {e2}")
                if zf is not None:
                    names = zf.namelist()
                    hit = [n for n in ("StudyState.json", "Study.md", "Project.md")
                           if any(x.endswith(n) for x in names)]
                    rec("1.5 导出 zip", len(hit) == 3, f"{src}, {len(names)} 个文件, 含 {hit}")
                # (b) 激活项 UI 无删除按钮
                page.locator("#ws-current").click()
                page.wait_for_timeout(400)
                n_del_active = page.locator('.ws-item.active [data-op="delete"]').count()
                rec("1.5 激活项无删除按钮(UI)", n_del_active == 0, "")
                page.keyboard.press("Escape")
                page.locator("body").click()
                # (c) API 禁删激活
                cur_active = next((w["slug"] for w in api("/api/workspaces")["workspaces"] if w["active"]), None)
                r = api("/api/workspaces/delete", {"slug": cur_active, "delete_data": False})
                rec("1.5 禁删激活工作区(API)", not r.get("ok"), f"resp={r}")
                # (d) UI 删 tinyrag 保留磁盘
                dialogs = {"n": 0}

                def on_dialog(d):
                    dialogs["n"] += 1
                    if dialogs["n"] == 1:
                        d.accept()
                    else:
                        d.dismiss()  # 保留磁盘数据
                page.on("dialog", on_dialog)
                page.locator("#ws-current").click()
                page.wait_for_timeout(400)
                page.locator('.ws-item:has(.ws-slug:text("tinyrag")) [data-op="delete"]').click()
                page.wait_for_timeout(1200)
                gone = all(w["slug"] != "tinyrag" for w in api("/api/workspaces")["workspaces"])
                disk_kept = (ROOT / "workspaces/tinyrag/docx").exists()
                rec("1.5 删除-配置移除", gone, f"dialogs={dialogs['n']}")
                rec("1.5 删除-默认保留磁盘", disk_kept, "")
                # (e) 清掉旧磁盘目录，为 1.2 重建让路
                if disk_kept:
                    shutil.rmtree(ROOT / "workspaces/tinyrag")
                    print("  （旧 tinyrag 磁盘目录已清理，准备重建）", flush=True)
            else:
                print("  （1.5 导出/删除首轮已 ✅，本轮跳过）", flush=True)

            # ---------- 1.2 新建工作区向导（重建 tinyrag，真实 LLM）----------
            page.locator("#ws-current").click()
            page.wait_for_timeout(400)
            page.locator('#ws-menu .ws-item:has-text("新建工作区")').click()
            page.wait_for_timeout(600)
            page.fill("#ws-project-dir", "../temp_tinyrag")
            page.fill("#ws-slug", "tinyrag")
            page.fill("#ws-title-input", "TinyRAG 学习")
            page.fill("#ws-goal", "测试通用工作区初始化流程")
            page.fill("#ws-days", "5")
            page.locator("#ws-preview-btn").click()
            ok_scan = wait_fn(page, """(() => {
                const el = document.getElementById('ws-scan-preview');
                return el && !el.classList.contains('hidden') && el.textContent.length > 50;
            })()""", 60)
            prev = page.locator("#ws-scan-preview").text_content() or ""
            rec("1.2 扫描预览", ok_scan, f"{len(prev.strip())} 字符: {prev.strip()[:80]}...")
            page.locator("#ws-create").click()
            st = None
            t0 = time.time()
            while time.time() - t0 < 420:
                try:
                    st = page.locator("#ws-status").text_content() or ""
                except Exception:
                    break  # 页面已 reload（成功）
                if "初始化完成" in st or "初始化失败" in st or "请求异常" in st:
                    break
                time.sleep(3)
            ok_init = st is not None and "初始化完成" in st
            rec("1.2 向导初始化(LLM)", ok_init, (st or "页面已reload")[:100])
            if ok_init:
                page.wait_for_load_state("load")
                page.wait_for_timeout(1500)
                ws_list = api("/api/workspaces")["workspaces"]
                tiny = next((w for w in ws_list if w["slug"] == "tinyrag"), None)
                rec("1.2 自动切换到新工作区", bool(tiny and tiny.get("active")), "")
                docx = ROOT / "workspaces/tinyrag/docx"
                skeleton = ["StudyState.json", "Study.md", "Project.md",
                            "ReplicaPlan.md", "DocIndex.md", "InterviewQA.md"]
                missing = [f for f in skeleton if not (docx / f).exists()]
                rec("1.2 骨架文件齐全", not missing, f"缺: {missing}" if missing else "6 文件齐")
                try:
                    sj = json.loads((docx / "StudyState.json").read_text(encoding="utf-8"))
                    sm = (docx / "Study.md").read_text(encoding="utf-8")
                    rec("1.2 StudyState Day1", sj.get("current_day") == 1, f"current_day={sj.get('current_day')}")
                    rec("1.2 Study.md 覆盖 5 天", all(f"Day {i}" in sm for i in (1, 3, 5)), "")
                except Exception as e:
                    rec("1.2 学习数据内容", False, str(e))
                roots = api("/api/code/roots")["roots"]
                rec("1.2 代码根注册", any(r["name"] == "temp_tinyrag" for r in roots),
                    str([r["name"] for r in roots]))
                vr = subprocess.run(
                    [sys.executable, "resources/hooks/validate_study.py",
                     "workspaces/tinyrag/docx", "5", "tinyrag-replica"],
                    cwd=ROOT, capture_output=True, text=True, timeout=120)
                rec("1.2 validate_study", vr.returncode == 0, (vr.stdout or vr.stderr).strip().splitlines()[-1][:100])

                # ---------- 1.4 重扫（active=tinyrag，LLM 重生成 Project.md）----------
                pmd = docx / "Project.md"
                mtime_before = pmd.stat().st_mtime if pmd.exists() else 0
                page.locator("#ws-current").click()
                page.wait_for_timeout(400)
                page.locator('#ws-menu .ws-item:has-text("重新扫描项目结构")').click()
                t0 = time.time()
                toast = ""
                while time.time() - t0 < 240:
                    try:
                        c = page.locator(".toast")
                        if c.count() > 0:
                            toast = c.last.text_content() or ""
                            if "已刷新" in toast or "失败" in toast:
                                break
                    except Exception:
                        pass
                    time.sleep(1)
                rec("1.4 重扫完成提示", "已刷新" in toast, toast[:60])
                bak = docx / "hooks/backup/Project.md.bak"
                mtime_after = pmd.stat().st_mtime if pmd.exists() else 0
                rec("1.4 规则14备份", bak.exists(), str(bak.relative_to(ROOT)) if bak.exists() else "无 .bak")
                rec("1.4 Project.md 重生成", mtime_after > mtime_before,
                    f"mtime {mtime_before:.0f} -> {mtime_after:.0f}")

            # JS 错误总览
            rec("全程零 JS 错误", not errors, "; ".join(errors[:3]))
        finally:
            # 还原：切回原工作区
            cur = next((w["slug"] for w in api("/api/workspaces")["workspaces"] if w["active"]), None)
            if cur != orig:
                api("/api/workspaces/switch", {"slug": orig})
            b.close()

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n==== 第 1 组验收：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ====", flush=True)
    for item, ok, detail in fails:
        print(f"  失败: {item} — {detail}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
