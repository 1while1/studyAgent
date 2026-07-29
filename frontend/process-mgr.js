// ---------- 进程管理 + 实战工坊（新建 demo 弹窗） ----------
// 从 app.js 拆分出的独立功能域模块

// ---- M6 实战工坊：新建 demo 弹窗 ----

const demoModal = document.getElementById("demo-modal");
document.getElementById("demo-new").onclick = async () => {
  const res = await fetch("/api/demo/scaffolds");
  const r = await res.json();
  const sel = document.getElementById("demo-type");
  sel.innerHTML = "";
  for (const s of r.scaffolds || []) {
    const opt = document.createElement("option");
    opt.value = s.type;
    const raw = (s.description || "").replace(/^studyAgent 实战工坊生成的\s*/, "")
      .split(/[，。；：,.;:!！？?（(]/)[0].trim();
    let desc = raw.slice(0, 24);
    if (raw.length > 24 && /[A-Za-z0-9]$/.test(desc) && /[A-Za-z0-9]/.test(raw[24])) {
      desc = desc.replace(/\s*\S*$/, "").trim();
    }
    opt.textContent = desc ? `${s.type} — ${desc}` : s.type;
    opt.title = s.description || s.type;
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
  await loadCodeRoots(true);
  showToast(`demo 已创建：${r.path}（可选中文件编辑，或让 AI 构建/启动）`);
  setTimeout(() => demoModal.classList.add("hidden"), 900);
};

// ---- M6 实战工坊：进程面板 ----

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

document.getElementById("proc-clean").onclick = async () => {
  const res = await fetch("/api/processes/clear-stopped", { method: "POST" });
  const r = await res.json();
  if (!r.ok) { showToast(r.error || "清理失败"); return; }
  showToast(r.cleared ? `已清理 ${r.cleared} 个已停止进程` : "没有已停止的进程");
  refreshProcesses();
};

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
  if (!r.ok) { showToast(r.error || "启动失败"); return; }
  document.getElementById("proc-cmd").value = "";
  showToast(`进程已启动（${r.id}）${r.ports && r.ports.length ? "，端口 " + r.ports.join("/") : ""}`);
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
