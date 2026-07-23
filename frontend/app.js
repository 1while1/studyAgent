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
  if (p.kind === "doc") {
    // 资料库读取（备课预取 / READ_DOC）：展示 chip，不跳转代码浏览器
    chip.classList.add("doc-chip");
    if (p.prefetch) {
      const n = (p.sources || []).length;
      chip.textContent = `📚 已备课：${n} 份教材节选`;
      chip.title = (p.sources || []).join("\n");
    } else if (p.ok) {
      chip.textContent = `📄 AI 阅读了《${p.title || p.doc}》` +
        (p.section ? `·「${p.section}」` : "·章节目录");
      chip.title = p.doc;
    } else {
      chip.textContent = `📄 资料读取失败：${p.doc}${p.error ? "（" + p.error + "）" : ""}`;
    }
  } else if (p.kind === "action") {
    // planner ACTION（M5c）：工具调用 chip，不跳转
    chip.classList.add("doc-chip");
    chip.textContent = p.ok
      ? `🔧 AI 调用了工具 ${p.tool}`
      : `🔧 工具调用失败：${p.tool || "?"}${p.error ? "（" + p.error + "）" : ""}`;
    chip.title = p.reason || "";
  } else if (p.ok) {
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
  if (name === "materials") { openMaterials(); return; }
  if (name === "interview_qa") { openQa(false); return; }  // M4：话术层收编为卡片视图
  const box = document.getElementById("doc-content");
  box.textContent = "加载中…";
  docModal.classList.remove("hidden");
  const res = await fetch(`/api/doc?name=${name}`);
  const r = await res.json();
  document.getElementById("doc-title").textContent = r.title || "学习资料";
  renderMarkdownInto(box, r.ok ? r.content : `加载失败：${r.error}`);
}

// ---------- 资料库 ----------

async function openMaterials() {
  const box = document.getElementById("doc-content");
  box.textContent = "加载中…";
  docModal.classList.remove("hidden");
  document.getElementById("doc-title").textContent = "资料库";
  const res = await fetch("/api/materials");
  const r = await res.json();
  box.innerHTML = "";
  if (!r.ok) { box.textContent = `加载失败：${r.error || "未知错误"}`; return; }
  if (!r.configured) {
    box.textContent = "当前工作区未配置资料目录（settings.toml 工作区的 materials_dir 键）。";
    return;
  }
  // 工具条：重新扫描 + 手工注册
  const bar = document.createElement("div");
  bar.className = "mat-toolbar";
  const rs = document.createElement("button");
  rs.textContent = "↻ 重新扫描";
  rs.onclick = async () => {
    rs.disabled = true; rs.textContent = "扫描中…";
    await fetch("/api/materials/rescan", { method: "POST" });
    openMaterials();
  };
  const inp = document.createElement("input");
  inp.type = "text";
  inp.placeholder = "注册外部文件路径或视频链接…";
  const regBtn = document.createElement("button");
  regBtn.textContent = "注册";
  regBtn.onclick = async () => {
    const source = inp.value.trim();
    if (!source) return;
    const rr = await fetch("/api/materials/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    const rj = await rr.json();
    if (!rj.ok) { showToast(rj.error || "注册失败"); return; }
    showToast(`已注册：${rj.id}`);
    openMaterials();
  };
  bar.append(rs, inp, regBtn);
  box.appendChild(bar);
  // 资料列表
  const list = document.createElement("div");
  list.className = "mat-list";
  if (!r.materials.length) list.textContent = "（资料目录为空）";
  for (const m of r.materials) {
    const item = document.createElement("div");
    item.className = "mat-item" + (m.status === "error" ? " err" : "");
    const status = m.status === "parsed" ? `${m.headings} 章`
      : m.status === "error" ? "解析失败" : "未解析";
    const type = document.createElement("span");
    type.className = "mat-type"; type.textContent = m.type;
    const title = document.createElement("span");
    title.className = "mat-name"; title.textContent = m.id;
    const st = document.createElement("span");
    st.className = "mat-status"; st.textContent = status;
    item.append(type, title, st);
    item.title = m.error || m.indexed_at || m.id;
    if (m.status === "parsed") item.onclick = () => openMaterialPreview(m.id);
    list.appendChild(item);
  }
  box.appendChild(list);
}

async function openMaterialPreview(id) {
  const box = document.getElementById("doc-content");
  box.textContent = "加载中…";
  const res = await fetch(`/api/materials/preview?id=${encodeURIComponent(id)}`);
  const r = await res.json();
  box.innerHTML = "";
  const back = document.createElement("button");
  back.className = "mat-back";
  back.textContent = "← 返回资料列表";
  back.onclick = openMaterials;
  box.appendChild(back);
  const body = document.createElement("div");
  body.className = "markdown-body";
  box.appendChild(body);
  document.getElementById("doc-title").textContent = r.title || "资料预览";
  renderMarkdownInto(body, r.ok ? r.content : `加载失败：${r.error}`);
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
  if (mcEditor) mcEditor.updateOptions({ wordWrap: on ? "on" : "off" });
};

// 轻提示（.toast 样式早已存在，M6 补上助手）
function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

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
  showCodeHint("选择文件查看代码");
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

// ---- Monaco（M6：pair 布局首次打开文件时动态加载；失败静默降级 legacy 渲染） ----
let monacoReady = null;   // Promise|null（加载单例）
let mcEditor = null;      // monaco editor 实例（null = legacy 模式）
let mcDecorations = [];   // 行高亮 decoration 句柄

function loadMonaco() {
  if (monacoReady) return monacoReady;
  monacoReady = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/vendor/monaco/vs/loader.js";
    s.onload = () => {
      try {
        const base = location.origin + "/vendor/monaco/vs";
        // worker 经 data-URL 包装引入（无构建步骤下的官方做法）
        // 语言智能感知 worker 各指各的真实文件，其余走通用 editor worker
        const WORKERS = {
          "vs/language/css/cssWorker": "language/css/cssWorker.js",
          "vs/language/html/htmlWorker": "language/html/htmlWorker.js",
          "vs/language/json/jsonWorker": "language/json/jsonWorker.js",
          "vs/language/typescript/tsWorker": "language/typescript/tsWorker.js",
        };
        window.MonacoEnvironment = {
          getWorkerUrl: (moduleId) => {
            const rel = WORKERS[moduleId] || "base/worker/workerMain.js";
            return "data:text/javascript;charset=utf-8," + encodeURIComponent(
              `self.MonacoEnvironment={baseUrl:'${base}/'};importScripts('${base}/${rel}');`);
          },
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

// 代码区提示（Monaco 宿主存在时先销毁编辑器，防 innerHTML 抹掉其 DOM）
function showCodeHint(text) {
  if (mcEditor) {
    mcEditor.dispose();
    mcEditor = null;
    window.__codeEditor = null;
    codeContentEl.classList.remove("mc-host");
  }
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
    body: JSON.stringify({ root: codeState.root, path: codeState.path, content: mcEditor.getValue() }),
  });
  const r = await res.json();
  if (r.ok) { setDirty(false); toast(`已保存 ${codeState.path}`); }
  else toast(`保存失败：${r.error}`);
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
      value: r.content, language: r.lang, theme: "vs-dark",
      readOnly: !r.editable,
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
  } else {
    mcEditor.setValue(r.content);
    monaco.editor.setModelLanguage(mcEditor.getModel(), r.lang);
    mcEditor.updateOptions({ readOnly: !r.editable });
  }
  mcEditor.setScrollTop(0);
  mcEditor.setPosition({ lineNumber: 1, column: 1 });
  mcDecorations = mcEditor.deltaDecorations(mcDecorations, []);
  setDirty(false);  // setValue 会触发 change 事件误标脏
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
  codeContentEl.classList.remove("mc-host");
  const lines = r.content.split("\n");
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

async function openCodeFile(root, rel) {
  document.getElementById("code-file-path").textContent = `${root}/${rel}`;
  floatBtn.classList.add("hidden");
  const res = await fetch(`/api/code/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(rel)}`);
  const r = await res.json();
  if (!r.ok) { showCodeHint(r.error); return; }
  codeState = { root, path: rel, lang: r.lang, editable: !!r.editable };
  document.getElementById("csb-path").textContent = `${root}/${rel}`;
  document.getElementById("csb-meta").textContent =
    `${r.lang} · ${r.lines || r.content.split("\n").length} 行 · UTF-8${r.editable ? " · 可编辑" : " · 只读"}`;
  updateSaveBtn();
  try {
    await loadMonaco();
    openInMonaco(r);
  } catch (e) {
    openLegacy(r);  // vendor 缺失/加载失败：静默降级旧渲染（mermaid 同款策略）
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
  if (mcEditor) {  // Monaco：decoration + 滚动定位（替代旧绝对定位 div）
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

// ---------- 双模式（知识学习=study/tutor · 源码学习=code/pair，M6 双轴钉死） ----------

const modeBtns = {
  tutor: document.getElementById("mode-tutor"),
  pair: document.getElementById("mode-pair"),
};
const panelShowBtn = document.getElementById("code-panel-show");

// layout（tutor/pair）= 展示层偏好；mode（study/code）= 会话级 agent 状态（服务端）
function setLayout(mode) {
  document.body.dataset.layout = mode;
  localStorage.setItem("layout", mode);
  modeBtns.tutor.classList.toggle("active", mode === "tutor");
  modeBtns.pair.classList.toggle("active", mode === "pair");
  if (mode === "pair") {
    // code 模式默认展示代码面板；用户可收起（覆盖仅作用面板显隐，不换引擎）
    const hiddenPref = localStorage.getItem("codePanelHidden") === "1";
    codePanel.classList.toggle("hidden", hiddenPref);
    panelShowBtn.classList.toggle("hidden", !hiddenPref);
    if (!hiddenPref && !codeTreeEl.querySelector(".tree-row")) loadCodeRoots();
  } else {
    codePanel.classList.add("hidden");
    panelShowBtn.classList.add("hidden");
    floatBtn.classList.add("hidden");
  }
}

// 模式按钮 = 切换 agent 模式（服务端 session.mode），布局跟随默认配对
async function setAgentMode(mode) {
  try {
    const res = await fetch("/api/session/mode", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const r = await res.json();
    if (!r.ok) { toast(r.error || "模式切换失败"); return; }
    setLayout(mode === "code" ? "pair" : "tutor");
    if (mode === "code") toast("已切换到源码学习（agent 模式：AI 可建 demo / 改文件 / 起进程）");
  } catch (e) {
    toast("模式切换失败：" + e.message);
  }
}
modeBtns.tutor.onclick = () => setAgentMode("study");
modeBtns.pair.onclick = () => setAgentMode("code");

// 面板显隐（覆盖入口成对存在，吸取"侧栏收不回"教训）
document.getElementById("code-panel-hide").onclick = () => {
  codePanel.classList.add("hidden");
  localStorage.setItem("codePanelHidden", "1");
  panelShowBtn.classList.remove("hidden");
};
panelShowBtn.onclick = () => {
  localStorage.setItem("codePanelHidden", "0");
  panelShowBtn.classList.add("hidden");
  if (document.body.dataset.layout !== "pair") setLayout("pair");
  codePanel.classList.remove("hidden");
  if (!codeTreeEl.querySelector(".tree-row")) loadCodeRoots();
};

// 初始布局：以服务端会话模式为准；接口不可达时退回本地布局记忆
(async () => {
  let mode = null;
  try {
    const res = await fetch("/api/session/mode");
    mode = (await res.json()).mode;
  } catch (e) { /* 离线降级 */ }
  setLayout(mode ? (mode === "code" ? "pair" : "tutor")
                 : (localStorage.getItem("layout") || "tutor"));
})();

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
  // 上下文窗口区（M5b）：预算/触发比例可调，模型上限与生效预算只读预览
  const c = cfg.context || {};
  const budgetInput = document.getElementById("ctx-budget");
  const ratioInput = document.getElementById("ctx-ratio");
  budgetInput.value = c.budget_tokens ?? 256000;
  ratioInput.value = c.trigger_ratio ?? 0.8;
  const updateCtxPreview = () => {
    const b = parseInt(budgetInput.value, 10) || 0;
    document.getElementById("ctx-budget-k").textContent = `≈${Math.round(b / 1024)}K`;
    const naive = Math.max(1024, Math.min(b, c.model_limit ?? 32768));
    document.getElementById("ctx-preview").textContent =
      `当前模型 ${c.model || "?"} 上下文上限 ${c.model_limit ?? "?"} tokens；` +
      `预计生效预算 ≈${naive}（未计输出预留，以保存后为准）；当前生效 ${c.effective_budget ?? "?"}`;
  };
  budgetInput.oninput = updateCtxPreview;
  updateCtxPreview();
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
  // 上下文项：非法输入不静默丢弃——跳过该项并在结果中明示（空 = 未改动）
  const ctxBudgetRaw = document.getElementById("ctx-budget").value.trim();
  const ctxRatioRaw = document.getElementById("ctx-ratio").value.trim();
  let ctxInvalid = false;
  let context_budget_tokens = null, context_trigger_ratio = null;
  if (ctxBudgetRaw !== "") {
    const v = parseInt(ctxBudgetRaw, 10);
    if (Number.isFinite(v) && v > 0) context_budget_tokens = v;
    else ctxInvalid = true;
  }
  if (ctxRatioRaw !== "") {
    const v = parseFloat(ctxRatioRaw);
    if (Number.isFinite(v) && v > 0) context_trigger_ratio = v;
    else ctxInvalid = true;
  }
  const body = {
    provider: document.getElementById("llm-provider").value,
    fallback_provider: document.getElementById("llm-fallback").value,
    warmup_on_start: document.getElementById("llm-warmup").checked,
    sections,
    context_budget_tokens,
    context_trigger_ratio,
  };
  const res = await fetch("/api/llm-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const r = await res.json();
  const status = document.getElementById("llm-status");
  if (r.ok) {
    status.textContent = "已保存并热生效（无需重启）。"
      + (ctxInvalid ? " 注意：上下文项输入无效，该项未保存。" : "");
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

// ---------- 访问密码门 + 可观测性（M2） ----------

const loginOverlay = document.getElementById("login-overlay");
const loginPwd = document.getElementById("login-password");
const loginErr = document.getElementById("login-error");
const _rawFetch = window.fetch.bind(window);
let _loginPromise = null;

function ensureLogin() {
  if (_loginPromise) return _loginPromise;
  loginOverlay.classList.remove("hidden");
  loginErr.textContent = "";
  loginPwd.value = "";
  setTimeout(() => loginPwd.focus(), 50);
  _loginPromise = new Promise((resolve) => {
    const submit = document.getElementById("login-submit");
    submit.onclick = async () => {
      const res = await _rawFetch("/api/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: loginPwd.value }),
      });
      const r = await res.json();
      if (r.ok) {
        loginOverlay.classList.add("hidden");
        _loginPromise = null;
        resolve(true);
      } else {
        loginErr.textContent = r.error || "登录失败";
      }
    };
    loginPwd.onkeydown = (e) => {
      if (e.key === "Enter") submit.click();
    };
  });
  return _loginPromise;
}

// fetch 包装：/api/ 返回 401 → 弹登录层 → 登录成功重放一次原请求
window.fetch = async (input, init) => {
  const res = await _rawFetch(input, init);
  const url = typeof input === "string" ? input : input.url;
  if (res.status === 401 && url.includes("/api/") && !url.includes("/api/auth/")) {
    const ok = await ensureLogin();
    if (ok) return _rawFetch(input, init);
  }
  return res;
};

// ---- LLM 状态条 ----

const llmStatusEl = document.getElementById("llm-pill");
async function refreshLlmStatus() {
  try {
    const r = await (await fetch("/api/observability/status")).json();
    llmStatusEl.classList.remove("hidden", "err");
    const last = r.last_call;
    if (last) {
      llmStatusEl.textContent = last.ok
        ? `${last.provider} · ${(last.latency_ms / 1000).toFixed(1)}s`
        : `${last.provider} · 失败`;
      llmStatusEl.title = last.ok
        ? `模型 ${last.model} · ${last.ts} · 今日 ${r.today.calls} 次调用（自服务启动）`
        : `最近调用失败：${last.error}`;
      if (!last.ok) llmStatusEl.classList.add("err");
    } else {
      llmStatusEl.textContent = r.provider;
      llmStatusEl.title = `主渠道 ${r.provider}（服务启动后尚未调用 LLM）`;
    }
  } catch (e) { /* 服务未就绪时静默 */ }
}

// ---- Token 用量弹窗 ----

const usageModal = document.getElementById("usage-modal");
document.getElementById("open-usage").onclick = openUsage;
document.getElementById("usage-close").onclick = () => usageModal.classList.add("hidden");
usageModal.addEventListener("click", (e) => {
  if (e.target === usageModal) usageModal.classList.add("hidden");
});

async function openUsage() {
  usageModal.classList.remove("hidden");
  const rowsEl = document.getElementById("usage-rows");
  const summaryEl = document.getElementById("usage-summary");
  rowsEl.innerHTML = "";
  summaryEl.textContent = "加载中…";
  const [u, a] = await Promise.all([
    (await fetch("/api/observability/usage?days=7")).json(),
    (await fetch("/api/auth/status")).json(),
  ]);
  const t = u.totals;
  summaryEl.textContent =
    `近 ${u.days} 天：${t.calls} 次调用（失败 ${t.failures}）· ` +
    `输入 ${t.in_tokens.toLocaleString()} tok · 输出 ${t.out_tokens.toLocaleString()} tok` +
    (t.cost ? ` · 估算成本 ¥${t.cost}` : "") +
    "（token 为实际/估算混排，仅供参考）";
  if (!u.rows.length) {
    rowsEl.innerHTML = `<tr><td colspan="8">暂无记录（agent.log 为空）</td></tr>`;
  }
  for (const g of u.rows) {
    const tr = document.createElement("tr");
    const cells = [g.date, `${g.provider} / ${g.model}`, g.task, g.calls,
                   g.failures, g.in_tokens.toLocaleString(),
                   g.out_tokens.toLocaleString(),
                   (g.cost ? `¥${g.cost}` : "—") + (g.est_calls ? `（估算×${g.est_calls}）` : "")];
    for (const c of cells) {
      const td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    }
    rowsEl.appendChild(tr);
  }
  renderUsageAuth(a);
}

function renderUsageAuth(a) {
  const area = document.getElementById("usage-auth-area");
  area.innerHTML = "";
  if (!a.gate) {
    const tip = document.createElement("span");
    tip.className = "usage-auth-tip";
    tip.textContent = "访问密码未设置（开放模式）";
    const input = document.createElement("input");
    input.type = "password";
    input.id = "setup-password";
    input.placeholder = "设置访问密码（≥6 位）";
    const btn = document.createElement("button");
    btn.textContent = "设置密码";
    btn.onclick = async () => {
      const res = await fetch("/api/auth/setup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: input.value }),
      });
      const r = await res.json();
      if (r.ok) { showToast("访问密码已设置"); openUsage(); }
      else showToast(r.error || "设置失败");
    };
    area.append(tip, input, btn);
  } else {
    const logout = document.createElement("button");
    logout.textContent = "退出登录";
    logout.onclick = async () => {
      await _rawFetch("/api/auth/logout", { method: "POST" });
      location.reload();
    };
    const clear = document.createElement("button");
    clear.textContent = "删除密码（恢复开放）";
    clear.onclick = async () => {
      if (!confirm("确定删除访问密码？删除后本助手恢复开放访问。")) return;
      const res = await fetch("/api/auth/password", { method: "DELETE" });
      const r = await res.json();
      if (r.ok) { showToast("密码已删除，恢复开放模式"); openUsage(); }
      else showToast(r.error || "删除失败");
    };
    area.append(logout, clear);
  }
}

// ---- 掌握度面板（M3 数据 / v2 全屏面板） ----

const masteryPage = document.getElementById("mastery-page");
document.getElementById("open-learner").onclick = openLearner;
document.getElementById("mastery-close").onclick = () => masteryPage.classList.add("hidden");
masteryPage.addEventListener("click", (e) => {
  if (e.target === masteryPage) masteryPage.classList.add("hidden");
});

// evidence 类型 → 人性化中文名（机器术语不进 UI）
const EV_TYPE_NAMES = {
  quiz_right: "单元考核达标", quiz_wrong: "考核未达标",
  quiz_score: "历史评分迁移",
  sync_mastered: "[同步] 已掌握", sync_stuck: "[同步] 卡壳",
  code_verify_pass: "构建验证通过", code_verify_fail: "构建未通过",
  note_distilled: "笔记销账", teach_back_pass: "口述考核通过",
  teach_back_fail: "口述考核未过", mark_wrong: "纠错标记",
};

function masteryBand(c) {
  if (!c.evidence.length) return "none";
  if (c.mastery < 0.4) return "low";
  if (c.mastery < 0.7) return "mid";
  return "high";
}

let _masteryModel = null;

async function openLearner(expandCid) {
  masteryPage.classList.remove("hidden");
  for (const id of ["ms-urgent-body", "ms-today-body", "ms-rest-body"])
    document.getElementById(id).innerHTML = "";
  const mbar = document.getElementById("learner-migrate");
  mbar.classList.add("hidden");
  const model = await (await fetch("/api/learner/model")).json();
  _masteryModel = model;

  // 迁移引导条：模型未建且有旧评分数据（幂等，逻辑与 v1 一致）
  if (!model.exists && model.has_ratings_source) {
    mbar.classList.remove("hidden");
    mbar.innerHTML = "";
    const tip = document.createElement("span");
    tip.textContent = "检测到旧评分数据，可一键迁移为掌握度证据（草稿→确认）：";
    const btn = document.createElement("button");
    btn.textContent = "生成迁移预览";
    btn.onclick = async () => {
      const r = await (await fetch("/api/learner/migrate/preview", { method: "POST" })).json();
      if (!r.ok) { showToast(r.error || "预览失败"); return; }
      tip.textContent = `草稿就绪：${r.quiz_scores} 条评分证据、${r.notes} 条卡壳/疑问笔记。`;
      btn.textContent = "确认应用迁移";
      btn.onclick = async () => {
        const r2 = await (await fetch("/api/learner/migrate/apply", { method: "POST" })).json();
        if (r2.ok) { showToast(`迁移完成：${r2.concepts} 个知识点、${r2.notes} 条笔记`); openLearner(); }
        else showToast(r2.error || "迁移失败");
      };
    };
    mbar.append(tip, btn);
  }

  // 统计卡
  const concepts = model.concepts || [];
  document.getElementById("stat-weak").textContent =
    concepts.filter(c => c.evidence.length && c.mastery < 0.4).length;
  document.getElementById("stat-due").textContent =
    concepts.filter(c => c.due).length;

  if (!concepts.length) {
    document.getElementById("ms-urgent-body").innerHTML =
      '<div class="mastery-empty-hint">（暂无知识点——完成迁移或开始学习后自动生成）</div>';
    return;
  }

  // 状态驱动分桶（战术板：状态 → 知识点，而非 Day → 知识点）
  const curDay = model.current_day;
  const isToday = (c) => c.id.startsWith(`Day${curDay}-`);
  const isUrgent = (c) => c.evidence.length && (c.due || c.mastery < 0.4);
  const urgent = concepts.filter(isUrgent).sort(
    (a, b) => (b.due - a.due) || (a.mastery - b.mastery) || a.id.localeCompare(b.id));
  const today = concepts.filter(c => isToday(c) && !isUrgent(c));
  const rest = concepts.filter(c => !isToday(c) && !isUrgent(c));

  document.getElementById("ms-today-day").textContent = curDay;
  renderMasterySection("ms-urgent", urgent,
    "🎉 没有紧急项——没有到期复习，也没有薄弱知识点，保持节奏！");
  renderMasterySection("ms-today", today,
    "（今日单元的知识点将在考核/同步后自动出现）");
  // 其余知识点：按 Day 分组，默认折叠
  document.getElementById("ms-rest-count").textContent = rest.length;
  const restBody = document.getElementById("ms-rest-body");
  const byDay = new Map();
  for (const c of rest) {
    const day = (c.id.match(/^Day(\d+)-/) || [0, "?"])[1];
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(c);
  }
  for (const [day, items] of [...byDay.entries()].sort((a, b) => a[0] - b[0])) {
    const head = document.createElement("div");
    head.className = "mastery-day";
    head.textContent = `Day ${day}`;
    restBody.appendChild(head);
    for (const c of items) restBody.appendChild(masteryRow(c));
  }
  if (!rest.length)
    restBody.innerHTML = '<div class="mastery-empty-hint">（无）</div>';

  // 侧栏预警点入：定位并展开指定知识点
  if (expandCid) {
    const row = document.querySelector(
      `.mastery-row[data-cid="${CSS.escape(expandCid)}"]`);
    if (row) {
      // 可能在「其余知识点」折叠区里，先展开
      if (row.closest("#ms-rest-body")) {
        document.getElementById("ms-rest-body").classList.remove("hidden");
        document.getElementById("ms-rest-toggle").classList.add("open");
      }
      row.scrollIntoView({ block: "center" });
      row.click();
    }
  }
}

function renderMasterySection(secId, items, emptyText) {
  const sec = document.getElementById(secId);
  const body = sec.querySelector(".m-sec-body");
  sec.querySelector(".m-sec-count").textContent = items.length;
  if (!items.length) {
    body.innerHTML = `<div class="mastery-empty-hint">${emptyText}</div>`;
    return;
  }
  for (const c of items) body.appendChild(masteryRow(c));
}

function masteryRow(c) {
  const band = masteryBand(c);
  const row = document.createElement("button");
  row.className = "mastery-row";
  row.dataset.band = band;
  row.dataset.cid = c.id;
  const top = document.createElement("div");
  top.className = "mr-top";
  // 行首：Day 标签 + 状态标记；行尾：仅百分比
  const dayTag = document.createElement("span");
  dayTag.className = "mr-day";
  dayTag.textContent = "Day" + ((c.id.match(/^Day(\d+)-/) || [0, "?"])[1]);
  top.appendChild(dayTag);
  if (c.capped) {
    const b = document.createElement("span");
    b.className = "mr-cap";
    b.textContent = "≤0.6";
    b.title = "缺构建验证通过记录，封顶 0.6";
    top.appendChild(b);
  }
  if (c.due) {
    const b = document.createElement("span");
    b.className = "mr-badge due";
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24"><circle cx="12" cy="13" r="7"/><path d="M12 10v3l2 2"/><path d="m5 3-2 2M19 3l2 2"/></svg>';
    b.title = "已到复习窗口";
    top.appendChild(b);
  }
  const title = document.createElement("span");
  title.className = "mr-title";
  title.textContent = c.title || c.id;
  title.title = `${c.id} ${c.title}`;
  top.appendChild(title);
  const pct = document.createElement("span");
  pct.className = "mr-pct";
  pct.textContent = c.evidence.length ? (c.mastery * 100).toFixed(0) + "%" : "无证据";
  top.appendChild(pct);
  row.appendChild(top);
  // 底部极细进度线（不占独立行高）
  const hair = document.createElement("div");
  hair.className = "mr-hair " + band;
  hair.style.width = Math.round(c.mastery * 100) + "%";
  row.appendChild(hair);
  row.onclick = () => toggleMasteryDetail(row, c);
  return row;
}

// 手风琴：行内展开详情（同时只展开一条）
function toggleMasteryDetail(row, c) {
  const wasOpen = row.classList.contains("open");
  document.querySelectorAll(".mastery-detail-inline").forEach(d => d.remove());
  document.querySelectorAll(".mastery-row.open").forEach(r => r.classList.remove("open"));
  if (wasOpen) return;
  row.classList.add("open");
  const box = document.createElement("div");
  box.className = "mastery-detail-inline";
  showConceptDetail(c, box);
  row.after(box);
}

function masteryAdvice(c) {
  if (!c.evidence.length)
    return "💡 建议：先完成本单元的导学与考核问答，产生第一条掌握度证据。";
  if (c.mastery < 0.4)
    return "💡 建议：掌握度偏低。可在对话中说「再讲讲这个单元」针对性补强，复盘时它也会被重点拷问。";
  if (c.capped)
    return "💡 建议：切到源码学习模式运行 [验证代码]，一次构建通过即可解除 0.6 封顶。";
  if (c.due)
    return "💡 建议：已到复习窗口。下次 [开始今日学习] 的间隔复习会自动带上它，也可以现在快速自测一遍。";
  return "✅ 状态良好，按节奏推进即可。";
}

function showConceptDetail(c, detail) {
  detail.innerHTML = "";
  const band = masteryBand(c);
  // 分数行（标题在行上已有，详情不再重复）
  const scoreLine = document.createElement("div");
  scoreLine.className = "md-score";
  const big = document.createElement("span");
  big.className = "md-big " + band;
  big.textContent = c.evidence.length ? (c.mastery * 100).toFixed(1) + "%" : "—";
  scoreLine.appendChild(big);
  const expl = document.createElement("span");
  expl.className = "md-expl";
  expl.textContent = c.capped
    ? `未封顶值 ${(c.uncapped * 100).toFixed(1)}%，缺构建验证通过记录，按规则封顶 60%`
    : c.evidence.length ? "由证据按时间衰减加权得出" : "尚无学习证据";
  scoreLine.appendChild(expl);
  detail.appendChild(scoreLine);
  // 建议行动卡
  const advice = document.createElement("div");
  advice.className = "md-advice";
  advice.textContent = masteryAdvice(c);
  detail.appendChild(advice);
  // 行动按钮：看完建议直接行动
  const actions = document.createElement("div");
  actions.className = "md-actions";
  const reteach = document.createElement("button");
  reteach.className = "md-act-btn primary";
  reteach.textContent = "👉 丢给 AI 重新讲";
  reteach.onclick = () => {
    const input = document.getElementById("input");
    input.value = `再讲讲 ${c.title || c.id}`;
    masteryPage.classList.add("hidden");
    input.focus();
    input.dispatchEvent(new Event("input"));
  };
  actions.appendChild(reteach);
  if ((c.materials || []).length) {
    const mat = document.createElement("button");
    mat.className = "md-act-btn";
    mat.textContent = "📖 查看关联资料";
    mat.onclick = () => openMaterialDirect(c.materials[0]);
    actions.appendChild(mat);
  }
  detail.appendChild(actions);
  // 先修链（小字）
  if (c.prerequisites.length) {
    const p = document.createElement("div");
    p.className = "learner-meta";
    p.textContent = `先修：${c.prerequisites.join("、")}`;
    detail.appendChild(p);
  }
  // 证据明细：默认折叠，质疑分数时才展开
  const det = document.createElement("details");
  det.className = "md-ev";
  const sum = document.createElement("summary");
  sum.textContent = `查看评估明细（${c.evidence.length} 条）`;
  det.appendChild(sum);
  if (!c.evidence.length) {
    const p = document.createElement("div");
    p.className = "learner-meta";
    p.textContent = "完成该单元的考核问答后，这里会出现第一条证据。";
    det.appendChild(p);
  } else {
    const table = document.createElement("table");
    table.className = "ev-table";
    table.innerHTML = "<thead><tr><th>行为</th><th>Δ 权重</th><th>日期</th><th>来源</th></tr></thead>";
    const tb = document.createElement("tbody");
    for (const ev of [...c.evidence].reverse()) {
      const tr = document.createElement("tr");
      const t = document.createElement("td");
      t.textContent = EV_TYPE_NAMES[ev.type] || ev.type;
      const d = document.createElement("td");
      d.textContent = (ev.delta > 0 ? "+" : "") + ev.delta;
      d.className = ev.delta >= 0 ? "delta-pos" : "delta-neg";
      const ts = document.createElement("td");
      ts.textContent = ev.ts;
      const src = document.createElement("td");
      src.textContent = ev.source_ref;
      src.className = "ev-src";
      src.title = ev.source_ref;
      tr.append(t, d, ts, src);
      tb.appendChild(tr);
    }
    table.appendChild(tb);
    det.appendChild(table);
    const decay = document.createElement("div");
    decay.className = "md-decay";
    decay.textContent = "证据随时间衰减：半衰期 14 天（14 天前的证据权重减半）。保持复习与实战，掌握度才不会回落。";
    det.appendChild(decay);
  }
  detail.appendChild(det);
}

// 关联资料直达（先开资料库再进预览，避免与列表渲染竞态）
async function openMaterialDirect(id) {
  masteryPage.classList.add("hidden");
  await openMaterials();
  openMaterialPreview(id);
}

// ---- 抽屉 tab 与「其余知识点」折叠 ----

document.querySelectorAll(".drawer-tab").forEach(t => {
  t.onclick = () => {
    document.querySelectorAll(".drawer-tab").forEach(x =>
      x.classList.toggle("active", x === t));
    const tab = t.dataset.mtab;
    document.getElementById("mastery-tactical").classList.toggle("hidden", tab !== "tactical");
    document.getElementById("mastery-radar").classList.toggle("hidden", tab !== "radar");
    if (tab === "radar") renderRadar();
  };
});
document.getElementById("ms-rest-toggle").onclick = () => {
  const body = document.getElementById("ms-rest-body");
  body.classList.toggle("hidden");
  document.getElementById("ms-rest-toggle").classList.toggle(
    "open", !body.classList.contains("hidden"));
};

// ---- 战略雷达：Donut 分布 / 活动热力 / 课程时间轴（全部前端渲染现有数据） ----

async function renderRadar() {
  const model = _masteryModel || await (await fetch("/api/learner/model")).json();
  _masteryModel = model;
  const concepts = model.concepts || [];
  renderRadarDonut(concepts);
  renderRadarHeat(concepts);
  renderRadarTimeline(model);
}

function _bandOf(c) {
  return !c.evidence.length ? "none"
    : c.mastery < 0.4 ? "low" : c.mastery < 0.7 ? "mid" : "high";
}

const RADAR_BANDS = [
  ["low", "#e5534b", "薄弱（<0.4）"],
  ["mid", "#e3b341", "爬升（0.4~0.7）"],
  ["high", "#57ab5a", "达标（≥0.7）"],
  ["none", "#8b949e", "无证据"],
];

function renderRadarDonut(concepts) {
  const counts = RADAR_BANDS.map(([cls]) =>
    concepts.filter(c => _bandOf(c) === cls).length);
  const total = concepts.length;
  const withEv = concepts.filter(c => c.evidence.length);
  const avg = withEv.length
    ? withEv.reduce((s, c) => s + c.mastery, 0) / withEv.length : 0;
  const R = 62, CIRC = 2 * Math.PI * R;
  let acc = 0;
  const segs = [];
  RADAR_BANDS.forEach(([cls, color], i) => {
    const len = total ? counts[i] / total * CIRC : 0;
    if (len > 0) {
      segs.push(`<circle cx="80" cy="80" r="${R}" fill="none" stroke="${color}" stroke-width="16" stroke-dasharray="${len.toFixed(1)} ${(CIRC - len).toFixed(1)}" stroke-dashoffset="${(-acc).toFixed(1)}" transform="rotate(-90 80 80)"/>`);
    }
    acc += len;
  });
  document.getElementById("radar-donut").innerHTML =
    `<svg viewBox="0 0 160 160" class="donut">` +
    `<circle cx="80" cy="80" r="${R}" fill="none" stroke="var(--inline-code-bg)" stroke-width="16"/>` +
    segs.join("") +
    `<text x="80" y="74" text-anchor="middle" class="donut-num">${total}</text>` +
    `<text x="80" y="92" text-anchor="middle" class="donut-sub">知识点</text>` +
    `<text x="80" y="110" text-anchor="middle" class="donut-avg">平均 ${withEv.length ? (avg * 100).toFixed(1) + "%" : "—"}</text>` +
    `</svg>`;
  const legend = document.getElementById("radar-legend");
  legend.innerHTML = "";
  RADAR_BANDS.forEach(([cls, color, label], i) => {
    const row = document.createElement("div");
    row.className = "rl-row";
    const dot = document.createElement("span");
    dot.className = "rl-dot";
    dot.style.background = color;
    const lb = document.createElement("span");
    lb.className = "rl-label";
    lb.textContent = label;
    const num = document.createElement("span");
    num.className = "rl-num";
    num.textContent = counts[i];
    row.append(dot, lb, num);
    legend.appendChild(row);
  });
}

function _localIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function renderRadarHeat(concepts) {
  const box = document.getElementById("radar-heat");
  box.innerHTML = "";
  const counts = {};
  for (const c of concepts)
    for (const ev of c.evidence) counts[ev.ts] = (counts[ev.ts] || 0) + 1;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(today);
  start.setDate(start.getDate() - (12 * 7 - 1));
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));  // 对齐周一
  const grid = document.createElement("div");
  grid.className = "heat-grid";
  for (const d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) {
    const iso = _localIso(d);
    const n = counts[iso] || 0;
    const cell = document.createElement("span");
    const lvl = n === 0 ? 0 : n === 1 ? 1 : n === 2 ? 2 : n === 3 ? 3 : 4;
    cell.className = "heat-cell2 lv" + lvl;
    cell.title = `${iso}：${n} 条证据`;
    grid.appendChild(cell);
  }
  box.appendChild(grid);
}

// 课程地图：垂直时间轴（先修链是线性数据，竖排全标题可读，节点可点击跳转）
function renderRadarTimeline(model) {
  const box = document.getElementById("radar-timeline");
  box.innerHTML = "";
  const concepts = model.concepts || [];
  if (!concepts.length) {
    box.textContent = "（暂无知识点）";
    return;
  }
  const curDay = String(model.current_day);
  const byDay = new Map();
  for (const c of concepts) {
    const day = (c.id.match(/^Day(\d+)-/) || [0, "?"])[1];
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(c);
  }
  let currentRow = null;
  for (const [day, items] of [...byDay.entries()].sort((a, b) => a[0] - b[0])) {
    const dh = document.createElement("div");
    dh.className = "tl-day" + (String(day) === curDay ? " current" : "");
    dh.textContent = `Day ${day}`;
    box.appendChild(dh);
    for (const c of items) {
      const band = _bandOf(c);
      const row = document.createElement("button");
      row.className = "tl-row" + (String(day) === curDay ? " current" : "");
      row.dataset.cid = c.id;
      const dot = document.createElement("span");
      dot.className = "tl-dot " + band;
      const main = document.createElement("span");
      main.className = "tl-main";
      const t = document.createElement("span");
      t.className = "tl-title";
      t.textContent = c.title || c.id;
      const cid = document.createElement("span");
      cid.className = "tl-cid";
      cid.textContent = c.id;
      main.append(t, cid);
      const pct = document.createElement("span");
      pct.className = "tl-pct " + band;
      pct.textContent = c.evidence.length ? (c.mastery * 100).toFixed(0) + "%" : "—";
      row.append(dot, main, pct);
      row.onclick = () => {
        document.querySelector(".drawer-tab[data-mtab='tactical']").click();
        openLearner(c.id);
      };
      box.appendChild(row);
      if (String(day) === curDay && !currentRow) currentRow = row;
    }
  }
  if (currentRow) setTimeout(() => currentRow.scrollIntoView({ block: "center" }), 60);
}

// 算法说明弹层
document.getElementById("algo-info-btn").onclick = (e) => {
  e.stopPropagation();
  document.getElementById("algo-pop").classList.toggle("hidden");
};
document.addEventListener("click", (e) => {
  const pop = document.getElementById("algo-pop");
  if (!pop.classList.contains("hidden") && !pop.contains(e.target)
      && e.target.id !== "algo-info-btn" && !document.getElementById("algo-info-btn").contains(e.target)) {
    pop.classList.add("hidden");
  }
});

// ---- 侧栏复习预警 widget（伴随式暴露跨周期紧急项） ----

async function refreshUrgentWidget() {
  const w = document.getElementById("urgent-widget");
  try {
    const model = await (await fetch("/api/learner/model")).json();
    const urgent = (model.concepts || [])
      .filter(c => c.evidence.length && (c.due || c.mastery < 0.4))
      .sort((a, b) => (b.due - a.due) || (a.mastery - b.mastery));
    if (!urgent.length) {
      w.classList.add("hidden");
      return;
    }
    w.classList.remove("hidden");
    document.getElementById("urgent-count").textContent = urgent.length;
    const box = document.getElementById("urgent-items");
    box.innerHTML = "";
    for (const c of urgent.slice(0, 3)) {
      const it = document.createElement("button");
      it.className = "uw-item";
      const t = document.createElement("span");
      t.className = "uw-title";
      t.textContent = c.title || c.id;
      t.title = c.id;
      const m = document.createElement("span");
      m.className = "uw-mastery " + masteryBand(c);
      m.textContent = (c.mastery * 100).toFixed(0) + "%";
      it.append(t, m);
      it.onclick = () => openLearner(c.id);
      box.appendChild(it);
    }
    if (urgent.length > 3) {
      const more = document.createElement("button");
      more.className = "uw-more";
      more.textContent = `还有 ${urgent.length - 3} 项，打开战术板…`;
      more.onclick = () => openLearner();
      box.appendChild(more);
    }
  } catch (e) { /* 预警是增益，失败静默 */ }
}
refreshUrgentWidget();
setInterval(refreshUrgentWidget, 30000);

// ---------- 面试话术库（M4 话术层：卡片视图 + 编辑/删除 + 原文切换） ----------

async function openQa(raw) {
  const box = document.getElementById("doc-content");
  box.textContent = "加载中…";
  docModal.classList.remove("hidden");
  document.getElementById("doc-title").textContent = "面试话术库";
  if (raw) {
    const r = await (await fetch("/api/doc?name=interview_qa")).json();
    box.innerHTML = "";
    box.appendChild(qaToolbar(true));
    const body = document.createElement("div");
    box.appendChild(body);
    renderMarkdownInto(body, r.ok ? r.content : `加载失败：${r.error}`);
    return;
  }
  const r = await (await fetch("/api/qa/entries")).json();
  box.innerHTML = "";
  box.appendChild(qaToolbar(false));
  if (!r.ok) {
    const err = document.createElement("div");
    err.textContent = `加载失败：${r.error || "未知错误"}`;
    box.appendChild(err);
    return;
  }
  if (!r.entries.length) {
    const hint = document.createElement("div");
    hint.className = "qa-empty";
    hint.textContent = "暂无话术条目。产出途径：指令 [同步] 面试话术 XXX；或每日复盘拷打结束后自动反喂沉淀。";
    box.appendChild(hint);
    return;
  }
  for (const e of r.entries) box.appendChild(qaEntry(e));
}

function qaToolbar(isRaw) {
  const bar = document.createElement("div");
  bar.className = "qa-toolbar";
  const card = document.createElement("button");
  card.textContent = "卡片视图";
  card.className = isRaw ? "" : "active";
  card.onclick = () => openQa(false);
  const rawBtn = document.createElement("button");
  rawBtn.textContent = "原文";
  rawBtn.className = isRaw ? "active" : "";
  rawBtn.onclick = () => openQa(true);
  bar.append(card, rawBtn);
  return bar;
}

function qaEntry(e) {
  const card = document.createElement("div");
  card.className = "qa-entry";
  const head = document.createElement("div");
  head.className = "qa-head";
  const title = document.createElement("span");
  title.className = "qa-title";
  title.textContent = e.title;
  head.appendChild(title);
  for (const t of e.tags || []) {
    const tag = document.createElement("span");
    tag.className = "note-chip concept";
    tag.textContent = "#" + t;
    head.appendChild(tag);
  }
  const src = document.createElement("span");
  src.className = "qa-src";
  src.textContent = e.source;
  head.appendChild(src);
  card.appendChild(head);
  if (e.code_ref && e.code_ref !== "待补") {
    const cr = document.createElement("div");
    cr.className = "qa-code";
    cr.textContent = "关联代码：" + e.code_ref;
    card.appendChild(cr);
  }
  const bLabel = document.createElement("div");
  bLabel.className = "qa-label";
  bLabel.textContent = "精简版（30秒）";
  const bBody = document.createElement("div");
  bBody.className = "qa-brief";
  bBody.textContent = e.brief;
  card.append(bLabel, bBody);
  if (e.detail) {
    const det = document.createElement("details");
    const sum = document.createElement("summary");
    sum.textContent = "展开版（2分钟）";
    const body = document.createElement("div");
    body.className = "qa-fold-body";
    body.textContent = e.detail;
    det.append(sum, body);
    card.appendChild(det);
  }
  if ((e.followups || []).length) {
    const det = document.createElement("details");
    const sum = document.createElement("summary");
    sum.textContent = `追问预案（${e.followups.length}）`;
    const body = document.createElement("div");
    body.className = "qa-fold-body";
    for (const [q, a] of e.followups) {
      const qa = document.createElement("div");
      qa.className = "qa-fu";
      const qEl = document.createElement("div");
      qEl.className = "qa-q";
      qEl.textContent = "Q: " + q;
      const aEl = document.createElement("div");
      aEl.className = "qa-a";
      aEl.textContent = "A: " + a;
      qa.append(qEl, aEl);
      body.appendChild(qa);
    }
    det.append(sum, body);
    card.appendChild(det);
  }
  const ops = document.createElement("div");
  ops.className = "note-ops";
  const edit = document.createElement("button");
  edit.textContent = "编辑";
  edit.onclick = () => qaEdit(card, e);
  const del = document.createElement("button");
  del.textContent = "删除";
  del.onclick = async () => {
    if (!confirm(`删除话术「${e.title}」？（不可恢复）`)) return;
    const r = await notesApi("/api/qa/delete", { id: e.id });
    if (!r.ok) { showToast(r.error || "删除失败"); return; }
    openQa(false);
  };
  ops.append(edit, del);
  card.appendChild(ops);
  return card;
}

function qaEdit(card, e) {
  card.innerHTML = "";
  const mk = (labelText, value, rows) => {
    const label = document.createElement("div");
    label.className = "qa-label";
    label.textContent = labelText;
    const ta = document.createElement("textarea");
    ta.rows = rows || 2;
    ta.value = value || "";
    card.append(label, ta);
    return ta;
  };
  const titleTa = mk("标题", e.title, 1);
  const briefTa = mk("精简版（30秒）", e.brief, 3);
  const detailTa = mk("展开版（2分钟）", e.detail, 5);
  const fuText = (e.followups || []).map(([q, a]) => `Q: ${q}\nA: ${a}`).join("\n");
  const fuTa = mk("追问预案（每条两行：Q: / A:）", fuText, 6);
  const row = document.createElement("div");
  row.className = "note-edit-row";
  const save = document.createElement("button");
  save.textContent = "保存";
  save.className = "primary";
  const cancel = document.createElement("button");
  cancel.textContent = "取消";
  row.append(save, cancel);
  card.appendChild(row);
  save.onclick = async () => {
    const followups = [];
    const lines = fuTa.value.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const qm = lines[i].match(/^Q[:：]\s*(.*)$/);
      if (!qm) continue;
      const am = (lines[i + 1] || "").match(/^A[:：]\s*(.*)$/);
      followups.push([qm[1], am ? am[1] : ""]);
      if (am) i++;
    }
    const r = await notesApi("/api/qa/update", {
      id: e.id, title: titleTa.value.trim(), brief: briefTa.value,
      detail: detailTa.value, followups,
    });
    if (!r.ok) { showToast(r.error || "保存失败"); return; }
    showToast("已保存");
    openQa(false);
  };
  cancel.onclick = () => openQa(false);
}

// ---------- 笔记页 v2（M4 条目层：书架三栏 + Markdown 编辑器） ----------

const notesPage = document.getElementById("notes-page");
const NOTE_KINDS = { stuck: "卡壳", question: "疑问", mastered: "已掌握", insight: "心得" };
const notesState = {
  shelf: "all", kind: "", search: "",
  notes: [], concepts: [], selectedId: null,
  dirty: false, mergeMode: false,
};

document.getElementById("open-notes").onclick = openNotes;
document.getElementById("notes-close").onclick = closeNotes;

async function notesApi(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

async function openNotes() {
  notesPage.classList.remove("hidden");
  await reloadNotes();
}

function closeNotes() {
  if (notesState.dirty && !confirm("有未保存的修改，确定关闭？")) return;
  notesState.dirty = false;
  notesPage.classList.add("hidden");
}

async function reloadNotes() {
  const [notesRes, model] = await Promise.all([
    (await fetch("/api/notes")).json(),
    (await fetch("/api/learner/model")).json(),
  ]);
  notesState.notes = notesRes.notes || [];
  notesState.concepts = model.concepts || [];
  renderShelf();
  renderNotesList();
  renderEditor();
}

// ---- 书架（左栏） ----

function noteMatchesShelf(n, shelf) {
  if (shelf === "all") return true;
  if (shelf === "open") return n.status !== "resolved";
  if (shelf === "resolved") return n.status === "resolved";
  if (shelf === "triage") return !!n.needs_review || !n.concept_id;
  if (shelf.startsWith("concept:")) return n.concept_id === shelf.slice(8);
  return true;
}

function filteredNotes() {
  const q = notesState.search.toLowerCase();
  return notesState.notes.filter(n =>
    noteMatchesShelf(n, notesState.shelf) &&
    (!notesState.kind || n.kind === notesState.kind) &&
    (!q || n.text.toLowerCase().includes(q)));
}

function renderShelf() {
  const notes = notesState.notes;
  const count = (pred) => notes.filter(pred).length;
  document.getElementById("cnt-all").textContent = notes.length;
  document.getElementById("cnt-open").textContent = count(n => n.status !== "resolved");
  document.getElementById("cnt-resolved").textContent = count(n => n.status === "resolved");
  document.getElementById("cnt-triage").textContent = count(n => n.needs_review || !n.concept_id);
  document.querySelectorAll("#notes-shelf > .shelf-group > .shelf-item").forEach(b =>
    b.classList.toggle("active", b.dataset.shelf === notesState.shelf));
  // 知识点书架：有笔记挂接的 concept 成"书"
  const box = document.getElementById("shelf-concepts");
  box.innerHTML = "";
  const used = new Set(notes.map(n => n.concept_id).filter(Boolean));
  const concepts = notesState.concepts.filter(c => used.has(c.id));
  if (!concepts.length) {
    const empty = document.createElement("div");
    empty.className = "shelf-empty";
    empty.textContent = "（挂接知识点后在此成架）";
    box.appendChild(empty);
  }
  for (const c of concepts) {
    const b = document.createElement("button");
    b.className = "shelf-item" + (notesState.shelf === "concept:" + c.id ? " active" : "");
    b.dataset.shelf = "concept:" + c.id;
    const t = document.createElement("span");
    t.className = "shelf-title";
    t.textContent = `${c.id} ${c.title}`;
    t.title = `${c.id} ${c.title}`;
    const cnt = document.createElement("span");
    cnt.className = "shelf-count";
    cnt.textContent = count(n => n.concept_id === c.id);
    b.append(t, cnt);
    b.onclick = () => { notesState.shelf = b.dataset.shelf; renderShelf(); renderNotesList(); };
    box.appendChild(b);
  }
  document.querySelectorAll("#shelf-kinds .kind-chip").forEach(b =>
    b.classList.toggle("active", b.dataset.kind === notesState.kind));
}

document.querySelectorAll("#notes-shelf > .shelf-group > .shelf-item[data-shelf]").forEach(b => {
  b.onclick = () => { notesState.shelf = b.dataset.shelf; renderShelf(); renderNotesList(); };
});
document.querySelectorAll("#shelf-kinds .kind-chip").forEach(b => {
  b.onclick = () => {
    notesState.kind = notesState.kind === b.dataset.kind ? "" : b.dataset.kind;
    renderShelf();
    renderNotesList();
  };
});
document.getElementById("notes-search").oninput = (e) => {
  notesState.search = e.target.value.trim();
  renderNotesList();
};

// ---- 列表（中栏） ----

function noteTitle(text) {
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    return t.replace(/^#+\s*/, "").slice(0, 40);
  }
  return "（空白笔记）";
}

function noteExcerpt(text) {
  const plain = text.replace(/[#*>`\-\[\]|]/g, "").replace(/\s+/g, " ").trim();
  return plain.length > 80 ? plain.slice(0, 80) + "…" : plain;
}

function renderNotesList() {
  const list = document.getElementById("notes-list");
  list.innerHTML = "";
  const notes = filteredNotes();
  if (!notes.length) {
    const empty = document.createElement("div");
    empty.className = "notes-empty-hint";
    empty.textContent = "（此书架暂无笔记——[同步] 卡壳/疑问会自动进条目层，也可「＋ 新建笔记」或「⇩ 从日志蒸馏」）";
    list.appendChild(empty);
    return;
  }
  for (const n of notes) list.appendChild(noteCard(n));
}

function noteCard(n) {
  const card = document.createElement("div");
  card.className = "note-card"
    + (n.id === notesState.selectedId ? " active" : "")
    + (n.status === "resolved" ? " resolved" : "");
  const head = document.createElement("div");
  head.className = "nc-head";
  const kind = document.createElement("span");
  kind.className = "note-chip kind-" + n.kind;
  kind.textContent = NOTE_KINDS[n.kind] || n.kind;
  head.appendChild(kind);
  if (n.needs_review || !n.concept_id) {
    const w = document.createElement("span");
    w.className = "note-chip warn";
    w.textContent = "⚠";
    w.title = "待整理：挂接知识点后，销账才能写证据";
    head.appendChild(w);
  }
  if (n.status === "resolved") {
    const s = document.createElement("span");
    s.className = "note-chip done";
    s.textContent = "✓";
    head.appendChild(s);
  }
  if (notesState.mergeMode) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "note-merge-cb";
    cb.dataset.nid = n.id;
    head.appendChild(cb);
  }
  const title = document.createElement("div");
  title.className = "nc-title";
  title.textContent = noteTitle(n.text);
  const excerpt = document.createElement("div");
  excerpt.className = "nc-excerpt";
  excerpt.textContent = noteExcerpt(n.text);
  const meta = document.createElement("div");
  meta.className = "nc-meta";
  const bits = [];
  if (n.concept_id) bits.push(n.concept_id);
  if (n.created_day) bits.push(`Day ${n.created_day}`);
  meta.textContent = bits.join(" · ");
  card.append(head, title, excerpt, meta);
  card.onclick = () => {
    if (notesState.mergeMode) return;
    selectNote(n.id);
  };
  return card;
}

function currentNote() {
  return notesState.notes.find(n => n.id === notesState.selectedId) || null;
}

function selectNote(id) {
  if (notesState.dirty && notesState.selectedId && id !== notesState.selectedId) {
    if (!confirm("当前笔记有未保存修改，切换将丢弃，继续？")) return;
  }
  notesState.dirty = false;
  notesState.selectedId = id;
  renderNotesList();
  renderEditor();
}

// ---- 编辑器（右栏） ----

function renderEditor() {
  const empty = document.getElementById("notes-empty");
  const ed = document.getElementById("notes-editor");
  const n = currentNote();
  if (!n) {
    empty.classList.remove("hidden");
    ed.classList.add("hidden");
    return;
  }
  empty.classList.add("hidden");
  ed.classList.remove("hidden");
  const ta = document.getElementById("ne-text");
  ta.value = n.text;
  notesState.dirty = false;
  updateDirty();
  refreshPreview();
  const bits = [NOTE_KINDS[n.kind] || n.kind];
  bits.push(n.concept_id ? `挂接：${n.concept_id}` : "未挂接知识点");
  bits.push(n.status === "resolved" ? "已解决" : "未解决");
  if (n.created_day) bits.push(`Day ${n.created_day}`);
  document.getElementById("ne-meta").textContent = bits.join(" · ");
  document.getElementById("ne-resolve").style.display =
    n.status === "resolved" ? "none" : "";
}

let _previewTimer = null;
function refreshPreview() {
  const ta = document.getElementById("ne-text");
  renderMarkdownInto(document.getElementById("ne-preview"),
                     ta.value || "（无内容）", true);
}
document.getElementById("ne-text").addEventListener("input", () => {
  notesState.dirty = true;
  updateDirty();
  clearTimeout(_previewTimer);
  _previewTimer = setTimeout(refreshPreview, 200);
});
function updateDirty() {
  document.getElementById("ne-dirty").classList.toggle("hidden", !notesState.dirty);
}

document.querySelectorAll("#ne-view-switch button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#ne-view-switch button").forEach(x =>
      x.classList.toggle("active", x === b));
    document.getElementById("ne-body").dataset.view = b.dataset.view;
    if (b.dataset.view !== "edit") refreshPreview();
  };
});

// ---- Markdown 工具条 ----

function mdApply(fn) {
  const ta = document.getElementById("ne-text");
  fn(ta);
  ta.dispatchEvent(new Event("input"));
  ta.focus();
}

function mdWrap(ta, before, after, placeholder) {
  const s = ta.selectionStart, e = ta.selectionEnd;
  const sel = ta.value.slice(s, e) || placeholder;
  ta.setRangeText(before + sel + after, s, e, "end");
  ta.setSelectionRange(s + before.length, s + before.length + sel.length);
}

function mdLinePrefix(ta, prefix) {
  const s = ta.selectionStart, e = ta.selectionEnd;
  const start = ta.value.lastIndexOf("\n", s - 1) + 1;
  const lines = ta.value.slice(start, e).split("\n");
  const replaced = lines.map(l => l.trim() ? prefix + l : l).join("\n");
  ta.setRangeText(replaced, start, e, "end");
}

function mdInsert(ta, text, selectOffset = 0, selectLen = 0) {
  const s = ta.selectionStart;
  ta.setRangeText(text, s, ta.selectionEnd, "end");
  if (selectLen) ta.setSelectionRange(s + selectOffset, s + selectOffset + selectLen);
}

const MD_SNIPPETS = {
  codeblock: "\n```\n代码…\n```\n",
  link: "[链接文字](https://)",
  table: "\n| 列1 | 列2 | 列3 |\n|-----|-----|-----|\n|     |     |     |\n",
  hr: "\n\n---\n\n",
  mermaid: "\n```mermaid\nflowchart LR\n  A[开始] --> B[处理] --> C[结束]\n```\n",
};

document.querySelectorAll("#ne-toolbar button[data-md]").forEach(b => {
  b.onclick = () => {
    const act = b.dataset.md;
    mdApply(ta => {
      if (act === "h1") mdLinePrefix(ta, "# ");
      else if (act === "h2") mdLinePrefix(ta, "## ");
      else if (act === "h3") mdLinePrefix(ta, "### ");
      else if (act === "bold") mdWrap(ta, "**", "**", "加粗文字");
      else if (act === "italic") mdWrap(ta, "*", "*", "斜体文字");
      else if (act === "strike") mdWrap(ta, "~~", "~~", "删除线");
      else if (act === "code") mdWrap(ta, "`", "`", "代码");
      else if (act === "quote") mdLinePrefix(ta, "> ");
      else if (act === "ul") mdLinePrefix(ta, "- ");
      else if (act === "ol") mdLinePrefix(ta, "1. ");
      else if (act === "task") mdLinePrefix(ta, "- [ ] ");
      else if (act === "codeblock") mdInsert(ta, MD_SNIPPETS.codeblock, 5, 3);
      else if (act === "link") mdInsert(ta, MD_SNIPPETS.link, 1, 4);
      else if (act === "table") mdInsert(ta, MD_SNIPPETS.table);
      else if (act === "hr") mdInsert(ta, MD_SNIPPETS.hr);
      else if (act === "mermaid") mdInsert(ta, MD_SNIPPETS.mermaid);
    });
  };
});

// ---- 编辑器动作 ----

document.getElementById("ne-save").onclick = async () => {
  const n = currentNote();
  if (!n) return;
  const r = await notesApi("/api/notes/update", {
    id: n.id, text: document.getElementById("ne-text").value,
  });
  if (!r.ok) { showToast(r.error || "保存失败"); return; }
  n.text = r.note.text;
  notesState.dirty = false;
  updateDirty();
  showToast("已保存");
  renderNotesList();
};

document.getElementById("ne-resolve").onclick = async () => {
  const n = currentNote();
  if (!n) return;
  const tip = n.concept_id
    ? "标记为解决？（将沉淀 note_distilled 证据到掌握度模型）"
    : "标记为解决？（未挂接知识点，不写证据）";
  if (!confirm(tip)) return;
  const r = await notesApi("/api/notes/resolve", { id: n.id });
  if (!r.ok) { showToast(r.error || "操作失败"); return; }
  showToast(r.evidence ? "已销账并沉淀证据（+0.05）" : "已标记解决");
  await reloadNotes();
};

document.getElementById("ne-delete").onclick = async () => {
  const n = currentNote();
  if (!n || !confirm("删除这条笔记？（不可恢复）")) return;
  await notesApi("/api/notes/delete", { id: n.id });
  notesState.selectedId = null;
  await reloadNotes();
};

// ---- 挂接 / 新建 选择器浮层 ----

function closeAttachPicker() {
  document.getElementById("attach-picker")?.remove();
}

function pickerOverlay(titleText) {
  closeAttachPicker();
  const ov = document.createElement("div");
  ov.id = "attach-picker";
  const box = document.createElement("div");
  box.className = "attach-box";
  const h = document.createElement("div");
  h.className = "attach-title";
  h.textContent = titleText;
  box.appendChild(h);
  ov.appendChild(box);
  ov.onclick = (e) => { if (e.target === ov) closeAttachPicker(); };
  return { ov, box };
}

function pickerRow(box) {
  const row = document.createElement("div");
  row.className = "note-edit-row";
  const ok = document.createElement("button");
  ok.textContent = "确定";
  ok.className = "primary";
  const cancel = document.createElement("button");
  cancel.textContent = "取消";
  cancel.onclick = closeAttachPicker;
  row.append(ok, cancel);
  box.appendChild(row);
  return ok;
}

document.getElementById("ne-attach").onclick = () => {
  const n = currentNote();
  if (!n) return;
  if (!notesState.concepts.length) {
    showToast("暂无知识点（先开始学习或完成迁移）");
    return;
  }
  const { ov, box } = pickerOverlay("挂接到知识点：");
  const sel = document.createElement("select");
  for (const c of notesState.concepts) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.id} ${c.title}`;
    sel.appendChild(opt);
  }
  if (n.concept_id) sel.value = n.concept_id;
  box.appendChild(sel);
  const ok = pickerRow(box);
  document.body.appendChild(ov);
  ok.onclick = async () => {
    const r = await notesApi("/api/notes/update", { id: n.id, concept_id: sel.value });
    closeAttachPicker();
    if (!r.ok) { showToast(r.error || "挂接失败"); return; }
    showToast(`已挂接 ${sel.value}`);
    await reloadNotes();
  };
};

document.getElementById("notes-add-btn").onclick = () => {
  const { ov, box } = pickerOverlay("新建笔记");
  const l1 = document.createElement("div");
  l1.className = "qa-label";
  l1.textContent = "类型";
  const kindSel = document.createElement("select");
  for (const [v, label] of Object.entries(NOTE_KINDS)) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = label;
    kindSel.appendChild(opt);
  }
  kindSel.value = "insight";
  const l2 = document.createElement("div");
  l2.className = "qa-label";
  l2.textContent = "挂接书架（知识点，可后补）";
  const conceptSel = document.createElement("select");
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "（暂不挂接）";
  conceptSel.appendChild(none);
  for (const c of notesState.concepts) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.id} ${c.title}`;
    conceptSel.appendChild(opt);
  }
  if (notesState.shelf.startsWith("concept:")) {
    conceptSel.value = notesState.shelf.slice(8);
  }
  box.append(l1, kindSel, l2, conceptSel);
  const ok = pickerRow(box);
  ok.textContent = "创建并编辑";
  document.body.appendChild(ov);
  ok.onclick = async () => {
    const r = await notesApi("/api/notes/add", {
      kind: kindSel.value, text: "# 新笔记\n\n",
      concept_id: conceptSel.value,
    });
    closeAttachPicker();
    if (!r.ok) { showToast(r.error || "创建失败"); return; }
    notesState.selectedId = r.note.id;
    await reloadNotes();
    document.getElementById("ne-text").focus();
  };
};

// ---- 顶栏动作 ----

document.getElementById("notes-distill-btn").onclick = async () => {
  const r = await notesApi("/api/notes/distill", {});
  showToast(r.ok ? `日志蒸馏完成：新增 ${r.added} 条` : (r.error || "蒸馏失败"));
  await reloadNotes();
};

document.getElementById("notes-merge-btn").onclick = async () => {
  const btn = document.getElementById("notes-merge-btn");
  if (!notesState.mergeMode) {
    notesState.mergeMode = true;
    btn.classList.add("active");
    renderNotesList();
    return;
  }
  const cbs = [...document.querySelectorAll(".note-merge-cb:checked")];
  notesState.mergeMode = false;
  btn.classList.remove("active");
  if (cbs.length < 2) { renderNotesList(); return; }
  const ids = cbs.map(cb => cb.dataset.nid);
  if (!confirm(`合并 ${ids.length} 条笔记？文本并入最早勾选的那条，其余标记为已合并。`)) {
    renderNotesList();
    return;
  }
  const r = await notesApi("/api/notes/merge", { keep: ids[0], others: ids.slice(1) });
  if (!r.ok) { showToast(r.error || "合并失败"); return; }
  showToast("已合并");
  await reloadNotes();
};

// ---------- 启动 ----------

(async () => {
  try {
    const a = await (await fetch("/api/auth/status")).json();
    if (a.gate && !a.authed) await ensureLogin();
  } catch (e) { /* 服务未就绪时静默 */ }
})();
refreshState();
refreshLlmStatus();
loadCommands();
loadHistory();
loadWorkspaces();
setInterval(refreshState, 10000);
setInterval(refreshLlmStatus, 15000);

// ---------- M6 实战工坊：新建 demo 弹窗 ----------

const demoModal = document.getElementById("demo-modal");
document.getElementById("demo-new").onclick = async () => {
  const res = await fetch("/api/demo/scaffolds");
  const r = await res.json();
  const sel = document.getElementById("demo-type");
  sel.innerHTML = "";
  for (const s of r.scaffolds || []) {
    const opt = document.createElement("option");
    opt.value = s.type;
    opt.textContent = s.description ? `${s.type} — ${s.description}` : s.type;
    sel.appendChild(opt);
  }
  const msg = document.getElementById("demo-msg");
  msg.textContent = "";
  msg.className = "";
  demoModal.classList.remove("hidden");
};
document.getElementById("demo-close").onclick = () => demoModal.classList.add("hidden");
demoModal.addEventListener("click", (e) => {
  if (e.target === demoModal) demoModal.classList.add("hidden");
});
document.getElementById("demo-create").onclick = async () => {
  const type = document.getElementById("demo-type").value;
  const name = document.getElementById("demo-name").value.trim();
  const msg = document.getElementById("demo-msg");
  if (!name) { msg.textContent = "请填写 demo 名称"; msg.className = "error"; return; }
  msg.textContent = "创建中…";
  msg.className = "";
  const res = await fetch("/api/demo/scaffold", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, name }),
  });
  const r = await res.json();
  if (!r.ok) { msg.textContent = r.error || "创建失败"; msg.className = "error"; return; }
  msg.textContent = `已创建 ${r.path}（${r.files} 个文件）`;
  msg.className = "ok";
  codeState.root = r.code_root || "demo";
  await loadCodeRoots(true);  // demo 代码根已自动注册，刷新并选中
  toast(`demo 已创建：${r.path}（可选中文件编辑，或让 AI 构建/启动）`);
  setTimeout(() => demoModal.classList.add("hidden"), 900);
};

// ---------- M6 实战工坊：进程面板 ----------

const procDrawer = document.getElementById("proc-drawer");
let procTimer = null;
let procLogSource = null;

function stopProcWatch() {
  if (procTimer) { clearInterval(procTimer); procTimer = null; }
  if (procLogSource) { procLogSource.close(); procLogSource = null; }
}

document.getElementById("proc-toggle").onclick = () => {
  const opening = procDrawer.classList.contains("hidden");
  procDrawer.classList.toggle("hidden");
  if (opening) {
    refreshProcesses();
    procTimer = setInterval(refreshProcesses, 5000);
  } else {
    stopProcWatch();
  }
};
document.getElementById("proc-close").onclick = () => {
  procDrawer.classList.add("hidden");
  stopProcWatch();
};
document.getElementById("proc-refresh").onclick = refreshProcesses;

async function refreshProcesses() {
  const res = await fetch("/api/processes");
  const r = await res.json();
  const sel = document.getElementById("proc-cwd");
  if (!sel.options.length && r.allowed_cwds) {
    for (const [label, path] of Object.entries(r.allowed_cwds)) {
      const opt = document.createElement("option");
      opt.value = path;
      opt.textContent = label;
      opt.title = path;
      sel.appendChild(opt);
    }
  }
  const list = document.getElementById("proc-list");
  const items = r.processes || [];
  const running = items.filter(p => p.status === "running").length;
  document.getElementById("proc-status").textContent =
    items.length ? `${running} 运行 / 共 ${items.length}` : "";
  list.innerHTML = "";
  if (!items.length) {
    const d = document.createElement("div");
    d.className = "proc-empty";
    d.textContent = "暂无登记进程。上方输入命令启动，或让 AI 经 process_start 启动。";
    list.appendChild(d);
    return;
  }
  for (const p of items) {
    const row = document.createElement("div");
    row.className = "proc-row";
    const nameEl = document.createElement("span");
    nameEl.className = "p-name";
    nameEl.textContent = p.name;
    nameEl.title = p.name;
    const statusEl = document.createElement("span");
    statusEl.className = `p-status ${p.status}`;
    statusEl.textContent = p.status === "running" ? "运行中" : "已停止";
    const cmdEl = document.createElement("span");
    cmdEl.className = "p-cmd";
    cmdEl.textContent = (p.cmd || []).join(" ");
    cmdEl.title = cmdEl.textContent;
    row.appendChild(nameEl);
    row.appendChild(statusEl);
    row.appendChild(cmdEl);
    for (const pt of p.ports || []) {
      const a = document.createElement("a");
      a.className = "p-port";
      a.href = `http://127.0.0.1:${pt}`;
      a.target = "_blank";
      a.title = "打开看效果";
      a.textContent = `:${pt}`;
      row.appendChild(a);
    }
    const logBtn = document.createElement("button");
    logBtn.textContent = "日志";
    logBtn.onclick = () => tailProcLog(p.id, p.name);
    row.appendChild(logBtn);
    if (p.status === "running") {
      const stopBtn = document.createElement("button");
      stopBtn.textContent = "停止";
      stopBtn.onclick = async () => {
        await fetch("/api/processes/stop", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: p.id }),
        });
        refreshProcesses();
      };
      row.appendChild(stopBtn);
    }
    list.appendChild(row);
  }
}

document.getElementById("proc-start-btn").onclick = async () => {
  const cwd = document.getElementById("proc-cwd").value;
  const cmd = document.getElementById("proc-cmd").value.trim();
  if (!cmd) return;
  const res = await fetch("/api/processes/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cwd, cmd }),
  });
  const r = await res.json();
  if (!r.ok) { toast(r.error || "启动失败"); return; }
  document.getElementById("proc-cmd").value = "";
  toast(`进程已启动（${r.id}）${r.ports && r.ports.length ? "，端口 " + r.ports.join("/") : ""}`);
  refreshProcesses();
  tailProcLog(r.id, r.name);
};

function tailProcLog(id, name) {
  if (procLogSource) procLogSource.close();
  const el = document.getElementById("proc-log");
  el.classList.remove("hidden");
  el.textContent = `# ${name} (${id}) 日志 tail\n`;
  const es = new EventSource(`/api/processes/logs/stream?id=${encodeURIComponent(id)}`);
  procLogSource = es;
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.type === "log") {
      el.textContent += d.line + "\n";
      el.scrollTop = el.scrollHeight;
    } else {
      el.textContent += `# ${d.reason || d.content || "流结束"}\n`;
      es.close();
      procLogSource = null;
    }
  };
  es.onerror = () => { es.close(); procLogSource = null; };
}
