// ---------- 代码浏览器（源码学习模式面板） ----------
// 从 app.js 拆分出的独立功能域模块

const codePanel = document.getElementById("code-panel");
const codeTreeEl = document.getElementById("code-tree");
const codeContentEl = document.getElementById("code-content");
const floatBtn = document.getElementById("snippet-float");
var codeState = { root: "", path: "", lang: "plaintext" };
var codeFileSeq = 0;  // openCodeFile 响应序号（Y8：慢响应后到不覆盖新选择）
var snippetSel = null;
var lastMouse = { x: 0, y: 0 };

// ---- 目录树折叠 + 宽度拖拽 ----
const treeToggleBtn = document.getElementById("code-tree-toggle");
treeToggleBtn.onclick = () => {
  const collapsed = codeTreeEl.classList.toggle("collapsed");
  treeToggleBtn.textContent = collapsed ? "»" : "«";
};
const treeResizer = document.getElementById("tree-resizer");
const savedTreeWidth = localStorage.getItem("codeTreeWidth");
if (savedTreeWidth) codeTreeEl.style.width = `${parseInt(savedTreeWidth)}px`;
treeResizer.addEventListener("mousedown", (e) => {
  e.preventDefault();
  document.body.style.userSelect = "none";
  const onMove = (ev) => {
    const rect = codeTreeEl.getBoundingClientRect();
    const w = Math.min(Math.max(ev.clientX - rect.left, 140), 480);
    codeTreeEl.style.width = `${w}px`;
  };
  const onUp = (ev) => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    document.body.style.userSelect = "";
    const rect = codeTreeEl.getBoundingClientRect();
    const w = Math.min(Math.max(ev.clientX - rect.left, 140), 480);
    localStorage.setItem("codeTreeWidth", String(w));
  };
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
});

// ---- 自动换行 ----
const wrapBtn = document.getElementById("code-wrap-toggle");
wrapBtn.onclick = () => {
  const on = codeContentEl.classList.toggle("wrap-mode");
  wrapBtn.textContent = on ? "换行: 开" : "换行: 关";
  if (mcEditor) mcEditor.updateOptions({ wordWrap: on ? "on" : "off" });
};

async function loadCodeRoots(keepSelection) {
  const res = await fetch("/api/code/roots");
  const { roots } = await res.json();
  const sel = document.getElementById("code-root-select");
  sel.innerHTML = "";
  for (const r of roots) {
    const opt = document.createElement("option");  // C3：DOM 构建防注入（原 insertAdjacentHTML 拼接）
    opt.value = r.name;
    opt.textContent = r.name + (r.exists ? "" : "（目录不存在）");
    if (!r.exists) opt.disabled = true;
    sel.appendChild(opt);
  }
  if (roots.length) {
    if (keepSelection && codeState.root) sel.value = codeState.root;
    codeState.root = sel.value;
    codeTreeEl.innerHTML = '<div class="code-hint">加载中…</div>';
    await loadTreeLevel(codeState.root, "", codeTreeEl, true);
  } else {
    codeTreeEl.innerHTML = '<div class="code-hint">还没有代码根，点「+ 添加项目」</div>';
  }
}

document.getElementById("code-root-select").onchange = (e) => {
  codeState.root = e.target.value;
  codeState.path = "";
  document.getElementById("code-file-path").textContent = "← 从左侧目录树选择文件";
  document.getElementById("csb-path").textContent = "未打开文件";
  document.getElementById("csb-meta").textContent = "";
  showCodeHint("选择文件查看代码");
  loadTreeLevel(codeState.root, "", codeTreeEl, true);
};

async function loadTreeLevel(root, rel, container, replace) {
  const res = await fetch(`/api/code/tree?root=${encodeURIComponent(root)}&path=${encodeURIComponent(rel)}`);
  const r = await res.json();
  if (!r.ok) { container.textContent = ""; const d = document.createElement("div");
    d.className = "code-hint"; d.textContent = r.error; container.appendChild(d); return; }
  if (replace) container.innerHTML = "";
  for (const entry of r.entries) {
    const row = document.createElement("div");
    row.className = `tree-row ${entry.type}`;
    const entryRel = rel ? `${rel}/${entry.name}` : entry.name;
    if (entry.type === "dir") {
      row.innerHTML = `<span class="tree-icon">▸</span> ${entry.name}`;
      row.title = entryRel;  // 悬停显示完整路径
      const children = document.createElement("div");
      children.className = "tree-children hidden";
      let loaded = false;
      row.onclick = async () => {
        children.classList.toggle("hidden");
        row.querySelector(".tree-icon").textContent =
          children.classList.contains("hidden") ? "▸" : "▾";
        if (!loaded) {
          loaded = true;
          await loadTreeLevel(root, entryRel, children, true);
        }
      };
      container.appendChild(row);
      container.appendChild(children);
    } else {
      row.innerHTML = `<span class="tree-icon">·</span> ${entry.name}`;
      row.title = entryRel;  // 悬停显示完整路径
      row.onclick = () => {
        container.closest(".code-tree").querySelectorAll(".tree-row.active")
          .forEach(n => n.classList.remove("active"));
        row.classList.add("active");
        openCodeFile(root, entryRel);
      };
      container.appendChild(row);
    }
  }
  if (!r.entries.length) container.innerHTML = '<div class="code-hint">（空目录）</div>';
}

// ---- Monaco（M6：pair 布局首次打开文件时动态加载；失败静默降级 legacy 渲染） ----
var monacoReady = null;   // Promise|null（加载单例）
var mcEditor = null;      // monaco editor 实例（null = legacy 模式）
var mcModel = null;       // 当前 model 句柄（Y10：随编辑器一并 dispose 防泄漏）
var mcDecorations = [];   // 行高亮 decoration 句柄

function loadMonaco() {
  if (monacoReady) return monacoReady;
  monacoReady = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/vendor/monaco/vs/loader.js";
    s.onload = () => {
      try {
        const base = location.origin + "/vendor/monaco/vs";
        const baseRoot = location.origin + "/vendor/monaco";
        window.MonacoEnvironment = {
          getWorkerUrl: () => "data:text/javascript;charset=utf-8," + encodeURIComponent(
            `self.MonacoEnvironment={baseUrl:'${baseRoot}/'};importScripts('${base}/base/worker/workerMain.js');`),
        };
        require.config({
          paths: { vs: base },
          "vs/nls": { availableLanguages: { "*": "zh-cn" } },
        });
        require(["vs/editor/editor.main"], () => resolve(window.monaco), reject);
      } catch (e) { reject(e); }
    };
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return monacoReady;
}

// 销毁 Monaco 编辑器与当前 model（Y10：model 句柄一并 dispose，防泄漏）
function disposeMonaco() {
  if (mcEditor) {
    mcEditor.dispose();
    mcEditor = null;
    window.__codeEditor = null;
    codeContentEl.classList.remove("mc-host");
  }
  if (mcModel) { mcModel.dispose(); mcModel = null; }
}

// 代码区提示（Monaco 宿主存在时先销毁编辑器，防 innerHTML 抹掉其 DOM）
function showCodeHint(text) {
  disposeMonaco();
  codeContentEl.innerHTML = "";
  const d = document.createElement("div");
  d.className = "code-hint";
  d.textContent = text;
  codeContentEl.appendChild(d);
}

function setDirty(v) {
  document.getElementById("code-save").classList.toggle("dirty", v);
}

function updateSaveBtn() {
  document.getElementById("code-save").classList.toggle("hidden", !codeState.editable);
}

async function saveCurrentFile() {
  if (!codeState.editable || !mcEditor) return;
  const res = await fetch("/api/code/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root: codeState.root, path: codeState.path, content: mcEditor.getValue(), mtime: codeState.mtime }),
  });
  const r = await res.json();
  if (r.ok) {
    setDirty(false);
    showToast(`已保存 ${codeState.path}`);
    if (r.mtime !== undefined) codeState.mtime = r.mtime;
    else {
      const fr = await (await fetch(`/api/code/file?root=${encodeURIComponent(codeState.root)}&path=${encodeURIComponent(codeState.path)}`)).json();
      if (fr.ok && fr.mtime !== undefined) codeState.mtime = fr.mtime;
    }
  } else if (r.conflict) {
    showToast("文件已被外部修改，请刷新后重试");
  } else showToast(`保存失败：${r.error}`);
}
document.getElementById("code-save").onclick = saveCurrentFile;

function openInMonaco(r) {
  if (!mcEditor) {
    codeContentEl.innerHTML = "";
    codeContentEl.classList.add("mc-host");
    const host = document.createElement("div");
    host.className = "mc-editor";
    codeContentEl.appendChild(host);
    mcEditor = monaco.editor.create(host, {
      theme: "vs-dark", readOnly: !r.editable,
      minimap: { enabled: false }, automaticLayout: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono','Cascadia Code',Consolas,monospace",
      scrollBeyondLastLine: false,
      wordWrap: codeContentEl.classList.contains("wrap-mode") ? "on" : "off",
    });
    window.__codeEditor = mcEditor;  // 走查 evaluate 用
    mcEditor.onDidChangeCursorSelection(onMonacoSelection);
    mcEditor.onDidChangeModelContent(() => setDirty(true));
    mcEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveCurrentFile);
  }
  const oldModel = mcEditor.getModel();
  mcModel = monaco.editor.createModel(r.content, r.lang);
  mcEditor.setModel(mcModel);
  mcEditor.updateOptions({ readOnly: !r.editable });
  if (oldModel) oldModel.dispose();
  mcDecorations = [];
  mcEditor.setScrollTop(0);
  mcEditor.setPosition({ lineNumber: 1, column: 1 });
  setDirty(false);
}

// Monaco 选区 → 片段提问（沿用 lastMouse 定位浮动按钮）
function onMonacoSelection(e) {
  const sel = e.selection;
  if (!sel || sel.isEmpty()) { snippetSel = null; floatBtn.classList.add("hidden"); return; }
  const text = mcEditor.getModel().getValueInRange(sel).replace(/\n$/, "");
  if (!text.trim()) { snippetSel = null; floatBtn.classList.add("hidden"); return; }
  snippetSel = { startLine: sel.startLineNumber, endLine: sel.endLineNumber, text };
  floatBtn.classList.remove("hidden");
  const x = Math.min(lastMouse.x + 12, window.innerWidth - 110);
  const y = Math.max(lastMouse.y - 42, 8);
  floatBtn.style.left = `${x}px`;
  floatBtn.style.top = `${y}px`;
}

// legacy 渲染（Monaco 加载失败的降级路径，保留原 gutter+hljs 实现）
function openLegacy(r) {
  disposeMonaco();
  codeContentEl.classList.remove("mc-host");
  document.getElementById("code-save").classList.add("hidden");
  const lines = r.content.split("\n");
  const wrap = document.createElement("div");
  wrap.className = "code-wrap";
  wrap.style.position = "relative";
  const gutter = document.createElement("pre");
  gutter.className = "code-gutter";
  gutter.textContent = lines.map((_, i) => i + 1).join("\n");
  const body = document.createElement("pre");
  body.className = "code-body";
  const code = document.createElement("code");
  code.className = `language-${r.lang}`;
  code.textContent = r.content;
  body.appendChild(code);
  wrap.appendChild(gutter);
  wrap.appendChild(body);
  codeContentEl.innerHTML = "";
  codeContentEl.appendChild(wrap);
  hljs.highlightElement(code);
}

async function openCodeFile(root, rel) {
  const seq = ++codeFileSeq;
  document.getElementById("code-file-path").textContent = `${root}/${rel}`;
  floatBtn.classList.add("hidden");
  const res = await fetch(`/api/code/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(rel)}`);
  const r = await res.json();
  if (seq !== codeFileSeq) return;
  if (!r.ok) { showCodeHint(r.error); return; }
  codeState = { root, path: rel, lang: r.lang, editable: !!r.editable, mtime: r.mtime };
  document.getElementById("csb-path").textContent = `${root}/${rel}`;
  document.getElementById("csb-meta").textContent =
    `${r.lang} · ${r.lines || r.content.split("\n").length} 行 · UTF-8${r.editable ? " · 可编辑" : " · 只读"}`;
  updateSaveBtn();
  try {
    await loadMonaco();
    if (seq !== codeFileSeq) return;
    openInMonaco(r);
  } catch (e) {
    monacoReady = null;
    if (seq !== codeFileSeq) return;
    openLegacy(r);
  }
}

// 选区 → 行号范围
function charOffsetOf(root, node, offset) {
  const r = document.createRange();
  r.selectNodeContents(root);
  try { r.setEnd(node, offset); } catch (e) { return null; }
  return r.toString().length;
}

function getSnippetSelection() {
  const body = codeContentEl.querySelector(".code-body");
  if (!body) return null;
  const sel = window.getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!body.contains(range.commonAncestorContainer)) return null;
  const start = charOffsetOf(body, range.startContainer, range.startOffset);
  const end = charOffsetOf(body, range.endContainer, range.endOffset);
  if (start == null || end == null || end <= start) return null;
  const full = body.textContent;
  const startLine = full.slice(0, start).split("\n").length;
  let endLine = full.slice(0, end).split("\n").length;
  if (full[end - 1] === "\n") endLine -= 1;
  return { startLine, endLine, text: sel.toString().replace(/\n$/, "") };
}

document.addEventListener("mouseup", (e) => { lastMouse = { x: e.clientX, y: e.clientY }; });

document.addEventListener("selectionchange", () => {
  if (mcEditor) return;  // Monaco 模式由 onDidChangeCursorSelection 驱动
  if (codePanel.classList.contains("hidden")) {
    floatBtn.classList.add("hidden");
    return;
  }
  snippetSel = getSnippetSelection();
  if (snippetSel && snippetSel.text.trim()) {
    floatBtn.classList.remove("hidden");
    const x = Math.min(lastMouse.x + 12, window.innerWidth - 110);
    const y = Math.max(lastMouse.y - 42, 8);
    floatBtn.style.left = `${x}px`;
    floatBtn.style.top = `${y}px`;
  } else {
    floatBtn.classList.add("hidden");
  }
});

floatBtn.onclick = () => {
  if (!snippetSel) return;
  const { startLine, endLine, text } = snippetSel;
  const ref = endLine > startLine ? `L${startLine}-L${endLine}` : `L${startLine}`;
  const inputEl = document.getElementById("input");
  inputEl.value =
    `\`${codeState.root}/${codeState.path}:${ref}\`\n` +
    "```" + codeState.lang + "\n" + text + "\n```\n\n我的问题：";
  inputEl.dispatchEvent(new Event("input"));  // autosize
  floatBtn.classList.add("hidden");
  inputEl.focus();
  window.getSelection().removeAllRanges();
};

// ---- 片段卡片点击跳转：打开文件 + 滚动定位 + 行高亮 ----
document.addEventListener("click", async (e) => {
  const chip = e.target.closest(".snippet-jump");
  if (!chip) return;
  const rootPath = chip.dataset.rootpath;
  const slash = rootPath.indexOf("/");
  const root = slash > 0 ? rootPath.slice(0, slash) : rootPath;
  const rel = slash > 0 ? rootPath.slice(slash + 1) : "";
  if (document.body.dataset.layout !== "pair") setLayout("pair");
  await openCodeFile(root, rel);
  flashLines(parseInt(chip.dataset.s), parseInt(chip.dataset.e));
});

function flashLines(s, e) {
  if (mcEditor) {
    mcDecorations = mcEditor.deltaDecorations(mcDecorations, [{
      range: new monaco.Range(s, 1, e, 1),
      options: { isWholeLine: true, className: "line-flash-mc" },
    }]);
    mcEditor.revealLineInCenter(s);
    return;
  }
  const wrap = codeContentEl.querySelector(".code-wrap");
  const body = codeContentEl.querySelector(".code-body");
  if (!wrap || !body) return;
  wrap.querySelectorAll(".line-flash").forEach(x => x.remove());
  const lineH = parseFloat(getComputedStyle(body).lineHeight) || 19;
  const padTop = parseFloat(getComputedStyle(body).paddingTop) || 10;
  for (let i = s; i <= e; i++) {
    const d = document.createElement("div");
    d.className = "line-flash";
    d.style.top = `${padTop + (i - 1) * lineH}px`;
    d.style.height = `${lineH}px`;
    wrap.appendChild(d);
  }
  codeContentEl.scrollTop = Math.max(padTop + (s - 1) * lineH - 80, 0);
}

// 项目根管理
document.getElementById("code-root-add").onclick = () =>
  document.getElementById("code-root-form").classList.toggle("hidden");
document.getElementById("code-root-cancel").onclick = () =>
  document.getElementById("code-root-form").classList.add("hidden");
document.getElementById("code-root-save").onclick = async () => {
  const name = document.getElementById("code-root-name").value.trim();
  const path = document.getElementById("code-root-path").value.trim();
  if (!name || !path) return;
  const res = await fetch("/api/code/roots", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, path }),
  });
  const r = await res.json();
  if (!r.ok) { alert(r.error); return; }
  document.getElementById("code-root-form").classList.add("hidden");
  document.getElementById("code-root-name").value = "";
  document.getElementById("code-root-path").value = "";
  codeState.root = name;
  await loadCodeRoots(true);
};
document.getElementById("code-root-del").onclick = async () => {
  if (!codeState.root) return;
  if (!confirm(`删除代码根「${codeState.root}」？（仅移除配置，不删文件）`)) return;
  await fetch("/api/code/roots/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: codeState.root }),
  });
  codeState.root = "";
  await loadCodeRoots();
};
