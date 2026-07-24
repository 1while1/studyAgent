# -*- coding: utf-8 -*-
"""验收第 6 组：资料库手动项（tinyrag 工作区，API 驱动）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖：6.3 重扫（mtime 变化重解析）+ 手工注册外部文件/视频链接。
6.1 走查 9d / 6.2 走查 9k / 6.4 test_materials（docx 损坏回退+pdf 分页）/
6.5 test_materials.test_scan_txt_md_and_skip_sensitive 打勾。
前提：服务 8765 运行中。结束还原：活动工作区、tinyrag 全部数据文件。
"""
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g6_bak"
MAT = ROOT / "runtime/_accept_g6_mat"
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
        # ---- 6.3 手工注册：外部文件 + 视频链接 ----
        MAT.mkdir(parents=True, exist_ok=True)
        ext = MAT / "外部教材.md"
        ext.write_text("# 第一章 RAG\n检索增强生成。\n", encoding="utf-8")
        r1 = api("/api/materials/register", {"source": str(ext)})
        rec("6.3 手工注册外部文件", r1.get("ok") and r1.get("id"),
            json.dumps(r1, ensure_ascii=False)[:100])
        r2 = api("/api/materials/register",
                 {"source": "https://example.com/watch?v=g6accept"})
        rec("6.3 视频链接登记（video_link 仅登记不解析）",
            r2.get("ok") and r2.get("type") == "video_link",
            json.dumps(r2, ensure_ascii=False)[:100])

        # ---- 6.3 重扫：mtime 变化触发重解析（文件须在 materials_dir 内，
        # scan() 只遍历该目录；tinyrag 默认无 materials_dir → 临时配置 + reload） ----
        st = ROOT / "config/settings.toml"
        st_bak = st.read_text(encoding="utf-8")
        tinyrag_sec = 'slug = "tinyrag"'
        assert tinyrag_sec in st_bak
        # 直接在 tinyrag 节首插一行（节内键顺序无关）；前置防 TOML 重复键
        lines = st_bak.splitlines()
        idx = next(i for i, l in enumerate(lines) if l.strip() == tinyrag_sec)
        sec_tail = "\n".join(lines[idx:idx + 12])
        assert "materials_dir" not in sec_tail, "tinyrag 节已有 materials_dir"
        lines.insert(idx + 1, 'materials_dir = "runtime/_accept_g6_mat"')
        st.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            api("/api/config/reload", {})
            scan_file = MAT / "扫描教材.md"
            scan_file.write_text("# 第一章 RAG\n检索增强生成。\n", encoding="utf-8")
            api("/api/materials/rescan", {})
            b = next((m for m in api("/api/materials")["materials"]
                      if m["id"] == "扫描教材"), {})
            import os
            scan_file.write_text("# 第一章 RAG\n检索增强生成。\n# 第二章 向量\n嵌入。\n",
                                 encoding="utf-8")
            os.utime(scan_file, (time.time() + 5, time.time() + 5))  # mtime 粒度保险
            rs = api("/api/materials/rescan", {})
            a = next((m for m in api("/api/materials")["materials"]
                      if m["id"] == "扫描教材"), {})
            rec("6.3 重扫：mtime 变化触发重解析（章节 1→2）",
                b.get("headings") == 1 and a.get("headings") == 2,
                f"headings {b.get('headings')} → {a.get('headings')}, "
                f"reparsed={rs.get('stats', {}).get('reparsed')}")
        finally:
            st.write_text(st_bak, encoding="utf-8")
            api("/api/config/reload", {})

        # ---- 6.5 旁证：敏感文件注册被拒 ----
        (MAT / ".env").write_text("SECRET=x", encoding="utf-8")
        r3 = api("/api/materials/register", {"source": str(MAT / ".env")})
        rec("6.5 敏感文件（.env）注册被拒",
            not r3.get("ok") and "敏感" in r3.get("error", ""),
            json.dumps(r3, ensure_ascii=False)[:80])
    finally:
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.rmtree(WS / "docx")
        shutil.copytree(BAK / "docx", WS / "docx")
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK)
        shutil.rmtree(MAT, ignore_errors=True)

    fails = [i for i, ok in RESULTS if not ok]
    print(f"\n== G6 手动项：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ==")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
