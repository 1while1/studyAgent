# -*- coding: utf-8 -*-
"""验收第 5 组：笔记与话术手动项（tinyrag 工作区，API 驱动）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖：5.4 日志蒸馏（去重幂等）/ 5.5 合并（keep 序+残骸 merged_into+不写证据）/
5.6 待挂接条目 concept 挂接（挂接后销账写证据）/ 5.3 销账幂等。
5.1/5.2/5.7 走查 9g/9h、5.8 test_qa_capture、5.9 test_arch_fixes_a 打勾。
前提：服务 8765 运行中。结束还原：活动工作区、tinyrag 全部数据文件。
"""
import json
import shutil
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g5_bak"
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
        # ---- 5.4 日志蒸馏（去重幂等） ----
        r1 = api("/api/notes/distill", {})
        r2 = api("/api/notes/distill", {})
        rec("5.4 日志蒸馏：首次 added>=0 + 二次去重",
            r1.get("ok", True) and r2.get("added", 1) == 0,
            f"added={r1.get('added')} → {r2.get('added')}")

        # ---- 5.5 合并：keep 序 + 残骸 merged_into + 不写证据 ----
        a = api("/api/notes/add", {"kind": "stuck", "text": "G5验收 背压机制不懂"})["note"]
        b = api("/api/notes/add", {"kind": "stuck", "text": "G5验收 SSE 背压是什么"})["note"]
        before = json.loads((WS / "docx/learner_model.json").read_text(encoding="utf-8"))
        mg = api("/api/notes/merge", {"keep": a["id"], "others": [b["id"]]})
        notes = {n["id"]: n for n in api("/api/notes")["notes"]}
        after = json.loads((WS / "docx/learner_model.json").read_text(encoding="utf-8"))
        wreck = notes.get(b["id"], {})
        rec("5.5 合并：keep 文本吸收 + 残骸 merged_into + 不写证据",
            mg.get("ok") and "SSE 背压是什么" in mg["note"]["text"]
            and wreck.get("merged_into") == a["id"]
            and before == after,
            f"merged_into={wreck.get('merged_into')}")

        # ---- 5.6 待挂接条目 concept 挂接 → 销账写证据；5.3 幂等 ----
        c = api("/api/notes/add", {"kind": "stuck",
                                   "text": "G5验收 待挂接条目"})["note"]
        rec("5.6 前置：无 concept 条目为待挂接态",
            c.get("status") in ("needs_review", "open") and not c.get("concept_id"),
            f"status={c.get('status')}")
        up = api("/api/notes/update", {"id": c["id"], "concept_id": "Day1-A"})
        rec("5.6 concept 挂接（服务端 update）",
            up.get("ok") and up["note"].get("concept_id") == "Day1-A",
            json.dumps(up, ensure_ascii=False)[:100])
        rs1 = api("/api/notes/resolve", {"id": c["id"]})
        m1 = json.loads((WS / "docx/learner_model.json").read_text(encoding="utf-8"))
        ev1 = [e for e in m1["concepts"].get("Day1-A", {}).get("evidence", [])
               if e.get("type") == "note_distilled"]
        rs2 = api("/api/notes/resolve", {"id": c["id"]})
        m2 = json.loads((WS / "docx/learner_model.json").read_text(encoding="utf-8"))
        ev2 = [e for e in m2["concepts"].get("Day1-A", {}).get("evidence", [])
               if e.get("type") == "note_distilled"]
        rec("5.3 销账：note_distilled 证据落盘 + 幂等（二次不重复）",
            len(ev1) >= 1 and len(ev2) == len(ev1),
            f"evidence {len(ev1)} → {len(ev2)}")

        # 清理自建笔记（还原双保险）
        for nid in (a["id"], b["id"], c["id"]):
            api("/api/notes/delete", {"id": nid})
    finally:
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.rmtree(WS / "docx")
        shutil.copytree(BAK / "docx", WS / "docx")
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK)

    fails = [i for i, ok in RESULTS if not ok]
    print(f"\n== G5 手动项：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ==")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
