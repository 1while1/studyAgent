const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const form = document.getElementById("input-form");
const scrollBtn = document.getElementById("scroll-bottom");

marked.setOptions({ breaks: true, gfm: true });

// ---------- Markdown 渲染 ----------

// mermaid 主题随布局：源码学习=IDE 深色，知识学习=暖纸浅色
function mermaidTheme() {
  return document.body.dataset.layout === "pair" ? "dark" : "default";
}

// 将 ```mermaid 代码块渲染为图（仅终渲染时调用，流式中块未闭合不渲染）
function renderMermaidBlocks(el) {
  if (typeof mermaid === "undefined") return;  // vendor 缺失时保留代码块原样
  const blocks = el.querySelectorAll("pre code.language-mermaid");
  if (!blocks.length) return;
  const nodes = [];
  blocks.forEach(code => {
    const pre = code.closest("pre");
    const div = document.createElement("div");
    div.className = "mermaid";
    div.textContent = code.textContent;
    pre.replaceWith(div);
    nodes.push(div);
  });
  mermaid.initialize({
    startOnLoad: false, securityLevel: "strict", theme: mermaidTheme(),
  });
  mermaid.run({ nodes }).catch(() => {
    // 语法错误等：回退为代码块展示，不炸整个气泡
    nodes.forEach(div => {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.className = "language-mermaid";
      code.textContent = div.textContent;
      pre.appendChild(code);
      div.replaceWith(pre);
    });
  });
}

function renderMarkdownInto(el, text, isFinal = true) {
  el.innerHTML = DOMPurify.sanitize(marked.parse(text));
  el.querySelectorAll("pre code").forEach(block => hljs.highlightElement(block));
  el.querySelectorAll("pre").forEach(pre => {
    if (pre.querySelector(".copy-btn")) return;
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = "复制";
    btn.onclick = () => {
      navigator.clipboard.writeText(pre.innerText.replace(/复制$/, "").trim());
      btn.textContent = "已复制";
      setTimeout(() => (btn.textContent = "复制"), 1500);
    };
    pre.appendChild(btn);
  });
  if (isFinal) renderMermaidBlocks(el);
  linkifyCodeRefs(el);
}

// ---------- 代码引用芯片（AI 回答中的路径 → 可点击跳转） ----------

// 形如 ragent原项目/infra-ai/pom.xml、core/prompt_manager.py、README.md，
// 可附行号 :L4 / :L4-L11 / :4-11；必须含扩展名
const CODE_REF_RE = /^[\w.\-\u4e00-\u9fff()]+(\/[\w.\-\u4e00-\u9fff()]+)*\.(java|xml|ya?ml|properties|md|txt|json|py|js|ts|tsx|jsx|html|css|sql|toml|gradle|vue|go|rs|sh|bat|c|h|cpp)(:L?\d+(-L?\d+)?)?$/i;

function linkifyCodeRefs(scope) {
  scope.querySelectorAll("code").forEach(code => {
    if (code.closest("pre")) return;  // 跳过代码块，只处理行内 code
    const text = code.textContent.trim();
    if (!CODE_REF_RE.test(text)) return;
    let path = text, s = null, e = null;
    const lm = text.match(/^(.*?):L?(\d+)(?:-L?(\d+))?$/);
    if (lm) { path = lm[1]; s = parseInt(lm[2]); e = parseInt(lm[3] || lm[2]); }
    const span = document.createElement("span");
    span.className = "code-ref";
    span.dataset.path = path;
    if (s) { span.dataset.s = s; span.dataset.e = e; }
    span.title = "在代码浏览器中打开";
    span.textContent = text;
    code.replaceWith(span);
  });
}

function showToast(msg) {
  document.querySelectorAll(".toast").forEach(t => t.remove());
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

// 点击代码引用芯片 → 解析 → 打开文件 → 行高亮
document.addEventListener("click", async (e) => {
  const ref = e.target.closest(".code-ref");
  if (!ref) return;
  const s = ref.dataset.s ? parseInt(ref.dataset.s) : null;
  const el = ref.dataset.e ? parseInt(ref.dataset.e) : null;
  const open = (root, path) => {
    if (document.body.dataset.layout !== "pair") setLayout("pair");
    return openCodeFile(root, path).then(() => { if (s) flashLines(s, el || s); });
  };
  let r = await (await fetch(`/api/code/resolve?path=${encodeURIComponent(ref.dataset.path)}`)).json();
  if (r.ok) { await open(r.root, r.path); return; }
  // 回退：完整路径找不到时按文件名再试（AI 常把目录写错但文件名是对的）
  const base = ref.dataset.path.split("/").pop();
  if (base && base !== ref.dataset.path) {
    r = await (await fetch(`/api/code/resolve?path=${encodeURIComponent(base)}`)).json();
    if (r.ok) {
      showToast(`原路径未找到，已定位同名文件：${r.root}/${r.path}`);
      await open(r.root, r.path);
      return;
    }
  }
  showToast(`未在已配置代码根中找到：${ref.dataset.path}`);
});

// ---------- 消息气泡 ----------

// 片段提问消息 → 紧凑卡片（模型仍收到完整代码，仅显示折叠）
// 容错：围栏后可缺换行、问题前缀可缺省（兼容早期插入格式）
const SNIPPET_RE = /^`(.+?:L\d+(?:-L\d+)?)`\s*```(\w*)\s*\n?([\s\S]*?)\n?```\s*(?:我的问题：)?([\s\S]*)$/;

function addUserMessage(text) {
  const m = text.match(SNIPPET_RE);
  if (!m) { addMessage("user", text); return; }
  const [, ref, lang, code, question] = m;
  const div = document.createElement("div");
  div.className = "msg user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const lm = ref.match(/^(.+?):L(\d+)(?:-L(\d+))?$/);
  const [rootPath, sLine, eLine] = lm ? [lm[1], lm[2], lm[3] || lm[2]] : ["", "1", "1"];
  bubble.innerHTML = `
    <span class="snippet-ref snippet-jump" data-rootpath="${escapeHtml(rootPath)}" data-s="${sLine}" data-e="${eLine}" title="点击在代码浏览器中打开并定位">📎 ${escapeHtml(ref)}</span>
    <pre class="snippet-code"><code class="language-${lang}"></code></pre>
    <div class="snippet-q">${question.trim() ? escapeHtml(question.trim()) : "（未补充问题）"}</div>`;
  bubble.querySelector("code").textContent = code;
  hljs.highlightElement(bubble.querySelector("code"));
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  scrollToBottom();
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// AI 读文件 tool-use 指示 chip（点击跳转代码浏览器定位行）
function addToolReadChip(p) {
  const div = document.createElement("div");
  div.className = "msg tool";
  const chip = document.createElement("span");
  chip.className = "tool-chip" + (p.ok ? "" : " fail");
  if (p.ok) {
    chip.textContent = `📖 AI 读取了 ${p.path}${p.lines ? ":" + p.lines : ""}`;
    chip.dataset.path = p.path;
    const lm = (p.lines || "").match(/^L(\d+)-L(\d+)$/);
    if (lm) { chip.dataset.s = lm[1]; chip.dataset.e = lm[2]; }
    chip.classList.add("code-ref");  // 复用引用芯片的点击跳转逻辑
    chip.title = "在代码浏览器中打开";
  } else {
    chip.textContent = `📖 读取失败：${p.path}${p.error ? "（" + p.error + "）" : ""}`;
  }
  div.appendChild(chip);
  messagesEl.appendChild(div);
}

function addMessage(role, text, isMarkdown) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "assistant" || role === "error") bubble.classList.add("md");
  if (isMarkdown && bubble.classList.contains("md")) {
    renderMarkdownInto(bubble, text);
  } else {
    bubble.textContent = text;
  }
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  scrollToBottom();
  return bubble;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
  scrollBtn.classList.add("hidden");
}

messagesEl.addEventListener("scroll", () => {
  const nearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 120;
  scrollBtn.classList.toggle("hidden", nearBottom);
});
scrollBtn.onclick = scrollToBottom;

// 流式期间的 markdown 渲染节流（raw 显示 → 每 200ms 渲染一次 → 结束终渲染）
// 注意：定时器触发时必须渲染「最新」文本（挂在 bubble 上），
// 不能用调度时的旧快照——否则流结束后的终渲染会被迟到的节流渲染回退成旧前缀（已踩坑）
let renderTimer = null;
function throttledRender(bubble, text) {
  bubble._pendingText = text;
  if (renderTimer) return;
  renderTimer = setTimeout(() => {
    renderTimer = null;
    renderMarkdownInto(bubble, bubble._pendingText, false);  // 流式中不渲染 mermaid
    scrollToBottom();
  }, 200);
}
function cancelThrottledRender() {
  if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
}

// ---------- 状态面板 ----------

async function refreshState() {
  try {
    const res = await fetch("/api/state");
    const s = await res.json();
    document.getElementById("day-label").textContent =
      `Day ${s.current_day} / ${s.workspace.total_days}`;
    if (s.workspace.title) {
      document.title = s.workspace.title;
      document.querySelector("#sidebar h1").textContent = s.workspace.title;
    }
    document.getElementById("progress-fill").style.width = `${s.percentage}%`;
    document.getElementById("percentage").textContent = `${s.percentage}%`;

    const unitsEl = document.getElementById("units");
    unitsEl.innerHTML = "";
    for (const u of s.units) {
      const li = document.createElement("li");
      const dot = u.checked ? "done" : (u.status === "in_progress" ? "doing" : "todo");
      li.innerHTML = `<span class="unit-dot ${dot}"></span><span>单元${u.id}：${escapeHtml(u.title)}` +
        (u.rating ? `（${u.rating}分）` : "") + "</span>";
      if (u.status === "in_progress") li.className = "in-progress";
      unitsEl.appendChild(li);
    }

    const syncEl = document.getElementById("sync-counts");
    syncEl.textContent =
      Object.entries(s.sync_counts).map(([k, v]) => `${k} ${v}`).join(" · ") || "-";

    const sess = s.session;
    document.getElementById("session-info").textContent =
      `${sess.day_phase || "-"} · 单元${sess.current_unit_id || "-"} · ${sess.current_stage || "-"}`;
  } catch (e) { /* 服务未就绪时静默 */ }
}

let COMMANDS = [];
async function loadCommands() {
  const res = await fetch("/api/commands");
  COMMANDS = await res.json();
  const box = document.getElementById("command-chips");
  box.innerHTML = "";
  for (const c of COMMANDS) {
    const btn = document.createElement("button");
    btn.className = "chip";
    btn.type = "button";
    btn.textContent = `[${c.trigger}]`;
    btn.onclick = () => sendCommand(`[${c.trigger}]`);
    box.appendChild(btn);
  }
}

// ---------- 「[」指令补全菜单（Slack 式） ----------

const cmdMenu = document.getElementById("cmd-menu");
let cmdMenuOpen = false;

function closeCmdMenu() {
  cmdMenu.classList.add("hidden");
  cmdMenuOpen = false;
}

function updateCmdMenu() {
  const m = inputEl.value.match(/^\[([^\]\n]*)$/);
  if (!m) { closeCmdMenu(); return; }
  const kw = m[1];
  const hits = COMMANDS.filter(c => !kw || c.trigger.includes(kw));
  if (!hits.length) { closeCmdMenu(); return; }
  cmdMenu.innerHTML = "";
  for (const c of hits) {
    const item = document.createElement("button");
    item.type = "button";
    item.textContent = `[${c.trigger}]`;
    item.onclick = () => {
      inputEl.value = `[${c.trigger}]`;
      closeCmdMenu();
      autosizeInput();
      inputEl.focus();
    };
    cmdMenu.appendChild(item);
  }
  cmdMenu.classList.remove("hidden");
  cmdMenuOpen = true;
}
inputEl.addEventListener("input", updateCmdMenu);
document.addEventListener("click", (e) => {
  if (cmdMenuOpen && !cmdMenu.contains(e.target) && e.target !== inputEl) closeCmdMenu();
});

async function loadHistory() {
  try {
    const res = await fetch("/api/history");
    const { messages } = await res.json();
    for (const m of messages) {
      if (m.role === "user") addUserMessage(m.content);
      else if (m.role === "assistant") addMessage("assistant", m.content, true);
    }
    scrollToBottom();
  } catch (e) { /* 忽略 */ }
}

// ---------- SSE 收发 ----------

// 发送锁：流式进行中禁止再次发送（防前后端历史错乱）
let streaming = false;

function setSendEnabled(on) {
  const btn = document.querySelector("#input-form button");
  if (btn) btn.disabled = !on;
  document.getElementById("command-chips").style.pointerEvents = on ? "" : "none";
}

async function streamPost(url, text) {
  if (streaming) { showToast("上一条回复生成中，请稍候…"); return; }
  streaming = true;
  setSendEnabled(false);
  addUserMessage(text);
  let bubble = addMessage("assistant", "思考中…");
  bubble.classList.add("thinking");
  const started = Date.now();
  const timer = setInterval(() => {
    if (bubble.classList.contains("thinking")) {
      bubble.textContent = `思考中… ${Math.floor((Date.now() - started) / 1000)}s（长提示词首包较慢，请稍候）`;
    }
  }, 1000);
  let rawText = "";  // Markdown 原文累积器（禁止从 bubble.textContent 回读）
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const bodyText = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}${bodyText ? "：" + bodyText.slice(0, 200) : ""}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();
      for (const ev of events) {
        if (!ev.startsWith("data: ")) continue;
        const payload = JSON.parse(ev.slice(6));
        if (payload.type === "delta") {
          if (bubble.classList.contains("thinking")) {
            clearInterval(timer);
            bubble.classList.remove("thinking");
            bubble.textContent = "";
            rawText = "";
          }
          rawText += payload.content;
          throttledRender(bubble, rawText);
        } else if (payload.type === "message") {
          clearInterval(timer);
          cancelThrottledRender();  // 防止旧气泡的迟到节流渲染覆盖模板
          const wasThinking = bubble.classList.contains("thinking");
          bubble.classList.remove("thinking");
          if (bubble.textContent && !wasThinking) bubble = addMessage("assistant", "");
          renderMarkdownInto(bubble, payload.content);
          rawText = "";
          // 模板渲染完后可能还有 LLM 流，继续保持等待提示
          bubble = addMessage("assistant", "思考中…");
          bubble.classList.add("thinking");
        } else if (payload.type === "tool_read") {
          // AI 触发读文件：封当前泡 → 插入读取 chip → 开新泡等续写
          cancelThrottledRender();
          const wasThinking = bubble.classList.contains("thinking");
          bubble.classList.remove("thinking");
          if (wasThinking && !rawText) {
            bubble.parentElement.remove();  // READ 是首个输出，占位泡无内容
          } else if (rawText) {
            renderMarkdownInto(bubble, rawText);
          }
          addToolReadChip(payload);
          rawText = "";
          bubble = addMessage("assistant", "思考中…");
          bubble.classList.add("thinking");
        } else if (payload.type === "error") {
          clearInterval(timer);
          if (bubble.classList.contains("thinking") || !bubble.textContent) {
            bubble.parentElement.remove();
          }
          bubble = addMessage("error", payload.content);
        } else if (payload.type === "done") {
          // 终渲染（流式期间是节流渲染）；先取消未触发的节流，防旧快照回退
          cancelThrottledRender();
          if (rawText && bubble.classList.contains("md")) {
            renderMarkdownInto(bubble, rawText);
          }
        }
        scrollToBottom();
      }
    }
    // 清理：无 LLM 流的指令（如 FAIL-FAST）会留下占位泡
    if (!rawText && (!bubble.textContent || bubble.classList.contains("thinking"))) {
      bubble.parentElement.remove();
    }
  } catch (err) {
    // 协议外失败（断网/非 2xx/服务重启）：清占位泡并给出可见错误
    cancelThrottledRender();
    if (bubble && bubble.parentElement &&
        (bubble.classList.contains("thinking") || !bubble.textContent)) {
      bubble.parentElement.remove();
    }
    addMessage("error", `请求失败：${err.message || err}`);
  } finally {
    clearInterval(timer);
    streaming = false;
    setSendEnabled(true);
    refreshState();
  }
}

function sendCommand(text) { streamPost("/api/command", text); }

form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (streaming) { showToast("上一条回复生成中，请稍候…"); return; }
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  autosizeInput();
  closeCmdMenu();
  const isCommand = /^\[.+\]/.test(text) ||
    ["重新开始今日学习", "重新开始", "恢复学习"].includes(text);
  streamPost(isCommand ? "/api/command" : "/api/chat", text);
});

// 多行输入：Enter 发送（输入法组词中除外），Shift+Enter 换行；随内容自动增高
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && cmdMenuOpen) { closeCmdMenu(); return; }
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (cmdMenuOpen) {
      const first = cmdMenu.querySelector("button");
      if (first) { first.onclick(); return; }
    }
    form.requestSubmit();
  }
});
function autosizeInput() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
}
inputEl.addEventListener("input", autosizeInput);

// ---------- 侧边栏 ----------

document.getElementById("toggle-sidebar").onclick = () => {
  const sb = document.getElementById("sidebar");
  sb.classList.toggle("collapsed");
  document.getElementById("toggle-sidebar").textContent =
    sb.classList.contains("collapsed") ? "⇥" : "⇤";
  document.getElementById("expand-sidebar").classList.toggle(
    "hidden", !sb.classList.contains("collapsed"));
};
document.getElementById("expand-sidebar").onclick = () => {
  document.getElementById("sidebar").classList.remove("collapsed");
  document.getElementById("expand-sidebar").classList.add("hidden");
  document.getElementById("toggle-sidebar").textContent = "⇤";
};

// ---------- 学习资料弹窗 ----------

const docModal = document.getElementById("doc-modal");
document.getElementById("open-docs").onclick = () => openDoc("memory");
document.getElementById("doc-close").onclick = () => docModal.classList.add("hidden");
docModal.addEventListener("click", (e) => {
  if (e.target === docModal) docModal.classList.add("hidden");
});
document.querySelectorAll(".doc-tab").forEach(tab => {
  tab.onclick = () => openDoc(tab.dataset.doc);
});

async function openDoc(name) {
  document.querySelectorAll(".doc-tab").forEach(t =>
    t.classList.toggle("active", t.dataset.doc === name));
  const box = document.getElementById("doc-content");
  box.textContent = "加载中…";
  docModal.classList.remove("hidden");
  const res = await fetch(`/api/doc?name=${name}`);
  const r = await res.json();
  document.getElementById("doc-title").textContent = r.title || "学习资料";
  renderMarkdownInto(box, r.ok ? r.content : `加载失败：${r.error}`);
}

// ---------- 代码浏览器（源码学习模式面板） ----------

const codePanel = document.getElementById("code-panel");
const codeTreeEl = document.getElementById("code-tree");
const codeContentEl = document.getElementById("code-content");
const floatBtn = document.getElementById("snippet-float");
let codeState = { root: "", path: "", lang: "plaintext" };
let snippetSel = null;
let lastMouse = { x: 0, y: 0 };

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
};

async function loadCodeRoots(keepSelection) {
  const res = await fetch("/api/code/roots");
  const { roots } = await res.json();
  const sel = document.getElementById("code-root-select");
  sel.innerHTML = "";
  for (const r of roots) {
    sel.insertAdjacentHTML("beforeend",
      `<option value="${r.name}" ${r.exists ? "" : "disabled"}>${r.name}${r.exists ? "" : "（目录不存在）"}</option>`);
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
  codeContentEl.innerHTML = '<div class="code-hint">选择文件查看代码</div>';
  loadTreeLevel(codeState.root, "", codeTreeEl, true);
};

async function loadTreeLevel(root, rel, container, replace) {
  const res = await fetch(`/api/code/tree?root=${encodeURIComponent(root)}&path=${encodeURIComponent(rel)}`);
  const r = await res.json();
  if (!r.ok) { container.innerHTML = `<div class="code-hint">${r.error}</div>`; return; }
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

async function openCodeFile(root, rel) {
  document.getElementById("code-file-path").textContent = `${root}/${rel}`;
  codeContentEl.innerHTML = '<div class="code-hint">加载中…</div>';
  floatBtn.classList.add("hidden");
  const res = await fetch(`/api/code/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(rel)}`);
  const r = await res.json();
  if (!r.ok) { codeContentEl.innerHTML = `<div class="code-hint">${r.error}</div>`; return; }
  codeState = { root, path: rel, lang: r.lang };
  const lines = r.content.split("\n");
  document.getElementById("csb-path").textContent = `${root}/${rel}`;
  document.getElementById("csb-meta").textContent = `${r.lang} · ${lines.length} 行 · UTF-8`;
  const wrap = document.createElement("div");
  wrap.className = "code-wrap";
  wrap.style.position = "relative";  // 行高亮定位基准
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
  if (codePanel.classList.contains("hidden")) {
    floatBtn.classList.add("hidden");
    return;
  }
  snippetSel = getSnippetSelection();
  if (snippetSel && snippetSel.text.trim()) {
    floatBtn.classList.remove("hidden");
    // 浮动按钮出现在选区旁（防越界）
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
  inputEl.value =
    `\`${codeState.root}/${codeState.path}:${ref}\`\n` +
    "```" + codeState.lang + "\n" + text + "\n```\n\n我的问题：";
  autosizeInput();
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

// ---------- 双模式（知识学习 / 源码学习） ----------

const modeBtns = {
  tutor: document.getElementById("mode-tutor"),
  pair: document.getElementById("mode-pair"),
};

function setLayout(mode) {
  document.body.dataset.layout = mode;
  localStorage.setItem("layout", mode);
  modeBtns.tutor.classList.toggle("active", mode === "tutor");
  modeBtns.pair.classList.toggle("active", mode === "pair");
  if (mode === "pair") {
    codePanel.classList.remove("hidden");  // 源码学习模式强制打开代码面板
    if (!codeTreeEl.querySelector(".tree-row")) loadCodeRoots();
  } else {
    codePanel.classList.add("hidden");
    floatBtn.classList.add("hidden");
  }
}

modeBtns.tutor.onclick = () => setLayout("tutor");
modeBtns.pair.onclick = () => setLayout("pair");
setLayout(localStorage.getItem("layout") || "tutor");

// ---------- 清空历史 ----------

document.getElementById("reset-history").onclick = async () => {
  if (!confirm("清空对话历史？（学习数据不受影响）")) return;
  const res = await fetch("/api/session/reset", { method: "POST" });
  const r = await res.json();
  addMessage("assistant", `对话历史已清空（${r.cleared} 条）。学习进度数据未受影响。`);
};

// ---------- 模型配置弹窗 ----------

const llmModal = document.getElementById("llm-modal");
let llmConfigCache = null;

document.getElementById("open-llm-config").onclick = openLlmConfig;
document.getElementById("llm-close").onclick = () => llmModal.classList.add("hidden");
llmModal.addEventListener("click", (e) => {
  if (e.target === llmModal) llmModal.classList.add("hidden");
});

async function openLlmConfig() {
  const res = await fetch("/api/llm-config");
  llmConfigCache = await res.json();
  const cfg = llmConfigCache;

  const providerSel = document.getElementById("llm-provider");
  const fallbackSel = document.getElementById("llm-fallback");
  providerSel.innerHTML = "";
  fallbackSel.innerHTML = '<option value="">（无）</option>';
  for (const p of cfg.providers) {
    providerSel.insertAdjacentHTML("beforeend",
      `<option value="${p.name}" ${p.name === cfg.provider ? "selected" : ""}>${p.label}</option>`);
    fallbackSel.insertAdjacentHTML("beforeend",
      `<option value="${p.name}" ${p.name === cfg.fallback_provider ? "selected" : ""}>${p.label}</option>`);
  }
  document.getElementById("llm-warmup").checked = cfg.warmup_on_start;

  const box = document.getElementById("provider-sections");
  box.innerHTML = "";
  for (const [name, s] of Object.entries(cfg.sections)) {
    const label = (cfg.providers.find(p => p.name === name) || {}).label || name;
    box.insertAdjacentHTML("beforeend", `
      <fieldset class="provider-fieldset" data-section="${name}">
        <legend>${label}</legend>
        <div class="form-row"><label>模型 ID</label>
          <input class="cfg-model" value="${s.model}"></div>
        <div class="form-row"><label>Base URL</label>
          <input class="cfg-baseurl" value="${s.base_url || ""}"></div>
        <div class="form-row"><label>API Key</label>
          <input class="cfg-key" type="password" placeholder="${s.has_key ? "当前: " + s.api_key_masked + "（留空保持不变）" : "未配置"}"></div>
        <div class="form-row"><label></label>
          <button class="cfg-test" data-section="${name}">测试连接</button>
          <span class="test-result" id="test-${name}"></span></div>
      </fieldset>`);
  }
  document.getElementById("llm-status").textContent = "";
  llmModal.classList.remove("hidden");
}

document.addEventListener("click", async (e) => {
  if (!e.target.classList.contains("cfg-test")) return;
  if (!e.target.closest("#provider-sections")) return;  // 只响应模型配置里的测试按钮
  const section = e.target.dataset.section;
  const el = document.getElementById(`test-${section}`);
  el.textContent = "测试中…";
  el.className = "test-result";
  await saveLlmConfig(true);
  const res = await fetch("/api/llm-config/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ section }),
  });
  const r = await res.json();
  el.textContent = r.ok ? r.detail : `失败: ${r.error}`;
  el.classList.add(r.ok ? "ok" : "fail");
});

document.getElementById("llm-save").onclick = () => saveLlmConfig(false);

async function saveLlmConfig(silent) {
  const sections = {};
  document.querySelectorAll(".provider-fieldset").forEach(fs => {
    sections[fs.dataset.section] = {
      model: fs.querySelector(".cfg-model").value.trim(),
      base_url: fs.querySelector(".cfg-baseurl").value.trim(),
      api_key: fs.querySelector(".cfg-key").value.trim(),
    };
  });
  const body = {
    provider: document.getElementById("llm-provider").value,
    fallback_provider: document.getElementById("llm-fallback").value,
    warmup_on_start: document.getElementById("llm-warmup").checked,
    sections,
  };
  const res = await fetch("/api/llm-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const r = await res.json();
  const status = document.getElementById("llm-status");
  if (r.ok) {
    status.textContent = "已保存并热生效（无需重启）。";
    status.className = "ok";
    if (!silent) setTimeout(() => llmModal.classList.add("hidden"), 800);
  } else {
    status.textContent = `保存失败: ${r.error}`;
    status.className = "fail";
  }
  return r.ok;
}

// ---------- 工作区（切换 / 新建初始化向导 / 重新扫描） ----------

const wsMenu = document.getElementById("ws-menu");
const wsModal = document.getElementById("ws-modal");

async function loadWorkspaces() {
  try {
    const res = await fetch("/api/workspaces");
    const data = await res.json();
    const active = data.workspaces.find(w => w.active);
    document.getElementById("ws-title").textContent = active ? active.title : "工作区";
    wsMenu.innerHTML = "";
    for (const w of data.workspaces) {
      const item = document.createElement("div");
      item.className = "ws-item" + (w.active ? " active" : "");
      item.innerHTML = `<span class="ws-label">${w.active ? "✓ " : ""}${escapeHtml(w.title)}</span>` +
        `<span class="ws-slug">${escapeHtml(w.slug)}</span>` +
        `<span class="ws-ops">` +
        `<button class="ws-op" data-op="export" title="导出学习数据（zip）">⬇</button>` +
        (w.active ? "" : `<button class="ws-op" data-op="delete" title="删除工作区">✕</button>`) +
        `</span>`;
      if (!w.active) {
        item.querySelector(".ws-label").onclick = () => switchWorkspace(w.slug);
        item.querySelector(".ws-slug").onclick = () => switchWorkspace(w.slug);
      }
      item.querySelector('[data-op="export"]').onclick = (e) => {
        e.stopPropagation();
        window.open(`/api/workspaces/export?slug=${encodeURIComponent(w.slug)}`);
      };
      const delBtn = item.querySelector('[data-op="delete"]');
      if (delBtn) delBtn.onclick = (e) => {
        e.stopPropagation();
        deleteWorkspace(w.slug, w.title);
      };
      wsMenu.appendChild(item);
    }
    const sep = document.createElement("div");
    sep.className = "ws-sep";
    wsMenu.appendChild(sep);
    const newBtn = document.createElement("button");
    newBtn.className = "ws-item";
    newBtn.textContent = "＋ 新建工作区";
    newBtn.onclick = () => { wsMenu.classList.add("hidden"); openWsWizard(); };
    const rescanBtn = document.createElement("button");
    rescanBtn.className = "ws-item";
    rescanBtn.textContent = "↻ 重新扫描项目结构";
    rescanBtn.onclick = rescanWorkspace;
    wsMenu.appendChild(newBtn);
    wsMenu.appendChild(rescanBtn);
  } catch (e) { /* 服务未就绪时静默 */ }
}

document.getElementById("ws-current").onclick = (e) => {
  e.stopPropagation();
  wsMenu.classList.toggle("hidden");
};
document.addEventListener("click", (e) => {
  if (!wsMenu.classList.contains("hidden") &&
      !wsMenu.contains(e.target) && e.target.id !== "ws-current") {
    wsMenu.classList.add("hidden");
  }
});

async function switchWorkspace(slug) {
  wsMenu.classList.add("hidden");
  const res = await fetch("/api/workspaces/switch", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug }),
  });
  const r = await res.json();
  if (r.ok) location.reload();
  else showToast(`切换失败：${r.error}`);
}

async function rescanWorkspace() {
  wsMenu.classList.add("hidden");
  showToast("正在重新扫描并生成 Project.md（约 1 分钟）…");
  const res = await fetch("/api/workspaces/rescan", { method: "POST" });
  const r = await res.json();
  showToast(r.ok ? "Project.md 已刷新" : `刷新失败：${r.error}`);
}

async function deleteWorkspace(slug, title) {
  if (!confirm(`确定删除工作区「${title}」？（默认保留磁盘上的学习数据）`)) return;
  const alsoData = confirm("要同时删除磁盘上的学习数据吗？（不可恢复）\n确定 = 删除数据；取消 = 保留数据");
  wsMenu.classList.add("hidden");
  const res = await fetch("/api/workspaces/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug, delete_data: alsoData }),
  });
  const r = await res.json();
  if (r.ok) { showToast(`工作区「${title}」已删除`); loadWorkspaces(); }
  else showToast(`删除失败：${r.error}`);
}

// ---- 初始化向导 ----

async function loadPresetOptions() {
  const sel = document.getElementById("ws-preset");
  if (sel.options.length) return;
  try {
    const r = await (await fetch("/api/workspaces/presets")).json();
    for (const p of r.presets) {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = p.name ? `${p.name} — ${p.description}` : p.description;
      sel.appendChild(opt);
    }
  } catch (e) { /* 预设加载失败时留空，创建按默认模式 */ }
}

function openWsWizard() {
  document.getElementById("ws-status").textContent = "";
  document.getElementById("ws-scan-preview").classList.add("hidden");
  loadPresetOptions();
  wsModal.classList.remove("hidden");
}
document.getElementById("ws-close").onclick = () => wsModal.classList.add("hidden");
wsModal.addEventListener("click", (e) => {
  if (e.target === wsModal) wsModal.classList.add("hidden");
});

document.getElementById("ws-preview-btn").onclick = async () => {
  const path = document.getElementById("ws-project-dir").value.trim();
  if (!path) return;
  const box = document.getElementById("ws-scan-preview");
  box.textContent = "扫描中…";
  box.classList.remove("hidden");
  const res = await fetch(`/api/workspaces/scan-preview?path=${encodeURIComponent(path)}`);
  const r = await res.json();
  box.textContent = r.ok ? r.profile : `扫描失败：${r.error}`;
};

document.getElementById("ws-create").onclick = async () => {
  const status = document.getElementById("ws-status");
  const body = {
    project_dir: document.getElementById("ws-project-dir").value.trim(),
    slug: document.getElementById("ws-slug").value.trim(),
    title: document.getElementById("ws-title-input").value.trim(),
    goal: document.getElementById("ws-goal").value.trim(),
    total_days: parseInt(document.getElementById("ws-days").value) || 25,
    replica_name: document.getElementById("ws-replica").value.trim(),
    preset: document.getElementById("ws-preset").value,
  };
  if (!body.project_dir || !body.slug) {
    status.textContent = "项目目录与标识为必填项。";
    status.className = "fail";
    return;
  }
  const btn = document.getElementById("ws-create");
  btn.disabled = true;
  status.textContent = "初始化中：扫描项目 → LLM 生成 Project.md / Study.md → 程序校验（约 1-2 分钟，请耐心等待）…";
  status.className = "working";
  try {
    const res = await fetch("/api/workspaces/create", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const r = await res.json();
    if (r.ok) {
      status.textContent = "初始化完成，正在切换…";
      status.className = "ok";
      setTimeout(() => location.reload(), 600);
    } else {
      status.textContent = `初始化失败：${r.error}`;
      status.className = "fail";
    }
  } catch (e) {
    status.textContent = `请求异常：${e}`;
    status.className = "fail";
  } finally {
    btn.disabled = false;
  }
};

// ---------- 启动 ----------

refreshState();
loadCommands();
loadHistory();
loadWorkspaces();
setInterval(refreshState, 10000);
