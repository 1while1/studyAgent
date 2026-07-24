# -*- coding: utf-8 -*-
"""验收第 3 组：AI 导学质量手动项（tinyrag 工作区，Mock 渠道，临时脚本不进 git）。

覆盖：3.1 备课确定性预取（📚 chip）/ 3.4 感召式复习（Step1 上游感召）/
3.5 回合复习（5 轮后自动渲染掌握情况检查）/ 3.6 间隔复习（Step1 日历到期项）。
3.2（走查 9c）、3.3（test_tool_use READ_DOC）、3.7（走查 7c）由既有覆盖打勾。
前提：服务 8765 运行中。结束还原：LLM 渠道、活动工作区、tinyrag 全部数据文件。
"""
import json
import shutil
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
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g3_bak"
MAT = ROOT / "runtime/_accept_g3_mat"
RESULTS = []


def rec(item, ok, detail=""):
    print(("✅" if ok else "❌") + f" {item}" + (f" — {detail}" if detail else ""), flush=True)
    RESULTS.append((item, ok))


def api(path, payload=None, method=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"))
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read()[:200]}"}


def send_and_wait(page, text, timeout=120):
    before = page.locator("#messages .bubble").count()
    page.fill("#input", text)
    page.locator("#input-form button").click()
    t0, stable, last_txt = time.time(), 0, ""
    while time.time() - t0 < timeout:
        page.wait_for_timeout(1500)
        n = page.locator("#messages .bubble").count()
        txt = page.locator("#messages .bubble").last.text_content() or ""
        if n >= before + 2 and "思考中" not in txt:
            if txt == last_txt:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable, last_txt = 0, txt
    texts = page.locator("#messages .bubble").all_text_contents()
    return "\n".join(texts[before + 1:])


def main():
    # ---- 0. 备份 + 渠道/工作区切换 ----
    orig_cfg = api("/api/llm-config")
    orig_ws = api("/api/workspaces")["active"]
    if BAK.exists():
        shutil.rmtree(BAK)
    BAK.mkdir(parents=True)
    shutil.copytree(WS / "docx", BAK / "docx")
    shutil.copy2(WS / "session.json", BAK / "session.json")
    api("/api/llm-config", {"provider": "mock",
                            "fallback_provider": orig_cfg.get("fallback_provider", ""),
                            "warmup_on_start": False, "sections": {}})
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    try:
        # ---- 1. 造数：资料（3.1）+ Day1 卡壳/疑问（3.6）----
        MAT.mkdir(parents=True, exist_ok=True)
        readme = MAT / "README.md"
        readme.write_text("# TinyRAG 教材\n\nRAG = 检索增强生成：先检索相关文档片段，"
                          "再交给大模型生成答案。\n\n## 核心流程\n上传→解析→向量化→检索→生成。\n",
                          encoding="utf-8")
        r = api("/api/materials/register", {"source": str(readme)})
        rec("3.1 前置：教材注册", r.get("ok", False), str(r)[:80])

        # Day 2 已结束（active_day_completed=true），start_day 递进 Day 3。
        # 按 Day 3 造数：间隔复习项改 Day_02.md 既有同步段（3-2=1 ∈ [1,3,7]；
        # 注意不能追加第二个 ### [同步] 记录 段——sync_items 只读第一段且遇「无」即返）；
        # Day 3 单元A doc 临时改 README.md（3.1 预取命中注册教材）。
        import re as _re
        day2 = WS / "docx/StudyMemory/Day_02.md"
        content = day2.read_text(encoding="utf-8")
        content = _re.sub(r"^- 卡壳：无$", "- 卡壳：Tika 解析机制没听懂",
                          content, count=1, flags=_re.M)
        content = _re.sub(r"^- 疑问：无$", "- 疑问：向量维度怎么选（待解答）",
                          content, count=1, flags=_re.M)
        assert "Tika 解析机制没听懂" in content, "Day_02.md 同步段定位失败"
        day2.write_text(content, encoding="utf-8")

        sm = WS / "docx/Study.md"
        sm_text = sm.read_text(encoding="utf-8")
        old_unit = ("1. [ ] 单元A：SseEmitter流式响应机制（预计 40min）\n"
                    "   - 文档：tinyrag-bootstrap/src/main/java/com/nageoffer/ai/tinyrag/TinyragApplication.java")
        assert old_unit in sm_text, "Day 3 单元A 定位失败"
        sm.write_text(sm_text.replace(
            old_unit,
            "1. [ ] 单元A：SseEmitter流式响应机制（预计 40min）\n   - 文档：README.md", 1),
            encoding="utf-8")

        # ---- 2. UI：开始今日学习（Day 2  fresh start）----
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(1500)
            out = send_and_wait(page, "[开始今日学习]", 180)
            rec("3.4 感召式复习：Step1 出现上游感召", "上游感召·Day" in out,
                "" if "上游感召·Day" in out else out[:300])
            page.wait_for_timeout(1000)
            chip = page.locator(".tool-chip.doc-chip")
            chip_txt = chip.first.text_content() if chip.count() else ""
            rec("3.1 备课预取：📚 chip 出现", chip.count() >= 1 and "已备课" in (chip_txt or ""),
                chip_txt or "无 chip")

            # ---- 3. 回合复习：5 轮对话后自动渲染掌握情况检查 ----
            got = ""
            for i in range(5):
                got = send_and_wait(page, f"继续讲解第{i + 1}部分")
            rec("3.5 回合复习：5 轮后自动渲染掌握情况检查",
                "【掌握情况检查】" in got and "已到回合复习点" in got,
                "" if "【掌握情况检查】" in got else got[-200:])

            # ---- 4. 间隔复习（3.6）：先造「上游全达标」清出感召占位 ----
            # （merged = 感召 + 日历 封顶 6，感召 7 项会挤掉日历项——设计如此，
            #  故 3.6 需在无感召场景验证）
            evs = lambda cid: (
                [{"type": "quiz_right", "delta": 0.10, "ts": "2026-07-24",
                  "source_ref": f"g3:{cid}:{i}"} for i in range(6)]
                + [{"type": "code_verify_pass", "delta": 0.20, "ts": "2026-07-24",
                    "source_ref": f"g3:{cid}:v"}])
            model = {"schema_version": 1, "concepts": {
                cid: {"title": cid, "mastery": 0.8, "evidence": evs(cid),
                      "last_review_day": 2, "review_due": []}
                for cid in ["Day1-A", "Day1-B", "Day1-C", "Day1-D",
                            "Day2-A", "Day2-B", "Day2-C"]}}
            (WS / "docx/learner_model.json").write_text(
                json.dumps(model, ensure_ascii=False), encoding="utf-8")
            out = send_and_wait(page, "重新开始今日学习", 180)
            rec("3.6 间隔复习：Step1 出现卡壳/疑问到期项",
                "卡壳·Day 2" in out and "疑问·Day 2" in out,
                "" if ("卡壳·Day 2" in out and "疑问·Day 2" in out) else out[:400])
            browser.close()
    finally:
        # ---- 4. 还原 ----
        api("/api/llm-config", orig_cfg)
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.rmtree(WS / "docx")
        shutil.copytree(BAK / "docx", WS / "docx")
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK)
        shutil.rmtree(MAT, ignore_errors=True)

    fails = [i for i, ok in RESULTS if not ok]
    print(f"\n== G3 手动项：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ==")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
