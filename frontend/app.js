// ---------- app.js — 核心 SSE / 消息 / 状态 / 侧边栏 / 资料弹窗 / 认证 ----------
// 改进5：功能域拆分后保留的核心模块（~1550 行）
// 已拆分到独立文件：markdown.js / code-browser.js / llm-config.js /
//   workspace-mgr.js / mastery.js / notes-page.js / process-mgr.js

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const form = document.getElementById("input-form");
const scrollBtn = document.getElementById("scroll-bottom");

// ---------- 消息气泡 ----------

// 片段提问消息 → 紧凑卡片（模型仍收到完整代码，仅显示折叠）
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

// AI 读文件 tool-use 指示 chip
function addToolReadChip(p) {
  const div = document.createElement("div");
  div.className = "msg tool";
  const chip = document.createElement("span");
  chip.className = "tool-chip" + (p.ok ? "" : " fail");
  if (p.kind === "doc") {
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
    chip.classList.add("code-ref");
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

// 流式期间的 markdown 渲染节流
let renderTimer = null;
function throttledRender(bubble, text) {
  bubble._pendingText = text;
  if (renderTimer) return;
  renderTimer = setTimeout(() => {
    renderTimer = null;
    renderMarkdownInto(bubble, bubble._pendingText, false);
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
      `${_stageLabel(sess.day_phase)} · 单元${sess.current_unit_id || "-"} · ${_stageLabel(sess.current_stage)}`;
  } catch (e) { /* 服务未就绪时静默 */ }
}

const STAGE_LABELS = {
  not_started: "未开始", planning: "规划中", studying: "学习中",
  teaching: "讲解中", quiz_r1: "考核中", quiz_r2: "考核中",
  scored: "待确认", completed: "已完成", reviewing: "复盘中",
  interviewing: "面试中", prereq_diagnosing: "诊断中", ended: "已结束",
};
const _stageLabel = (v) => STAGE_LABELS[v] || v || "-";

// 指令静态说明
const CMD_DESC = {
  "开始今日学习": "生成今日计划并开始导学",
  "恢复学习": "从中断单元恢复进度",
  "下一内容": "掌握检查确认后推进",
  "强制下一内容": "跳过检查直接推进",
  "超前学习": "预学明日首个单元",
  "同步": "汇报掌握/卡壳/疑问",
  "开始写代码": "进入复现编码模式",
  "验证代码": "校验复现代码",
  "模拟面试": "连环追问演练",
  "先修诊断": "诊断先修知识缺口",
  "开始今日复盘": "自测+拷问+评分",
  "结束今日学习": "收尾汇总写记忆",
  "跳转天数": "跳到指定 Day（如 Day 5）",
};

let COMMANDS = [];
let SLASH_COMMANDS = [];
async function loadCommands() {
  const res = await fetch("/api/commands");
  COMMANDS = await res.json();
  try {
    SLASH_COMMANDS = await (await fetch("/api/slash/commands")).json();
  } catch (e) { SLASH_COMMANDS = []; }
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

// ---------- 「[」指令补全菜单 ----------

const cmdMenu = document.getElementById("cmd-menu");
let cmdMenuOpen = false;

function closeCmdMenu() {
  cmdMenu.classList.add("hidden");
  cmdMenuOpen = false;
}

function _cmdMenuHeader(text) {
  const h = document.createElement("div");
  h.className = "cmd-group";
  h.textContent = text;
  cmdMenu.appendChild(h);
}

function _cmdMenuItem(name, desc, fill) {
  const item = document.createElement("button");
  item.type = "button";
  const n = document.createElement("span");
  n.className = "cmd-name";
  n.textContent = name;
  item.appendChild(n);
  if (desc) {
    const d = document.createElement("span");
    d.className = "cmd-desc";
    d.textContent = desc;
    item.appendChild(d);
  }
  item.onclick = () => {
    inputEl.value = fill;
    closeCmdMenu();
    autosizeInput();
    inputEl.focus();
  };
  cmdMenu.appendChild(item);
}

function updateCmdMenu() {
  const sm = inputEl.value.match(/^\/([a-z]*)$/i);
  if (sm) {
    const kw = sm[1].toLowerCase();
    const hits = SLASH_COMMANDS.filter(c => !kw || c.name.startsWith(kw));
    if (!hits.length) { closeCmdMenu(); return; }
    cmdMenu.innerHTML = "";
    _cmdMenuHeader("系统指令");
    for (const c of hits) _cmdMenuItem(`/${c.name}`, c.desc, `/${c.name}`);
    cmdMenu.classList.remove("hidden");
    cmdMenuOpen = true;
    return;
  }
  const m = inputEl.value.match(/^\[([^\]\n]*)$/);
  if (!m) { closeCmdMenu(); return; }
  const kw = m[1];
  const hits = COMMANDS.filter(c => !kw || c.trigger.includes(kw));
  if (!hits.length) { closeCmdMenu(); return; }
  cmdMenu.innerHTML = "";
  _cmdMenuHeader("学习指令");
  for (const c of hits) {
    _cmdMenuItem(`[${c.trigger}]`, CMD_DESC[c.trigger], `[${c.trigger}]`);
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

// ---------- SSE 收发（铁律 8 核心） ----------

let streaming = false;

function setSendEnabled(on) {
  const btn = document.querySelector("#input-form button[type='submit']");
  if (btn) btn.disabled = !on;
  document.getElementById("command-chips").style.pointerEvents = on ? "" : "none";
  for (const id of ["mode-tutor", "mode-pair", "reset-history"]) {
    const el = document.getElementById(id);
    if (el) el.disabled = !on;
  }
  // 流式期间禁用搜索 / 附件按钮
  for (const id of ["btn-web-search", "btn-file-upload"]) {
    const el = document.getElementById(id);
    if (el) el.disabled = !on;
  }
}

async function streamPost(url, text) {
  if (streaming) { showToast("上一条回复生成中，请稍候…"); return; }
  streaming = true;
  setSendEnabled(false);
  let bubble = null;
  let timer = null;
  try {
    addUserMessage(text);
    bubble = addMessage("assistant", "思考中…");
    bubble.classList.add("thinking");
    const started = Date.now();
    timer = setInterval(() => {
      if (bubble.classList.contains("thinking")) {
        bubble.textContent = `思考中… ${Math.floor((Date.now() - started) / 1000)}s（长提示词首包较慢，请稍候）`;
      }
    }, 1000);
    let rawText = "";
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
        } else if (payload.type === "clear") {
          clearInterval(timer);
          cancelThrottledRender();
          document.getElementById("messages").innerHTML = "";
          rawText = "";
          bubble = addMessage("assistant", "");
        } else if (payload.type === "message") {
          clearInterval(timer);
          cancelThrottledRender();
          const wasThinking = bubble.classList.contains("thinking");
          bubble.classList.remove("thinking");
          if (rawText) renderMarkdownInto(bubble, rawText);
          if ((rawText || bubble.textContent) && !wasThinking) bubble = addMessage("assistant", "");
          renderMarkdownInto(bubble, payload.content);
          rawText = "";
          bubble = addMessage("assistant", "思考中…");
          bubble.classList.add("thinking");
        } else if (payload.type === "tool_read") {
          cancelThrottledRender();
          const wasThinking = bubble.classList.contains("thinking");
          bubble.classList.remove("thinking");
          if (wasThinking && !rawText) {
            bubble.parentElement.remove();
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
        } else if (payload.type === "teaching_suggestion") {
          renderTeachingSuggestion(messagesEl, payload);
        } else if (payload.type === "done") {
          cancelThrottledRender();
          if (rawText && bubble.classList.contains("md")) {
            renderMarkdownInto(bubble, rawText);
          }
          refreshCtxStatus();
        }
        scrollToBottom();
      }
    }
    if (!rawText && (!bubble.textContent || bubble.classList.contains("thinking"))) {
      bubble.parentElement.remove();
    }
  } catch (err) {
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

const SLASH_LOCAL = { usage: () => openUsage() };

form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (streaming) { showToast("上一条回复生成中，请稍候…"); return; }
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  autosizeInput();
  closeCmdMenu();
  const cm = text.match(/^\/([a-z]+)$/i);
  if (cm) {
    const cmd = SLASH_COMMANDS.find(c => c.client && c.name === cm[1].toLowerCase());
    if (cmd && SLASH_LOCAL[cmd.name]) { SLASH_LOCAL[cmd.name](); return; }
  }
  const isSlash = /^\/\S/.test(text);
  const isCommand = !isSlash && (/^\[.+\]/.test(text) ||
    ["重新开始今日学习", "重新开始", "恢复学习"].includes(text));
  streamPost(isSlash ? "/api/slash" : (isCommand ? "/api/command" : "/api/chat"), text);
});

// 多行输入 + 补全菜单键盘导航
inputEl.addEventListener("keydown", (e) => {
  if (cmdMenuOpen && !e.isComposing) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const items = [...cmdMenu.querySelectorAll("button")];
      if (!items.length) return;
      const cur = items.findIndex(b => b.classList.contains("active"));
      const next = e.key === "ArrowDown"
        ? (cur + 1) % items.length
        : (cur <= 0 ? items.length - 1 : cur - 1);
      items.forEach((b, i) => b.classList.toggle("active", i === next));
      items[next].scrollIntoView({ block: "nearest" });
      return;
    }
    if (e.key === "Escape") {
      closeCmdMenu();
      inputEl.setSelectionRange(inputEl.value.length, inputEl.value.length);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const pick = cmdMenu.querySelector("button.active") ||
                   cmdMenu.querySelector("button");
      if (pick) { pick.onclick(); return; }
      closeCmdMenu();
      form.requestSubmit();
      return;
    }
  }
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
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
  const collapsed = sb.classList.contains("collapsed");
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  document.getElementById("toggle-sidebar").textContent = collapsed ? "⇥" : "⇤";
  document.getElementById("expand-sidebar").classList.toggle("hidden", !collapsed);
};
document.getElementById("expand-sidebar").onclick = () => {
  document.getElementById("sidebar").classList.remove("collapsed");
  document.body.classList.remove("sidebar-collapsed");
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
  if (name === "interview_qa") { openQa(false); return; }
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

async function openMaterialPreview(id, section, line) {
  const box = document.getElementById("doc-content");
  box.textContent = "加载中…";
  let url = `/api/materials/preview?id=${encodeURIComponent(id)}`;
  if (section) url += `&section=${encodeURIComponent(section)}`;
  if (line) url += `&line=${line}`;
  const res = await fetch(url);
  const r = await res.json();
  box.innerHTML = "";
  const back = document.createElement("button");
  back.className = "mat-back";
  back.textContent = section ? "← 返回章节目录" : "← 返回资料列表";
  back.onclick = () => { if (section) openMaterialPreview(id); else openMaterials(); };
  box.appendChild(back);
  const body = document.createElement("div");
  body.className = "markdown-body";
  box.appendChild(body);
  document.getElementById("doc-title").textContent = r.title || "资料预览";
  const md = r.ok ? r.content.replace(/(共 \d+ 章)：/g, "$1") : `加载失败：${r.error}`;
  renderMarkdownInto(body, md);
  if (!section && r.ok) {
    for (const li of body.querySelectorAll("li")) {
      const m = li.textContent.match(/^(.*)（第 (\d+) 行）\s*$/);
      if (!m) continue;
      li.classList.add("mat-chapter");
      li.title = "点击阅读该章节";
      li.onclick = () => openMaterialPreview(id, m[1].trim(), parseInt(m[2], 10));
    }
  }
}

// ---------- 双模式（知识学习=tutor / 源码学习=pair） ----------

const modeBtns = {
  tutor: document.getElementById("mode-tutor"),
  pair: document.getElementById("mode-pair"),
};
const panelShowBtn = document.getElementById("code-panel-show");

function setLayout(mode) {
  document.body.dataset.layout = mode;
  localStorage.setItem("layout", mode);
  modeBtns.tutor.classList.toggle("active", mode === "tutor");
  modeBtns.pair.classList.toggle("active", mode === "pair");
  if (mode === "pair") {
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

async function setAgentMode(mode) {
  try {
    const res = await fetch("/api/session/mode", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const r = await res.json();
    if (!r.ok) { showToast(r.error || "模式切换失败"); return; }
    setLayout(mode === "code" ? "pair" : "tutor");
    if (mode === "code") showToast("已切换到源码学习（agent 模式：AI 可建 demo / 改文件 / 起进程）");
  } catch (e) {
    showToast("模式切换失败：" + e.message);
  }
}
modeBtns.tutor.onclick = () => setAgentMode("study");
modeBtns.pair.onclick = () => setAgentMode("code");

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

// 初始布局
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

// fetch 包装：401 → 弹登录层 → 重放
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

// ---- 上下文仪表（M8）----

const ctxPill = document.getElementById("ctx-pill");
const ctxBar = document.getElementById("ctx-bar");
const ctxText = document.getElementById("ctx-text");
function fmtK(n) {
  return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "K" : String(n);
}
async function refreshCtxStatus() {
  try {
    const r = await (await fetch("/api/context-status")).json();
    if (!r || typeof r.total !== "number") return;
    ctxPill.classList.remove("hidden", "warn", "hot");
    const pct = Math.round((r.ratio || 0) * 100);
    ctxText.textContent = `上下文 ${fmtK(r.total)}/${fmtK(r.budget)}`;
    ctxBar.style.width = Math.min(100, pct) + "%";
    const L = r.layers || {};
    const tag = r.source === "calibrated" ? "实测校准"
      : (r.source === "measured" ? "实测" : "估算");
    const td = r.today || {};
    ctxPill.title =
      `上下文占用 ${fmtK(r.total)} / ${fmtK(r.budget)}（${pct}%）· ${tag}\n` +
      `钉住 ${fmtK(L.pinned || 0)} · 归档摘要 ${fmtK(L.archive || 0)} · 对话窗口 ${fmtK(L.window || 0)}\n` +
      `已归档 ${r.archived_turns} 条 / 共 ${r.turns} 条消息 · 超过 ${Math.round((r.trigger_ratio || 0.8) * 100)}% 将自动压缩历史\n` +
      (r.last_measured != null ? `最近一轮实测 ${fmtK(r.last_measured)}（含当轮注入内容，供参考）\n` : "") +
      `今日消耗 ${td.calls || 0} 次 · 输入 ${fmtK(td.in_tokens || 0)} · 输出 ${fmtK(td.out_tokens || 0)}`;
    if (r.ratio >= (r.trigger_ratio || 0.8)) ctxPill.classList.add("hot");
    else if (r.ratio >= (r.trigger_ratio || 0.8) * 0.75) ctxPill.classList.add("warn");
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
  const summaryEl = document.getElementById("usage-summary");
  const todayEl = document.getElementById("usage-today");
  summaryEl.textContent = "加载中…";
  todayEl.textContent = "";
  const [u, a] = await Promise.all([
    (await fetch("/api/observability/usage?days=7")).json(),
    (await fetch("/api/auth/status")).json(),
  ]);
  const t = u.totals, td = u.today || {};
  const _CUR = { CNY: "¥", USD: "$", EUR: "€", GBP: "£", JPY: "¥" };
  function _fmtCost(cost, costsByCurrency) {
    if (costsByCurrency && typeof costsByCurrency === "object") {
      const parts = Object.entries(costsByCurrency)
        .filter(([, v]) => v > 0)
        .map(([cur, v]) => `${_CUR[cur] || cur}${v}`);
      if (parts.length > 0) return parts.join(" / ");
    }
    return cost ? `¥${cost}` : "";
  }
  summaryEl.textContent =
    `近 ${u.days} 天：${t.calls} 次调用（失败 ${t.failures}）· ` +
    `输入 ${t.in_tokens.toLocaleString()} tok · 输出 ${t.out_tokens.toLocaleString()} tok` +
    (_fmtCost(t.cost, t.costs_by_currency) ? ` · 估算成本 ${_fmtCost(t.cost, t.costs_by_currency)}` : "") +
    "（token 为实际/估算混排，仅供参考）";
  todayEl.textContent =
    `今日：${td.calls || 0} 次 · 输入 ${(td.in_tokens || 0).toLocaleString()} tok · ` +
    `输出 ${(td.out_tokens || 0).toLocaleString()} tok` +
    (_fmtCost(td.cost, td.costs_by_currency) ? ` · ${_fmtCost(td.cost, td.costs_by_currency)}` : "");
  todayEl.style.cssText = "font-size:13px;color:var(--text-dim);margin-top:6px";
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

// ---------- 面试话术库（M4） ----------

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

// ---------- 教学建议卡片 ----------

// 教学行动 → 指令/消息映射
const actionCommands = {
    'REVIEW_PREREQ':    '[先修诊断]',                         // → /api/command
    'RETELL_CORE':      '请重新讲解这个概念的核心要点',        // → /api/chat
    'VARIANT_QUIZ':     '请给我出几道变体练习题',              // → /api/chat
    'ADVANCE_NEXT':     '[下一内容]',                         // → /api/command
    'REST':             null,                                 // 仅隐藏卡片
    'CHANGE_ANGLE':     '请换一个角度讲解这个知识点',          // → /api/chat
    'PRACTICE_PROJECT': '[开始写代码]'                        // → /api/command
};

// 采纳按钮处理：根据映射路由到 /api/command 或 /api/chat
function adoptTeachingSuggestion(action) {
    const mapped = actionCommands.hasOwnProperty(action) ? actionCommands[action] : null;
    // 隐藏卡片
    const card = event.target.closest('.teaching-suggestion-card');
    if (card) card.remove();
    if (mapped === null || mapped === undefined) return;  // REST：仅视觉弱化
    if (mapped.startsWith('[')) {
        // 现有 SOP 指令 → /api/command
        streamPost('/api/command', mapped);
    } else {
        // 自然语言消息 → /api/chat
        streamPost('/api/chat', mapped);
    }
}

function renderTeachingSuggestion(container, ev) {
    const data = typeof ev === 'string' ? JSON.parse(ev) : ev;
    if (!data || !data.action) return;

    const labels = {
        'REVIEW_PREREQ': '🔗 补先修', 'RETELL_CORE': '📖 重讲核心',
        'VARIANT_QUIZ': '🔄 变体练习', 'ADVANCE_NEXT': '➡️ 推进下一概念',
        'REST': '☕ 休息一下', 'CHANGE_ANGLE': '🔀 换个角度',
        'PRACTICE_PROJECT': '💻 项目实践'
    };

    const card = document.createElement('div');
    card.className = 'teaching-suggestion-card';
    card.innerHTML = `
        <div style="font-weight:600;margin-bottom:6px">${labels[data.action] || data.action}</div>
        <div style="font-size:0.9em;color:#666;margin-bottom:8px">${escapeHtml(data.reason || '')}</div>
        <div style="display:flex;gap:8px">
            <button onclick="adoptTeachingSuggestion('${data.action}')" style="padding:4px 12px;border-radius:4px;border:none;background:var(--primary,#4a90d9);color:#fff;cursor:pointer">采纳</button>
            <button onclick="this.parentElement.parentElement.remove()" style="padding:4px 12px;border-radius:4px;border:1px solid #ccc;background:transparent;cursor:pointer">跳过</button>
        </div>
    `;
    container.appendChild(card);
    scrollToBottom();
}

// ---------- Web 搜索 + 文件上传按钮 ----------

// 注入辅助样式
(function injectAuxStyles() {
  const s = document.createElement("style");
  s.textContent = `
    #input-form .input-aux-btn {
      background: transparent; box-shadow: none; padding: 6px 4px;
    }
    #input-form .input-aux-btn:hover {
      background: var(--accent-soft); filter: none; box-shadow: none;
    }
    .input-aux-btn:disabled {
      opacity: 0.4; cursor: not-allowed;
    }
    .input-aux-btn {
      background: transparent; border: none; cursor: pointer;
      font-size: 20px; line-height: 1; padding: 6px 4px; flex-shrink: 0;
      color: var(--text-dim); border-radius: 8px; transition: background .15s, color .15s;
    }
    .input-aux-btn:hover { background: var(--accent-soft); color: var(--accent); }
    .search-bar {
      display: none; align-items: center; gap: 8px;
      margin: 0 20px 4px; padding: 6px 12px;
      background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
    }
    .search-bar.open { display: flex; }
    .search-bar input {
      flex: 1; border: none; outline: none; background: transparent;
      font-size: 14px; color: var(--text); font-family: inherit;
    }
    .search-bar button {
      background: none; border: none; cursor: pointer; font-size: 16px;
      color: var(--text-dim); padding: 2px 4px;
    }
    .search-bar button:hover { color: var(--accent); }
    .upload-progress {
      font-size: 12px; color: var(--text-dim); padding: 2px 20px 0;
    }
  `;
  document.head.appendChild(s);
})();

// 在 input-form 内，发送按钮之前插入辅助按钮
(function injectAuxButtons() {
  const sendBtn = form.querySelector('button[type="submit"]');

  // 🔍 搜索按钮
  const searchBtn = document.createElement("button");
  searchBtn.type = "button";
  searchBtn.className = "input-aux-btn";
  searchBtn.textContent = "🔍";
  searchBtn.title = "Web 搜索";
  searchBtn.id = "btn-web-search";

  // 📎 附件按钮
  const attachBtn = document.createElement("button");
  attachBtn.type = "button";
  attachBtn.className = "input-aux-btn";
  attachBtn.textContent = "📎";
  attachBtn.title = "上传文件（图片/文档）";
  attachBtn.id = "btn-file-upload";

  // 隐藏 file input
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = ".jpg,.jpeg,.png,.gif,.webp,.md,.txt,.pdf";
  fileInput.style.display = "none";
  fileInput.id = "file-input-hidden";

  form.insertBefore(fileInput, sendBtn);
  form.insertBefore(attachBtn, sendBtn);
  form.insertBefore(searchBtn, sendBtn);

  // 搜索栏（在 form 上方插入）
  const searchBar = document.createElement("div");
  searchBar.className = "search-bar";
  searchBar.id = "search-bar";
  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.placeholder = "输入搜索关键词…";
  searchInput.id = "search-input";
  const searchGoBtn = document.createElement("button");
  searchGoBtn.textContent = "搜索";
  searchGoBtn.type = "button";
  const searchCloseBtn = document.createElement("button");
  searchCloseBtn.textContent = "✕";
  searchCloseBtn.type = "button";
  searchBar.append(searchInput, searchGoBtn, searchCloseBtn);
  form.parentNode.insertBefore(searchBar, form);

  // 事件：搜索按钮 → 显示搜索栏
  searchBtn.onclick = () => {
    searchBar.classList.toggle("open");
    if (searchBar.classList.contains("open")) searchInput.focus();
  };

  // 事件：执行搜索
  function doSearch() {
    const q = searchInput.value.trim();
    if (!q) return;
    searchBar.classList.remove("open");
    searchInput.value = "";
    streamPost("/api/chat", "web_search:" + q);
  }
  searchGoBtn.onclick = doSearch;
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); doSearch(); }
    if (e.key === "Escape") { searchBar.classList.remove("open"); searchInput.value = ""; }
  });
  searchCloseBtn.onclick = () => {
    searchBar.classList.remove("open");
    searchInput.value = "";
  };

  // 事件：附件按钮 → 打开文件选择器
  attachBtn.onclick = () => fileInput.click();
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) {
      handleFileUpload(fileInput.files[0]);
      fileInput.value = "";  // 允许重复选同一文件
    }
  });
})();

// ---------- 文件上传 ----------

async function handleFileUpload(file) {
  const maxSize = 20 * 1024 * 1024;  // 20 MB
  if (file.size > maxSize) {
    showToast("文件过大（上限 20 MB）");
    return;
  }

  // 显示上传进度
  const progEl = document.createElement("div");
  progEl.className = "upload-progress";
  progEl.textContent = `⏳ 正在上传：${file.name}（${formatFileSize(file.size)}）…`;
  form.parentNode.insertBefore(progEl, form);

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    progEl.remove();
    if (data.ok === false) {
      showToast(data.error || "上传失败");
      return;
    }
    // 在输入框插入文件引用
    const ref = data.filename || data.name || file.name;
    const url = data.url || data.path || "";
    const prefix = inputEl.value ? " " : "";
    inputEl.value += `${prefix}[${ref}](${url}) `;
    autosizeInput();
    inputEl.focus();
    showToast(`✅ 已上传：${ref}`);
  } catch (err) {
    progEl.remove();
    showToast("上传失败：" + (err.message || err));
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

// ---------- 启动 ----------

(async () => {
  try {
    const a = await (await fetch("/api/auth/status")).json();
    if (a.gate && !a.authed) await ensureLogin();
  } catch (e) { /* 服务未就绪时静默 */ }
})();
refreshState();
refreshLlmStatus();
refreshCtxStatus();
if (window.bindContentViewer) {
  bindContentViewer(document.body);
}
loadCommands();
loadHistory();
loadWorkspaces();
setInterval(refreshState, 10000);
setInterval(refreshLlmStatus, 15000);
setInterval(refreshCtxStatus, 15000);
