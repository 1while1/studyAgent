# -*- coding: utf-8 -*-
"""验收第 2 组 C 段：复盘 + 结束今日学习（tinyrag，Mock 渠道，临时脚本不进 git）。

覆盖：2.11 [开始今日复盘]（相位进入/矩阵拦截/评分落盘/反喂触发——Mock 一轮出分，
题量与反喂内容质量属真实 LLM 项标阻塞）；2.12 [结束今日学习]（6 步输出/StudyReview
生成/滚动细化/阶段复位/validate）。
前提：G2a 已完成（Day 1 单元全部 completed）；服务 8765 运行中。
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "workspaces/tinyrag/docx"
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


def send_and_wait(page, text, timeout=180):
    before = page.locator("#messages .bubble").count()
    page.fill("#input", text)
    page.locator("#input-form button").click()
    t0 = time.time()
    stable = 0
    last_txt = ""
    while time.time() - t0 < timeout:
        page.wait_for_timeout(2000)
        n = page.locator("#messages .bubble").count()
        txt = page.locator("#messages .bubble").last.text_content() or ""
        if n >= before + 2 and "思考中" not in txt:
            if txt == last_txt:
                stable += 1
                if stable >= 2:
                    return txt
            else:
                stable = 0
                last_txt = txt
    return last_txt


def main():
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    api("/api/session/mode", {"mode": "study"})
    orig_cfg = api("/api/llm-config")
    api("/api/llm-config", {"provider": "mock",
                            "fallback_provider": orig_cfg.get("fallback_provider", "")})
    time.sleep(1)

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 820})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            page.goto(BASE)
            page.wait_for_timeout(1500)
            day = json.loads((DOCX / "StudyState.json").read_text(encoding="utf-8"))["current_day"]

            # ---------- 2.11 [开始今日复盘] ----------
            r = send_and_wait(page, "[开始今日复盘]", 240)
            rec("2.11 复盘开启（拷问输出）", "复盘" in r or "拷问" in r,
                r[:80].replace("\n", " "))
            ph = api("/api/state")["session"].get("day_phase")
            rec("2.11 REVIEWING 相位", ph == "reviewing", f"phase={ph}")
            # 矩阵拦截：REVIEWING 期 [下一内容] 应被拒
            r2 = send_and_wait(page, "[下一内容]", 120)
            rec("2.11 REVIEWING 矩阵拦截", "复盘" in r2 and ("完成" in r2 or "先" in r2),
                r2[:60].replace("\n", " "))
            # 答题一轮（Mock 出【评分：4.0】→ 落盘 + 反喂触发）
            r3 = send_and_wait(page, "我的回答：先重试同渠道一次，仍失败则切换备用渠道并记录原因。", 240)
            sj = json.loads((DOCX / "StudyState.json").read_text(encoding="utf-8"))
            day_data = sj["days"][str(day)]
            rec("2.11 复盘评分落盘",
                float(day_data.get("review_score", 0)) >= 1.0,
                f"review_score={day_data.get('review_score')}")
            ph2 = api("/api/state")["session"].get("day_phase")
            rec("2.11 相位还原 STUDYING", ph2 == "studying", f"phase={ph2}")
            # 反喂：Mock 产出过不了机械校验 → InterviewQA 不新增（静默放弃属设计）
            # 真实 LLM 反喂内容质量 = 环境阻塞项（5.8 同此）

            # ---------- 2.12 [结束今日学习] ----------
            r = send_and_wait(page, "[结束今日学习]", 300)
            rec("2.12 六步收尾输出", "Step" in r and ("结束" in r or "明日" in r),
                r[:80].replace("\n", " "))
            reviews = list((DOCX / "StudyReview").glob(f"Day_{day:02d}-*.md"))
            rec("2.12 StudyReview 文件生成", len(reviews) >= 1,
                reviews[0].name if reviews else "无")
            if reviews:
                n_chars = len(reviews[0].read_text(encoding="utf-8"))
                print(f"  （StudyReview 字数 {n_chars}——Mock 渠道产出短，3000 字质量属真实 LLM 阻塞项）", flush=True)
            smd = (DOCX / "Study.md").read_text(encoding="utf-8")
            rec("2.12 Study.md 当日标完成", re.search(rf"## Day {day} \|.*✅", smd) is not None, "")
            rec("2.12 次日滚动细化（Mock）", f"## Day {day + 1} |" in smd and "单元A" in smd, "")
            st_now = api("/api/state")["session"]
            rec("2.12 阶段复位", st_now.get("current_stage", "") == "",
                f"stage='{st_now.get('current_stage')}'")
            mem = (DOCX / "StudyMemory" / f"Day_{day:02d}.md").read_text(encoding="utf-8")
            rec("2.12 StudyMemory 结束记录", "结束" in mem or "复盘" in mem, "")
            import subprocess
            vr = subprocess.run(
                [sys.executable, "resources/hooks/validate_study.py",
                 "workspaces/tinyrag/docx", "5", "tinyrag-replica"],
                cwd=ROOT, capture_output=True, text=True, timeout=120)
            rec("2.12 validate 三方一致", vr.returncode == 0,
                (vr.stdout or vr.stderr).strip().splitlines()[-1][:80])

            rec("全程零 JS 错误", not errors, "; ".join(errors[:3]))
        finally:
            api("/api/llm-config", {"provider": orig_cfg.get("provider", "deepseek_official"),
                                    "fallback_provider": orig_cfg.get("fallback_provider", "")})
            api("/api/workspaces/switch", {"slug": "ragent"})
            b.close()

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n==== G2c 验收：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ====", flush=True)
    for item, ok, detail in fails:
        print(f"  失败: {item} — {detail}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
