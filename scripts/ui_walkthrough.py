"""UI 全功能走查（Playwright 无头浏览器真实点击）。

用法：服务运行中（8765）执行  python scripts/ui_walkthrough.py
覆盖：加载/指令/聊天/主题/侧栏/双布局/代码浏览器（Monaco）/片段卡片/弹窗/
面板控件/Mermaid 渲染/AI 读文件 tool-use（Mock 渠道全链路）/code 模式与
实战工坊（模式落盘/demo 脚手架/编辑保存/进程起停/面板显隐，存在性清理）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
ISSUES = []


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        ISSUES.append(f"{name}: {detail}")


def main():
    import urllib.request
    import json as _json

    def api(path, payload=None):
        req = urllib.request.Request(
            BASE + path,
            data=_json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET")
        return _json.loads(urllib.request.urlopen(req).read())

    # 走查固定 ragent 工作区（依赖其单元数与代码根），结束后还原
    ws_list = api("/api/workspaces")
    orig_ws = next((w["slug"] for w in ws_list["workspaces"] if w["active"]), None)
    if orig_ws != "ragent":
        api("/api/workspaces/switch", {"slug": "ragent"})
    # 会话模式归一化：残留 code 模式会让侧栏隐藏/指令走 guard（走查前提自愈）
    api("/api/session/mode", {"mode": "study"})

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 820})
        errors = []
        step = {"cur": "加载"}

        def mark(s):
            step["cur"] = s

        page.on("pageerror", lambda e: errors.append(
            f"<{step['cur']}> " +
            (str(e)[:150] + " | " + str(getattr(e, "stack", ""))[:250])))

        # ---- 1. 加载 ----
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(2000)
        check("页面加载-侧栏可见", page.locator("#sidebar").is_visible())
        check("页面加载-单元列表", page.locator("#units li").count() == 3)
        check("页面加载-指令胶囊 12 个", page.locator("#command-chips .chip").count() == 12)
        check("消息容器就绪", page.locator("#messages").is_visible())

        # ---- 2. 指令：FAIL-FAST ----
        page.locator("#command-chips .chip", has_text="开始今日学习").click()
        page.wait_for_timeout(3000)
        texts = page.locator("#messages .bubble").all_text_contents()
        check("FAIL-FAST 双选项输出", any("FAIL-FAST" in t for t in texts))
        check("FAIL-FAST 无残留思考泡", page.locator(".bubble.thinking").count() == 0)

        # ---- 3. 「[」指令补全菜单 ----
        page.fill("#input", "[恢复")
        page.wait_for_timeout(400)
        check("指令补全弹出", page.locator("#cmd-menu").is_visible())
        page.locator("#cmd-menu button").first.click()
        page.wait_for_timeout(300)
        check("补全回填输入框", page.locator("#input").input_value().startswith("[恢复学习]"))
        # ---- 3b. 工作区切换器 + 初始化向导 ----
        check("工作区下拉可见", page.locator("#ws-current").is_visible())
        page.locator("#ws-current").click()
        page.wait_for_timeout(400)
        check("工作区菜单项", page.locator("#ws-menu .ws-item").count() >= 3)
        check("工作区导出按钮", page.locator('#ws-menu .ws-op[data-op="export"]').count() >= 1)
        check("工作区删除按钮", page.locator('#ws-menu .ws-op[data-op="delete"]').count() >= 1)
        page.locator("#ws-menu .ws-item", has_text="新建工作区").click()
        page.wait_for_timeout(800)
        check("向导弹窗打开", page.locator("#ws-modal").is_visible())
        check("学习模式预设选项", page.locator("#ws-preset option").count() >= 4)
        page.fill("#ws-project-dir", "../ragent-replica")
        page.locator("#ws-preview-btn").click()
        page.wait_for_timeout(1200)
        check("扫描预览输出", len(page.locator("#ws-scan-preview").text_content()) > 50)
        page.locator("#ws-close").click()
        page.wait_for_timeout(300)

        # ---- 4. 侧栏收起/展开 ----
        page.locator("#toggle-sidebar").click()
        page.wait_for_timeout(400)
        check("侧栏收起后悬浮按钮", page.locator("#expand-sidebar").is_visible())
        page.locator("#expand-sidebar").click()
        page.wait_for_timeout(400)
        check("侧栏恢复", page.locator("#sidebar").is_visible())

        # ---- 5. 学习资料弹窗 ----
        page.locator("#open-docs").click()
        page.wait_for_timeout(1200)
        check("资料弹窗-标题", "StudyMemory" in page.locator("#doc-title").text_content())
        check("资料弹窗-渲染", page.locator("#doc-content h2, #doc-content h3").count() > 0)
        page.locator(".doc-tab[data-doc='interview_qa']").click()
        page.wait_for_timeout(800)
        page.locator("#doc-close").click()
        page.wait_for_timeout(400)

        # ---- 6. 模型配置弹窗 ----
        page.locator("#open-llm-config").click()
        page.wait_for_timeout(1200)
        check("配置弹窗可见", page.locator("#llm-modal").is_visible())
        check("配置弹窗-渠道数", page.locator(".provider-fieldset").count() == 2)
        check("配置弹窗-上下文窗口区", page.locator("#context-section").is_visible())
        page.locator("#ctx-budget").fill("128000")
        page.wait_for_timeout(200)
        check("上下文预算≈K 提示", "125K" in (page.locator("#ctx-budget-k").text_content() or ""))
        check("上下文预览含模型上限", "上限" in (page.locator("#ctx-preview").text_content() or ""))
        page.locator("#llm-close").click()
        page.wait_for_timeout(400)

        mark("7 代码浏览")
        # ---- 7. 源码学习模式 + 代码浏览器（M6：Monaco 宿主） ----
        page.locator("#mode-pair").click()
        page.wait_for_timeout(1500)
        check("源码学习-布局切换", page.evaluate("document.body.dataset.layout") == "pair")
        check("源码学习-侧栏隐藏", not page.locator("#sidebar").is_visible())
        check("代码面板打开", page.locator("#code-panel").is_visible())
        h1 = page.locator("#chat-topbar").evaluate("el=>el.offsetHeight")
        h2 = page.locator(".code-panel-head").evaluate("el=>el.offsetHeight")
        check("双头部对齐", h1 == h2, f"{h1} vs {h2}")
        # 双轴钉住：布局留在 pair，agent 模式回 study（7b 聊天仍走导学引擎，语义同旧走查）
        api("/api/session/mode", {"mode": "study"})
        check("双轴-模式回 study 布局不动", page.evaluate("document.body.dataset.layout") == "pair")
        page.locator("#code-root-select").select_option("ragent-replica")
        page.wait_for_timeout(800)
        page.evaluate("openCodeFile('ragent-replica','day01/src/main/java/com/my/ragent/day01/StreamingChatClient.java')")
        page.wait_for_timeout(2500)  # Monaco 首次动态加载（loader + editor.main）
        check("Monaco 动态加载", page.evaluate(
            "typeof monaco !== 'undefined' && !!window.__codeEditor"))
        check("文件打开-内容", "StreamingChatClient" in page.evaluate(
            "window.__codeEditor ? window.__codeEditor.getValue() : ''"))
        check("文件打开-高亮", page.locator(".code-content .view-line span").count() > 5)
        check("IDE 状态栏", "行" in page.locator("#csb-meta").text_content())
        # Monaco 选区 → 浮动按钮 → 插入
        page.evaluate("""(() => {
          window.__codeEditor.setSelection(new monaco.Selection(1, 1, 3, 20));
          document.dispatchEvent(new MouseEvent('mouseup', {clientX: 800, clientY: 350}));
        })()""")
        page.wait_for_timeout(400)
        check("浮动插入按钮", page.locator("#snippet-float").is_visible())
        page.locator("#snippet-float").click()
        page.wait_for_timeout(300)
        check("插入输入框", ":L" in page.locator("#input").input_value())
        # 换行保留（textarea 回归守卫：旧的单行 input 会吞掉 \n）
        check("片段换行保留", "\n" in page.locator("#input").input_value())
        # 面板控件
        page.locator("#code-tree-toggle").click()
        page.wait_for_timeout(300)
        check("树折叠", page.locator(".code-tree").evaluate("el => el.classList.contains('collapsed')"))
        page.locator("#code-tree-toggle").click()
        page.locator("#code-wrap-toggle").click()
        page.wait_for_timeout(300)
        check("换行模式", page.evaluate(
            "window.__codeEditor.getOption(monaco.editor.EditorOption.wordWrap)") == "on")
        page.locator("#code-wrap-toggle").click()

        mark("7c 引用芯片")
        # ---- 7c. 代码引用芯片（AI 回答中的路径 → 点击跳转 + 高亮） ----
        page.evaluate("addMessage('assistant', '请看 `ragent-replica/day01/pom.xml:L1-L3` 这个文件', true)")
        page.wait_for_timeout(300)
        check("代码引用芯片渲染", page.locator(".code-ref").count() >= 1)
        page.locator(".code-ref").last.click()
        page.wait_for_timeout(1500)
        check("引用跳转-文件打开", "pom.xml" in page.locator("#code-file-path").text_content())
        check("引用跳转-行高亮", page.locator(".line-flash-mc").count() >= 1)
        page.evaluate("addMessage('assistant', '再看 `no/such/File.java`', true)")
        page.wait_for_timeout(300)
        page.locator(".code-ref").last.click()
        page.wait_for_timeout(600)
        check("引用未找到-toast", page.locator(".toast").is_visible())

        mark("7b 片段提问")
        # ---- 7b. 发送片段提问 → 卡片渲染 → 刷新历史回填 ----
        page.locator("#input").press("End")
        page.type("#input", "只回复OK", delay=5)
        page.locator("#input-form button").click()
        page.wait_for_timeout(800)
        check("片段卡片渲染", page.locator(".snippet-jump").count() >= 1)
        ok = False
        for i in range(40):
            page.wait_for_timeout(4000)
            last = page.locator("#messages .bubble").last.text_content() or ""
            if "思考中" not in last and len(last.strip()) > 0:
                ok = True
                break
        check("片段提问流式完成", ok)
        check("片段提问无错误泡", page.locator(".msg.error").count() == 0,
              page.locator(".msg.error .bubble").first.text_content()[:100] if page.locator(".msg.error").count() else "")
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(2000)
        check("历史回填渲染卡片", page.locator(".snippet-jump").count() >= 1)

        mark("8 片段跳转")
        # ---- 8. 片段跳转 + 切回知识学习 ----
        page.locator(".snippet-jump").first.click()
        page.wait_for_timeout(2500)
        check("片段跳转-行高亮", page.locator(".line-flash-mc").count() >= 1)
        page.locator("#mode-tutor").click()
        page.wait_for_timeout(800)
        check("切回知识学习", page.evaluate("document.body.dataset.layout") == "tutor")
        check("知识学习-侧栏恢复", page.locator("#sidebar").is_visible())
        check("知识学习-代码面板隐藏", not page.locator("#code-panel").is_visible())

        mark("8b 实战工坊")
        # ---- 8b. code 模式 + 实战工坊（M6）：模式持久化/Monaco 编辑保存/
        #      demo 脚手架/进程起停/面板显隐；存在性感知清理（9c+ 同款） ----
        demo_root_existed = any(r["name"] == "demo"
                                for r in api("/api/code/roots")["roots"])
        wt_proc_id = None

        def _port_free(port):
            import socket
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False
            finally:
                s.close()

        try:
            # 模式切换 = 服务端 agent 状态落盘（双轴）
            page.locator("#mode-pair").click()
            page.wait_for_timeout(1200)
            check("code 模式落盘", api("/api/session/mode").get("mode") == "code")
            check("code 模式布局配对", page.evaluate("document.body.dataset.layout") == "pair")
            # 新建 demo（脚手架）
            page.locator("#demo-new").click()
            page.wait_for_timeout(600)
            check("demo 弹窗打开", page.locator("#demo-modal").is_visible())
            page.locator("#demo-type").select_option("npm")
            page.fill("#demo-name", "wt-demo")
            page.locator("#demo-create").click()
            page.wait_for_timeout(1800)
            check("demo 创建成功", "已创建 demo/wt-demo" in
                  (page.locator("#demo-msg").text_content() or ""))
            check("demo 代码根注册", any(r["name"] == "demo"
                  for r in api("/api/code/roots")["roots"]))
            page.wait_for_timeout(1000)  # 创建成功后弹窗 900ms 自动关闭
            check("demo 弹窗自动关闭", page.locator("#demo-modal").is_hidden())
            # Monaco 编辑 + 保存（demo 白名单可写）
            page.evaluate("openCodeFile('demo','wt-demo/src/app.js')")
            page.wait_for_timeout(1500)
            check("demo 文件可编辑", "可编辑" in
                  (page.locator("#csb-meta").text_content() or ""))
            check("保存按钮可见", page.locator("#code-save").is_visible())
            page.evaluate("window.__codeEditor.setValue('// walkthrough edit\\n')")
            page.wait_for_timeout(200)
            check("编辑后脏标记", page.locator("#code-save.dirty").count() == 1)
            page.evaluate("saveCurrentFile()")
            page.wait_for_timeout(800)
            back = api("/api/code/file?root=demo&path=wt-demo/src/app.js")
            check("保存回读一致", back.get("content") == "// walkthrough edit\n")
            # Y3 回归：每文件独立 model，undo 不跨文件污染
            page.evaluate("openCodeFile('demo','wt-demo/README.md')")
            page.wait_for_timeout(800)
            page.evaluate("window.__codeEditor.trigger('wt','undo','')")
            page.wait_for_timeout(200)
            check("undo 不跨文件污染", "walkthrough" not in
                  page.evaluate("window.__codeEditor.getValue()"))
            # 原项目只读（写白名单不含原项目）
            page.evaluate("openCodeFile('ragent原项目','frontend/index.html')")
            page.wait_for_timeout(1200)
            check("原项目只读标记", "只读" in
                  (page.locator("#csb-meta").text_content() or ""))
            check("原项目无保存钮", page.locator("#code-save").is_hidden())
            # 进程面板：启动 → 端口链接 → 日志 tail → 停止 → 端口释放
            page.locator("#proc-toggle").click()
            page.wait_for_timeout(600)
            check("进程抽屉打开", page.locator("#proc-drawer").is_visible())
            import socket as _sk
            _s = _sk.socket(); _s.bind(("127.0.0.1", 0))
            wt_port = _s.getsockname()[1]; _s.close()
            page.locator("#proc-cwd").select_option(label="demo")
            page.fill("#proc-cmd",
                      f'"{sys.executable}" -m http.server {wt_port} --bind 127.0.0.1')
            page.locator("#proc-start-btn").click()
            page.wait_for_timeout(3500)  # 端口快探窗口 2.5s
            check("进程行出现", page.locator(".proc-row").count() >= 1)
            check("进程端口链接", page.locator(
                f".proc-row a.p-port[href$=':{wt_port}']").count() >= 1)
            plist = api("/api/processes")["processes"]
            wt_proc_id = next((p["id"] for p in plist
                               if p["status"] == "running"
                               and str(wt_port) in " ".join(p["cmd"])), None)
            check("进程登记 running", wt_proc_id is not None)
            page.locator(".proc-row button", has_text="日志").first.click()
            page.wait_for_timeout(800)
            page.request.get(f"http://127.0.0.1:{wt_port}/")
            page.wait_for_timeout(1500)
            check("进程日志 tail", "GET" in
                  (page.locator("#proc-log").text_content() or ""))
            page.locator(".proc-row button", has_text="停止").first.click()
            page.wait_for_timeout(2000)
            check("进程停止", "已停止" in
                  (page.locator("#proc-list").text_content() or ""))
            check("端口已释放", _port_free(wt_port))
            wt_proc_id = None
            page.locator("#proc-close").click()
            page.wait_for_timeout(300)
            # 面板显隐 override（收起 → 悬浮钮 → 重开）
            page.locator("#code-panel-hide").click()
            page.wait_for_timeout(300)
            check("面板收起", not page.locator("#code-panel").is_visible())
            check("悬浮重开钮", page.locator("#code-panel-show").is_visible())
            page.locator("#code-panel-show").click()
            page.wait_for_timeout(400)
            check("面板重开", page.locator("#code-panel").is_visible())
            page.locator("#mode-tutor").click()
            page.wait_for_timeout(800)
            check("切回 study 模式", api("/api/session/mode").get("mode") == "study")
        finally:
            # 清理：进程 / 模式 / demo 目录 / demo 代码根（存在性感知）
            try:
                if wt_proc_id:
                    api("/api/processes/stop", {"id": wt_proc_id})
                for p_ in api("/api/processes")["processes"]:
                    if p_["status"] == "running":
                        api("/api/processes/stop", {"id": p_["id"]})
            except Exception:
                pass
            try:
                api("/api/session/mode", {"mode": "study"})
            except Exception:
                pass
            import shutil as _sh
            _wt = ROOT / "workspaces" / "ragent" / "demo" / "wt-demo"
            if _wt.exists():
                _sh.rmtree(_wt, ignore_errors=True)
            if not demo_root_existed:
                try:
                    api("/api/code/roots/delete", {"name": "demo"})
                except Exception:
                    pass

        mark("9 聊天")
        # ---- 9. 聊天（真实 LLM，短请求） ----
        before = page.locator("#messages .bubble").count()
        page.fill("#input", "回复OK即可")
        page.locator("#input-form button").click()
        ok = False
        for i in range(40):
            page.wait_for_timeout(4000)
            n = page.locator("#messages .bubble").count()
            last = page.locator("#messages .bubble").last.text_content() or ""
            if n >= before + 2 and "思考中" not in last and len(last) > 0:
                ok = True
                break
        check("聊天流式完成", ok, f"bubbles {before}→{n}")
        check("无 LLM 错误泡", page.locator(".msg.error").count() == 0,
              page.locator(".msg.error .bubble").first.text_content()[:100] if page.locator(".msg.error").count() else "")

        mark("9b Mermaid")
        # ---- 9b. Mermaid 渲染（前端确定性注入，不依赖 LLM 发挥） ----
        page.evaluate("""(() => {
          const div = document.createElement('div');
          div.id = 'mermaid-test';
          document.body.appendChild(div);
          renderMarkdownInto(div, '```mermaid\\nflowchart LR\\n  A-->B\\n```', true);
        })()""")
        page.wait_for_timeout(2500)
        check("Mermaid 渲染为 SVG",
              page.locator("#mermaid-test svg").count() >= 1)
        page.evaluate("document.getElementById('mermaid-test').remove()")

        mark("9c tool-use")
        # ---- 9c. AI 读文件 tool-use 全链路（临时切 Mock 渠道，事后还原） ----
        orig_cfg = page.request.get(BASE + "/api/llm-config").json()
        mock_cfg = {"provider": "mock",
                    "fallback_provider": orig_cfg.get("fallback_provider", ""),
                    "warmup_on_start": False, "sections": {}}
        page.request.post(BASE + "/api/llm-config", data=mock_cfg)
        before = page.locator("#messages .bubble").count()
        page.fill("#input", "演示读代码")
        page.locator("#input-form button").click()
        ok = False
        for i in range(30):
            page.wait_for_timeout(1000)
            if page.locator(".tool-chip").count() >= 1:
                last = page.locator("#messages .bubble").last.text_content() or ""
                if "思考中" not in last and len(last.strip()) > 0:
                    ok = True
                    break
        check("tool-use chip 出现且续写完成", ok)
        check("tool-use 无错误泡", page.locator(".msg.error").count() == 0,
              page.locator(".msg.error .bubble").first.text_content()[:100]
              if page.locator(".msg.error").count() else "")
        # chip 点击 → 跳转代码浏览器定位行
        if page.locator(".tool-chip.code-ref").count() >= 1:
            page.locator(".tool-chip.code-ref").first.click()
            page.wait_for_timeout(2000)
            check("chip 跳转打开文件",
                  "index.html" in page.locator("#code-file-path").text_content())
            check("chip 跳转行高亮", page.locator(".line-flash-mc").count() >= 1)
            page.locator("#mode-tutor").click()
            page.wait_for_timeout(600)
        mark("9c+ 模拟面试")
        # ---- 9c+. 模拟面试（M5c，Mock 渠道；teach_back 写真实库 → 先备份事后还原） ----
        import tomllib
        _cfg = tomllib.load(open(ROOT / "config" / "settings.toml", "rb"))
        _active = _cfg.get("active_workspace")
        _ws = next(w for w in _cfg.get("workspaces", [])
                   if w.get("slug") == _active)
        _sess_p = (ROOT / _ws["session_path"]).resolve()
        _lm_p = ((ROOT / _ws["docx_dir"]).resolve() / "learner_model.json")
        # R6 加固：记录存在性——面试新建的文件还原时删除；try/finally 保还原
        _bak = {p: (p.exists(), p.read_bytes() if p.exists() else b"")
                for p in (_sess_p, _lm_p)}
        try:
            page.locator("#command-chips .chip", has_text="模拟面试").click()
            ok_iv = False
            for i in range(30):
                page.wait_for_timeout(1000)
                last = page.locator("#messages .bubble").last.text_content() or ""
                if "口述" in last and "思考中" not in last:
                    ok_iv = True
                    break
            check("模拟面试口述要求出现", ok_iv)
            # 走完全场（口述 → 两轮追问 → 终评），验证 teach_back 落盘消息
            for reply in ("我按结构讲一遍这个知识点", "追问回答一", "追问回答二"):
                page.fill("#input", reply)
                page.locator("#input-form button").click()
                for i in range(30):
                    page.wait_for_timeout(1000)
                    last = page.locator("#messages .bubble").last.text_content() or ""
                    if "思考中" not in last and len(last.strip()) > 0:
                        break
            check("模拟面试 teach_back 落盘",
                  "模拟面试结束" in (page.locator("#messages").text_content() or ""))
        finally:
            for p, (existed, data) in _bak.items():
                if existed:
                    p.write_bytes(data)  # 还原 session 与 learner_model
                elif p.exists():
                    p.unlink()           # 面试新建的文件删除（防残留污染）
            # 还原真实渠道配置
            page.request.post(BASE + "/api/llm-config", data={
                "provider": orig_cfg.get("provider", "openai_compat"),
                "fallback_provider": orig_cfg.get("fallback_provider", ""),
                "warmup_on_start": orig_cfg.get("warmup_on_start", True),
                "sections": {}})

        mark("9d 资料库")
        # ---- 9d. 资料库（M1）：API + 弹窗列表 + 预览 ----
        mats = page.request.get(BASE + "/api/materials").json()
        check("资料库 API 非空", mats.get("ok") and len(mats.get("materials", [])) >= 1)
        page.locator("#open-docs").click()
        page.wait_for_timeout(600)
        page.locator('.doc-tab[data-doc="materials"]').click()
        page.wait_for_timeout(1500)
        check("资料库弹窗有条目", page.locator(".mat-item").count() >= 1)
        parsed = page.locator(".mat-item:not(.err)").first
        if parsed.count() >= 1:
            parsed.click()
            page.wait_for_timeout(1200)
            check("资料预览有内容",
                  page.locator(".mat-back").is_visible() and
                  len(page.locator("#doc-content").text_content()) > 50)
        page.locator("#doc-close").click()
        page.wait_for_timeout(400)

        mark("9e 可观测")
        # ---- 9e. 可观测性与密码门（M2） ----
        page.wait_for_timeout(1000)
        pill = page.locator("#llm-pill")
        check("LLM 状态条显示", pill.is_visible() and
              len(pill.text_content() or "") > 0)
        page.locator("#open-usage").click()
        page.wait_for_timeout(1200)
        check("用量弹窗表格渲染", page.locator("#usage-table").is_visible() and
              page.locator("#usage-rows tr").count() >= 1)
        # auth 全流程：设密码 → 退出 → 401 → 错误密码 → 正确登录 → 删除还原
        page.fill("#setup-password", "walk123")
        page.locator("#usage-auth-area button", has_text="设置密码").click()
        page.wait_for_timeout(1200)
        check("设置密码成功", page.locator(
            "#usage-auth-area button", has_text="退出登录").count() == 1)
        page.locator("#usage-auth-area button", has_text="退出登录").click()
        page.wait_for_timeout(2000)  # 退出后页面自动刷新
        check("退出后登录层出现", page.locator("#login-overlay").is_visible())
        check("未登录 API 401",
              page.request.get(BASE + "/api/state").status == 401)
        page.fill("#login-password", "wrong999")
        page.locator("#login-submit").click()
        page.wait_for_timeout(800)
        check("错误密码被拒", page.locator("#login-overlay").is_visible() and
              "密码错误" in (page.locator("#login-error").text_content() or ""))
        page.fill("#login-password", "walk123")
        page.locator("#login-submit").click()
        page.wait_for_timeout(1200)
        check("正确密码登录成功", page.locator("#login-overlay").is_hidden())
        check("登录后 API 200",
              page.request.get(BASE + "/api/state").status == 200)
        page.locator("#open-usage").click()
        page.wait_for_timeout(1000)
        page.once("dialog", lambda d: d.accept())  # confirm 删除密码
        page.locator("#usage-auth-area button", has_text="删除密码").click()
        page.wait_for_timeout(1200)
        gate = page.request.get(BASE + "/api/auth/status").json().get("gate")
        check("密码已还原为开放模式", gate is False)
        page.locator("#usage-close").click()
        page.wait_for_timeout(300)

        mark("9f 掌握度")
        # ---- 9f. 掌握度抽屉（战术板 + 战略雷达 + 侧栏预警） ----
        page.locator("#open-learner").click()
        page.wait_for_timeout(1500)
        # 模型不存在时先走迁移（幂等：已存在则迁移条不出现，直接跳过）
        if page.locator("#learner-migrate").is_visible():
            page.locator("#learner-migrate button").click()
            page.wait_for_timeout(1000)
            page.locator("#learner-migrate button", has_text="确认应用迁移").click()
            page.wait_for_timeout(1500)
        check("掌握度抽屉打开", page.locator("#mastery-drawer").is_visible())
        check("行动计数双卡", page.locator(".tac-counter").count() == 2)
        # 算法说明弹层收纳
        check("顶部无公式长文", page.locator("#mastery-expl").count() == 0)
        page.locator("#algo-info-btn").click()
        page.wait_for_timeout(300)
        check("算法说明弹层", page.locator("#algo-pop").is_visible())
        page.locator("#algo-info-btn").click()
        page.wait_for_timeout(300)
        check("弹层可关闭", page.locator("#algo-pop").is_hidden())
        check("需要行动分区", page.locator("#ms-urgent .m-sec-head").is_visible())
        check("紧急项行渲染", page.locator("#ms-urgent-body .mastery-row").count() >= 1)
        check("今日学习分区", "Day" in page.locator("#ms-today .m-sec-head").text_content())
        check("其余默认折叠", page.locator("#ms-rest-body").is_hidden())
        page.locator("#ms-rest-toggle").click()
        page.wait_for_timeout(400)
        check("其余展开", page.locator("#ms-rest-body").is_visible())
        # 手风琴详情
        page.locator("#ms-urgent-body .mastery-row").first.click()
        page.wait_for_timeout(600)
        check("详情手风琴展开", page.locator(".mastery-detail-inline").is_visible() and
              "查看评估明细" in page.locator(".mastery-detail-inline").text_content())
        check("详情含建议行动",
              page.locator(".mastery-detail-inline .md-advice").is_visible())
        check("详情含行动按钮",
              page.locator(".mastery-detail-inline .md-act-btn").count() >= 1)
        check("明细默认折叠",
              page.locator(".mastery-detail-inline .md-ev .ev-table").is_hidden())
        page.locator("#ms-urgent-body .mastery-row").first.click()
        page.wait_for_timeout(400)
        check("手风琴收起", page.locator(".mastery-detail-inline").count() == 0)
        # 战略雷达 tab
        page.locator(".drawer-tab[data-mtab='radar']").click()
        page.wait_for_timeout(2500)
        check("雷达 Donut 渲染", page.locator("#radar-donut svg").count() == 1 and
              page.locator(".rl-row").count() == 4)
        check("雷达热力格", page.locator(".heat-cell2").count() >= 80)
        check("课程时间轴渲染", page.locator(".tl-row").count() >= 1)
        # 时间轴节点点击 → 跳回战术板展开详情
        page.locator(".tl-row").first.click()
        page.wait_for_timeout(1800)
        check("时间轴跳转战术板", page.locator("#mastery-tactical").is_visible() and
              page.locator(".mastery-detail-inline").count() >= 1)
        page.locator("#mastery-close").click()
        page.wait_for_timeout(300)
        # 侧栏复习预警 widget → 跳转抽屉展开详情
        check("侧栏复习预警", page.locator("#urgent-widget").is_visible() and
              page.locator(".uw-item").count() >= 1)
        page.locator(".uw-item").first.click()
        page.wait_for_timeout(1800)
        check("预警跳转展开详情", page.locator(".mastery-detail-inline").count() >= 1)
        page.locator("#mastery-close").click()
        page.wait_for_timeout(300)

        mark("9g 笔记")
        # ---- 9g. 笔记页 v2（书架三栏 + MD 编辑器） ----
        # 全程只用「走查测试」前缀笔记（无 concept：销账不写证据，零污染真实数据）
        page.locator("#open-notes").click()
        page.wait_for_timeout(1200)
        check("笔记全屏页打开", page.locator("#notes-page").is_visible())
        check("书架渲染", page.locator(
            "#notes-shelf .shelf-item[data-shelf='all']").is_visible())
        # 新建（浮层选类型）→ 进编辑器
        page.locator("#notes-add-btn").click()
        page.wait_for_timeout(400)
        page.locator("#attach-picker select").first.select_option("insight")
        page.locator("#attach-picker button", has_text="创建并编辑").click()
        page.wait_for_timeout(1000)
        check("新建后进编辑器", page.locator("#notes-editor").is_visible())
        # 工具条插标题 + 预览联动
        page.locator("#ne-text").fill("走查测试笔记")
        page.locator("#ne-toolbar button[data-md='h1']").click()
        page.wait_for_timeout(300)
        check("工具条插入标题",
              page.locator("#ne-text").input_value().startswith("# "))
        page.wait_for_timeout(500)
        check("预览渲染 h1", page.locator("#ne-preview h1").count() >= 1)
        # mermaid 模板 → 预览 SVG
        page.locator("#ne-toolbar button[data-md='mermaid']").click()
        page.wait_for_timeout(1500)
        check("预览渲染 mermaid", page.locator("#ne-preview svg").count() >= 1)
        # 保存 → 卡片出现
        page.locator("#ne-save").click()
        page.wait_for_timeout(800)
        check("笔记卡片出现",
              page.locator(".note-card", has_text="走查测试笔记").count() >= 1)
        # 搜索过滤
        page.fill("#notes-search", "不存在的内容xyz")
        page.wait_for_timeout(400)
        check("搜索空结果", page.locator(".note-card").count() == 0)
        page.fill("#notes-search", "")
        page.wait_for_timeout(400)
        # 编辑保存 → 卡片标题更新
        page.locator(".note-card", has_text="走查测试笔记").first.click()
        page.wait_for_timeout(400)
        page.locator("#ne-text").fill("# 走查测试笔记（已编辑）\n\n正文")
        page.locator("#ne-save").click()
        page.wait_for_timeout(800)
        check("编辑保存生效", "已编辑" in page.locator("#notes-list").text_content())
        # 销账（无 concept → evidence=False，不写学习者模型）
        page.once("dialog", lambda d: d.accept())
        page.locator("#ne-resolve").click()
        page.wait_for_timeout(1000)
        check("销账后已解决态",
              page.locator(".note-card.resolved", has_text="走查测试").count() >= 1)
        r = page.request.post(BASE + "/api/notes/distill", data={})
        check("蒸馏 API 正常", r.status == 200 and "added" in r.json())
        # 清理：只删走查自建笔记
        for n in page.request.get(BASE + "/api/notes").json().get("notes", []):
            if "走查测试" in n.get("text", ""):
                page.request.post(BASE + "/api/notes/delete", data={"id": n["id"]})
        left = [n for n in page.request.get(BASE + "/api/notes").json().get("notes", [])
                if "走查测试" in n.get("text", "")]
        check("走查笔记已清理", len(left) == 0)
        page.locator("#notes-close").click()
        page.wait_for_timeout(300)

        mark("9h 话术")
        # ---- 9h. 面试话术库（M4）：卡片视图 + 原文切换 ----
        page.locator("#open-docs").click()
        page.wait_for_timeout(800)
        page.locator(".doc-tab[data-doc='interview_qa']").click()
        page.wait_for_timeout(1200)
        check("话术卡片视图工具条", page.locator(".qa-toolbar").is_visible())
        if page.locator(".qa-entry").count() >= 1:
            check("话术卡片渲染", page.locator(".qa-entry .qa-brief").count() >= 1)
        else:
            check("话术空态提示", page.locator(".qa-empty").is_visible())
        page.locator(".qa-toolbar button", has_text="原文").click()
        page.wait_for_timeout(800)
        check("话术原文视图", "面试话术" in page.locator("#doc-content").text_content())
        page.locator("#doc-close").click()
        page.wait_for_timeout(300)

        # ---- 汇总 ----
        check("全程零 JS 错误", len(errors) == 0, "; ".join(errors[:3]))
        page.screenshot(path="/tmp/walkthrough_final.png")
        # 走查产生的测试消息自清理，不给用户留垃圾历史
        try:
            page.request.post(BASE + "/api/session/reset")
        except Exception:
            pass
        b.close()

    # 还原用户原工作区
    if orig_ws and orig_ws != "ragent":
        try:
            api("/api/workspaces/switch", {"slug": orig_ws})
        except Exception:
            pass

    print()
    if ISSUES:
        print(f"发现 {len(ISSUES)} 个问题：")
        for i in ISSUES:
            print(" -", i)
        return 1
    print("全部通过 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
