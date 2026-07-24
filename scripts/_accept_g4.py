# -*- coding: utf-8 -*-
"""验收第 4 组：学习者模型手动项（tinyrag 工作区，API 驱动）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖：4.1 concepts 自动注册（天内/跨天链）+ 材料挂接 / 4.2 evidence 三路写入实证 /
4.3 mastery 衰减 + 无 code_verify_pass 封顶 0.6 / 4.7 旧评分迁移预览→应用。
4.4/4.5/4.6（战术板/战略雷达/侧栏预警）由走查 9f 打勾。
前提：服务 8765 运行中。结束还原：活动工作区、tinyrag 全部数据文件。
"""
import json
import shutil
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g4_bak"
MAT = ROOT / "runtime/_accept_g4_mat"
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
    shutil.copytree(WS / "docx", BAK / "docx")
    shutil.copy2(WS / "session.json", BAK / "session.json")
    api("/api/workspaces/switch", {"slug": "tinyrag"})
    try:
        # ---- 4.1 concepts 自动注册 + 材料挂接 ----
        MAT.mkdir(parents=True, exist_ok=True)
        readme = MAT / "README.md"
        readme.write_text("# TinyRAG 教材\nRAG 内容。\n", encoding="utf-8")
        api("/api/materials/register", {"source": str(readme)})
        model = api("/api/learner/model")
        cmap = {c["id"]: c for c in model["concepts"]}
        day2a = cmap.get("Day2-A", {})
        rec("4.1 concepts 注册：天内链+跨天链",
            day2a.get("prerequisites") == ["Day1-D"],
            f"Day2-A prereqs={day2a.get('prerequisites')}")
        rec("4.1 材料挂接：单元 doc → 资料 id",
            "README" in day2a.get("materials", []),
            f"Day2-A materials={day2a.get('materials')}")

        # ---- 4.2 evidence 三路写入（G2a 真实流程沉淀） ----
        types = {e["type"] for c in model["concepts"] for e in c.get("evidence", [])}
        rec("4.2 evidence 三路：考核/同步/构建",
            {"quiz_right", "sync_mastered", "code_verify_pass"} <= types,
            f"types={sorted(types)}")

        # ---- 4.3 mastery 衰减 + 封顶 ----
        mp = WS / "docx/learner_model.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        old = (date.today() - timedelta(days=28)).isoformat()  # 2 个半衰期
        m["concepts"]["Day1-A"] = {
            "title": "Day1-A", "mastery": 0.4, "last_review_day": 1,
            "review_due": [],
            "evidence": [{"type": "quiz_right", "delta": 0.10, "ts": old,
                          "source_ref": f"g4:a:{i}"} for i in range(4)]}
        m["concepts"]["Day1-B"] = {
            "title": "Day1-B", "mastery": 0.8, "last_review_day": 1,
            "review_due": [],
            "evidence": [{"type": "quiz_right", "delta": 0.10,
                          "ts": date.today().isoformat(),
                          "source_ref": f"g4:b:{i}"} for i in range(8)]}
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        model = api("/api/learner/model")
        cmap = {c["id"]: c for c in model["concepts"]}
        a, b = cmap["Day1-A"], cmap["Day1-B"]
        rec("4.3 衰减：28 天前 0.4 → ≈0.1（半衰期 14 天）",
            0.05 <= a["mastery"] <= 0.15, f"mastery={a['mastery']}")
        rec("4.3 封顶：无 code_verify_pass 0.8 → 0.6（capped 标记）",
            b["mastery"] == 0.6 and b["capped"] and not b["has_code_pass"]
            and b["uncapped"] >= 0.79,
            f"mastery={b['mastery']} capped={b['capped']} uncapped={b['uncapped']}")

        # ---- 4.7 旧评分迁移：预览 → 应用 ----
        (WS / "docx/learner_model.json").unlink()
        draft = WS / "docx/learner_model.draft.json"
        draft.unlink(missing_ok=True)
        prev = api("/api/learner/migrate/preview", {})
        rec("4.7 迁移预览", prev.get("ok") and prev.get("quiz_scores", 0) > 0,
            json.dumps(prev, ensure_ascii=False)[:120])
        applied = api("/api/learner/migrate/apply", {})
        model = api("/api/learner/model")
        ev_types = {e["type"] for c in model["concepts"]
                    for e in c.get("evidence", [])}
        rec("4.7 迁移应用：模型重建 + 迁移证据落盘",
            applied.get("ok", True) and model["exists"] and len(ev_types) > 0,
            f"evidence types={sorted(ev_types)}")
    finally:
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.rmtree(WS / "docx")
        shutil.copytree(BAK / "docx", WS / "docx")
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK)
        shutil.rmtree(MAT, ignore_errors=True)

    fails = [i for i, ok in RESULTS if not ok]
    print(f"\n== G4 手动项：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ==")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
