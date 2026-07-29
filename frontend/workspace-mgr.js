// ---------- 工作区管理（切换 / 新建初始化向导 / 重新扫描） ----------
// 从 app.js 拆分出的独立功能域模块

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
        `<button class="ws-op" data-op="export" title="导出学习数据（zip）"><svg class="ic" viewBox="0 0 24 24"><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg></button>` +
        (w.active ? "" : `<button class="ws-op" data-op="delete" title="删除工作区"><svg class="ic" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/><path d="M10 11v6M14 11v6"/></svg></button>`) +
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
