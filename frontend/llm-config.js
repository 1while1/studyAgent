// ---------- 模型配置弹窗 ----------
// 从 app.js 拆分出的独立功能域模块

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
  // ---------- MCP Server 管理区域 ----------
  // 先清除旧实例，避免重复打开时重复插入
  document.querySelectorAll("#mcp-server-list,#plugin-list").forEach(el => el.closest(".settings-section")?.remove());
  const mcpSection = document.createElement("div");
  mcpSection.className = "settings-section";
  mcpSection.innerHTML = `
    <fieldset>
      <legend>MCP Server 管理</legend>
      <div id="mcp-server-list">
        <p class="mcp-status" style="color:var(--text-dim);font-size:13px;margin:4px 0">MCP Client 已就绪，可在 settings.toml 中配置 server</p>
      </div>
      <button class="btn-secondary" style="margin-top:6px" onclick="alert('MCP Server 配置请在 settings.toml 的 [[mcp.servers]] 中添加')">配置说明</button>
    </fieldset>
  `;

  // ---------- Plugin/Skill 管理区域 ----------
  const pluginSection = document.createElement("div");
  pluginSection.className = "settings-section";
  pluginSection.innerHTML = `
    <fieldset>
      <legend>Plugin/Skill 管理</legend>
      <div id="plugin-list">
        <p class="plugin-status" style="color:var(--text-dim);font-size:13px;margin:4px 0">Plugin 系统已就绪，可通过 pip install 安装插件</p>
      </div>
      <button class="btn-secondary" style="margin-top:6px" onclick="alert('Plugin 通过 pip entry_points 注册，在 settings.toml [plugins] enabled 中授权')">插件说明</button>
    </fieldset>
  `;

  // 插入到上下文窗口区域之后
  const contextSection = document.getElementById("context-section");
  contextSection.parentNode.insertBefore(mcpSection, contextSection.nextSibling);
  contextSection.parentNode.insertBefore(pluginSection, mcpSection.nextSibling);

  llmModal.classList.remove("hidden");
}

document.addEventListener("click", async (e) => {
  if (!e.target.classList.contains("cfg-test")) return;
  if (!e.target.closest("#provider-sections")) return;
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
    status.textContent = (r.warning ? r.warning + "（旧渠道仍在线）"
      : "已保存并热生效（无需重启）。")
      + (ctxInvalid ? " 注意：上下文项输入无效，该项未保存。" : "");
    status.className = r.warning ? "fail" : "ok";
    if (!silent && !r.warning) setTimeout(() => llmModal.classList.add("hidden"), 800);
  } else {
    status.textContent = `保存失败: ${r.error}`;
    status.className = "fail";
  }
  return r.ok;
}
