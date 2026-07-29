// ---------- 笔记页 v2（书架三栏 + Markdown 编辑器） ----------
// 从 app.js 拆分出的独立功能域模块

const notesPage = document.getElementById("notes-page");
const NOTE_KINDS = { stuck: "卡壳", question: "疑问", mastered: "已掌握", insight: "心得" };
var notesState = {
  shelf: "all", kind: "", search: "",
  notes: [], concepts: [], selectedId: null,
  dirty: false, mergeMode: false, mergePicks: [],
};

document.getElementById("open-notes").onclick = openNotes;
document.getElementById("notes-close").onclick = closeNotes;
document.getElementById("notes-back").onclick = closeNotes;

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
    cb.checked = notesState.mergePicks.includes(n.id);
    cb.onchange = () => {
      if (cb.checked) notesState.mergePicks.push(n.id);
      else notesState.mergePicks = notesState.mergePicks.filter(x => x !== n.id);
    };
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
    notesState.mergePicks = [];
    btn.classList.add("active");
    renderNotesList();
    return;
  }
  const ids = [...notesState.mergePicks];
  notesState.mergeMode = false;
  notesState.mergePicks = [];
  btn.classList.remove("active");
  if (ids.length < 2) { renderNotesList(); return; }
  if (!confirm(`合并 ${ids.length} 条笔记？文本并入最早勾选的那条，其余标记为已合并。`)) {
    renderNotesList();
    return;
  }
  const r = await notesApi("/api/notes/merge", { keep: ids[0], others: ids.slice(1) });
  if (!r.ok) { showToast(r.error || "合并失败"); return; }
  showToast("已合并");
  await reloadNotes();
};
