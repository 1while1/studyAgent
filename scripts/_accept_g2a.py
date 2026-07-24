# -*- coding: utf-8 -*-
"""验收第 2 组 A 段：学习流程手动项（tinyrag 工作区，真实 LLM，临时脚本不进 git）。

覆盖：2.3 [下一内容] 全流程 / 2.4 [强制下一内容] / 2.6 [同步] 五子类 /
2.7 [开始写代码]（scored 阶段正向 + first 阶段 fail_fast）。
前提：服务 8765 运行中；tinyrag 工作区已初始化（G1 重建），Day 1 未开始。
结束切回 ragent。
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
    """发送消息/指令，等流式完成，返回新 AI 气泡文本。"""
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
                if stable >= 2:  # 文本 4s 稳定 = 流式结束
                    return txt
            else:
                stable = 0
                last_txt = txt
    return last_txt


def load_state():
    return json.loads((DOCX / "StudyState.json").read_text(encoding="utf-8"))


def load_memory(day):
    p = DOCX / "StudyMemory" / f"Day_{day:02d}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def quiz_two_rounds(page, unit_label):
    """当前单元走完 quiz_r1→r2→scored。返回是否出现评分标记。"""
    a1 = send_and_wait(page, "我的回答：这是核心概念的综合运用，通过统一抽象与分层协作完成。", 180)
    print(f"  [{unit_label} r1 点评] {a1[:80]}...", flush=True)
    a2 = send_and_wait(page, "我的回答：底层基于事件驱动与状态机迁移，面试中强调权衡点。", 180)
    print(f"  [{unit_label} r2 点评] {a2[:80]}...", flush=True)
    return "【评分：" in a2 or "【评分:" in a2


def main():
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    api("/api/session/mode", {"mode": "study"})
    # 真实 LLM 渠道全灭（opencode 401 风控 / DeepSeek 402 余额）→ Mock 驱动流程验收
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

            # ---------- 2.1 [开始今日学习]（手动复验） ----------
            r = send_and_wait(page, "[开始今日学习]", 240)
            rec("2.1 开始今日学习-四步输出",
                "Step 1" in r and "Step 3" in r and "导学单元" in r,
                r[:100].replace("\n", " "))
            rec("2.1 无 LLM 错误泡", page.locator(".msg.error").count() == 0, "")
            # start_day 后单元才注册进 StudyState（days 空是全新工作区合法态）
            st = load_state()
            day = st["current_day"]
            units = st["days"][str(day)]["units"]
            print(f"  tinyrag Day {day}，单元：{[u['id'] for u in units]}", flush=True)

            # ---------- 2.3 [下一内容] 全流程（单元 A） ----------
            r = send_and_wait(page, "[下一内容]", 240)
            check_ok = ("掌握情况检查" in r and "已讲解" in r and "卡点" in r
                        and "编码进度" in r)
            rec("2.3 掌握情况检查模板（5字段）", check_ok, r[:80].replace("\n", " "))
            scored = quiz_two_rounds(page, "单元A")
            rec("2.3 两轮追问出评分标记", scored, "")
            r = send_and_wait(page, "[下一内容]", 240)
            st = load_state()
            ua = next(u for u in st["days"][str(day)]["units"] if u["id"] == "A")
            mem = load_memory(day)
            rec("2.3 评分落盘推进（StudyState）",
                ua["status"] == "completed" and 1.0 <= float(ua.get("rating", 0)) <= 5.0,
                f"status={ua['status']} rating={ua.get('rating')}")
            rec("2.3 StudyMemory 勾选+评分",
                "- [x] 单元A" in mem and re.search(r"单元A：\d+(?:\.\d+)?分", mem) is not None, "")
            lm_path = DOCX / "learner_model.json"
            ev = []
            if lm_path.exists():
                lm = json.loads(lm_path.read_text(encoding="utf-8"))
                ev = [e for c in lm.get("concepts", {}).values()
                      for e in c.get("evidence", [])]
            rec("2.3 学习者证据落盘", len(ev) >= 1,
                f"{len(ev)} 条: {[e.get('type') for e in ev][:4]}")
            rec("2.3 推进下一单元开场", "单元B" in r or "单元 B" in r,
                r[:60].replace("\n", " "))

            # ---------- 2.4 [强制下一内容]（单元 B） ----------
            r = send_and_wait(page, "[强制下一内容]", 240)
            st = load_state()
            ub = next((u for u in st["days"][str(day)]["units"] if u["id"] == "B"), None)
            mem = load_memory(day)
            if ub is not None:
                rec("2.4 强制跳过落盘",
                    ub["status"] == "completed" and float(ub.get("rating", 0)) == 2.0,
                    f"status={ub['status']} rating={ub.get('rating')}")
                rec("2.4 薄弱标记", "（未掌握-跳过）" in mem, "")
            else:
                rec("2.4 强制跳过落盘", False, "无单元B（单元数<2）")

            # ---------- 2.6 [同步] 五子类 ----------
            syncs = [
                ("已掌握", "事件驱动架构的核心流转"),
                ("卡壳", "背压与拉模式的边界条件"),
                ("疑问", "为什么首包探测后还要二次协商？"),
                ("面试话术", "背压设计三要素：缓冲、丢弃策略、上游通知"),
                ("代码完成", "tinyrag-replica day01 骨架"),
            ]
            for sub, content in syncs:
                r = send_and_wait(page, f"[同步] {sub} {content}", 120)
            mem = load_memory(day)
            hits = [s for s, c in syncs if any(
                w in mem for w in ([s, s.replace("已", "已")]) ) and c[:6] in mem]
            mem_ok = all(c[:8] in mem for _, c in syncs)
            rec("2.6 五子类落盘 StudyMemory", mem_ok,
                f"缺失: {[c[:8] for _, c in syncs if c[:8] not in mem]}")
            notes = json.loads((DOCX / "notes.json").read_text(encoding="utf-8")) \
                if (DOCX / "notes.json").exists() else {"notes": []}
            kinds = {n.get("kind") for n in notes.get("notes", [])}
            rec("2.6 自动产笔记条目（掌握/卡壳/疑问）",
                {"mastered", "stuck", "question"} <= kinds, str(kinds))
            qa = (DOCX / "InterviewQA.md").read_text(encoding="utf-8")
            rec("2.6 面试话术入 InterviewQA", "背压设计三要素" in qa, "")
            rec("2.6 疑问带待解答后缀", "（待解答）" in mem, "")

            # ---------- 2.8 [验证代码]（temp_tinyrag 根 pom.xml，maven 构建） ----------
            lm_path = DOCX / "learner_model.json"
            r = send_and_wait(page, "[验证代码]", 420)
            rec("2.8 构建回喂（结果+点评）",
                "LLM 调用失败" not in r and ("编译" in r or "构建" in r or "BUILD" in r or "成功" in r),
                r[:100].replace("\n", " "))
            ev_types = []
            if lm_path.exists():
                lm = json.loads(lm_path.read_text(encoding="utf-8"))
                ev_types = [e.get("type") for c in lm.get("concepts", {}).values()
                            for e in c.get("evidence", [])]
            rec("2.8 构建证据落盘（code_verify_pass/fail）",
                any(t in ("code_verify_pass", "code_verify_fail") for t in ev_types),
                f"evidence: {ev_types[-3:] if ev_types else '无'}")

            # ---------- 2.7 [开始写代码] ----------
            # 当前单元 C 处于 first 阶段 → fail_fast 拒绝（负向）
            r = send_and_wait(page, "[开始写代码]", 120)
            rec("2.7 first 阶段 fail_fast", "先把理论讲完" in r or "导读阶段" in r,
                r[:60].replace("\n", " "))
            # 单元 C 走 quiz 到 scored → [开始写代码] 正向
            send_and_wait(page, "[下一内容]", 240)  # 掌握情况检查 + r1
            quiz_two_rounds(page, "单元C")
            r = send_and_wait(page, "[开始写代码]", 240)
            st_now = api("/api/state")
            rec("2.7 scored 阶段进入 coding（fail_fast 通过）",
                st_now["session"]["current_stage"] == "coding" and len(r) > 10,
                f"stage={st_now['session']['current_stage']}, 响应 {len(r)} 字符")
            # [强制下一内容] 落盘单元 C → 今日全部完成
            r = send_and_wait(page, "[强制下一内容]", 240)
            st = load_state()
            all_done = all(u["status"] == "completed"
                           for u in st["days"][str(day)]["units"])
            rec("2.7 今日单元全部完成", all_done and "全部完成" in r,
                r[:60].replace("\n", " "))

            rec("全程零 JS 错误", not errors, "; ".join(errors[:3]))
        finally:
            api("/api/llm-config", {"provider": orig_cfg.get("provider", "deepseek_official"),
                                    "fallback_provider": orig_cfg.get("fallback_provider", "")})
            api("/api/workspaces/switch", {"slug": "ragent"})
            b.close()

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n==== G2a 验收：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ====", flush=True)
    for item, ok, detail in fails:
        print(f"  失败: {item} — {detail}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
