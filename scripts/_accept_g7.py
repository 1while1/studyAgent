# -*- coding: utf-8 -*-
"""验收第 7 组：实战工坊手动项（tinyrag 工作区，API + 真实 npm）。

（验收脚本统一入库，G 组全结束后随清理任务一并删除。）

覆盖：7.1 三类型脚手架 + {{name}} 替换 + 代码根注册（API 侧）/ 7.2 npm demo
离线构建与自测（真实 node/npm）。
7.3/7.5 走查 8b、7.4 走查 7/8、7.6 走查 9k、7.7 test_tool_registry+test_workshop、
7.8 test_arch_fixes_b（超时杀树）打勾。
前提：服务 8765 运行中；node/npm 可用（nvm 路径兜底）。结束还原全部改动。
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workspaces/tinyrag"
BAK = ROOT / "runtime/_accept_g7_bak"
NVM = Path(os.environ.get("APPDATA", "")) / "nvm/v18.20.8"
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
        return json.loads(urllib.request.urlopen(req, timeout=180).read())
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
    roots_before = {r["name"] for r in api("/api/code/roots")["roots"]}
    demo_dir = None
    try:
        # ---- 7.1 脚手架三类型 + {{name}} 替换 + 代码根注册 ----
        types = {s["type"] for s in api("/api/demo/scaffolds")["scaffolds"]}
        rec("7.1 三类型脚手架可用", {"npm", "maven-module", "gradle"} <= types,
            f"types={sorted(types)}")
        r = api("/api/demo/scaffold", {"type": "npm", "name": "g7demo"})
        rec("7.1 npm demo 创建", r.get("ok"), json.dumps(r, ensure_ascii=False)[:100])
        roots_after = api("/api/code/roots")["roots"]
        demo_root = next((x for x in roots_after if x["name"] == "demo"), None)
        rec("7.1 代码根自动注册", demo_root is not None,
            f"roots={sorted(x['name'] for x in roots_after)}")
        if demo_root:
            demo_dir = Path(demo_root["path"]) / "g7demo"
            pkg = (demo_dir / "package.json").read_text(encoding="utf-8")
            rec("7.1 {{name}} 替换", '"name": "g7demo"' in pkg)

            # ---- 7.2 npm demo 离线构建 + 自测（真实 node） ----
            env = dict(os.environ)
            env["PATH"] = str(NVM) + os.pathsep + env.get("PATH", "")
            npm = str(NVM / "npm.cmd")

            def run_npm(*args):
                p = subprocess.run([npm, *args], cwd=demo_dir, env=env,
                                   capture_output=True, timeout=120)
                out = ((p.stdout or b"") + (p.stderr or b"")).decode(
                    "utf-8", errors="replace")
                return p.returncode, out

            code, out = run_npm("run", "build")
            rec("7.2 npm run build 离线构建", code == 0, out[-120:].replace("\n", " "))
            code, out = run_npm("test")
            rec("7.2 npm test 自测", code == 0, out[-120:].replace("\n", " "))
    finally:
        if demo_dir and demo_dir.exists():
            shutil.rmtree(demo_dir, ignore_errors=True)
        if "demo" not in roots_before:  # 先删 tinyrag 的 demo 根再切回（顺序敏感）
            api("/api/code/roots", {"name": "demo"}, method="DELETE")
        api("/api/workspaces/switch", {"slug": orig_ws})
        shutil.rmtree(WS / "docx")
        shutil.copytree(BAK / "docx", WS / "docx")
        shutil.copy2(BAK / "session.json", WS / "session.json")
        shutil.rmtree(BAK)

    fails = [i for i, ok in RESULTS if not ok]
    print(f"\n== G7 手动项：{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 ==")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
