// Token 用量统计页（M9）：KPI 卡 / 日趋势 / 三栏汇总 / 全维度明细
"use strict";

const $ = (id) => document.getElementById(id);

// 主题跟随主页布局偏好（tutor 暖纸 / pair 深色）
document.body.dataset.layout = localStorage.getItem("layout") || "tutor";

function fmtK(n) {
  if (n == null) return "—";
  return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "K" : String(n);
}
function fmtFull(n) { return (n ?? 0).toLocaleString(); }
const _CURRENCY_SYMBOLS = { CNY: "¥", USD: "$", EUR: "€", GBP: "£", JPY: "¥" };
function fmtCost(c, costsByCurrency) {
  // 多币种：传入字典时按币种拼接
  if (costsByCurrency && typeof costsByCurrency === "object") {
    const parts = Object.entries(costsByCurrency)
      .filter(([, v]) => v > 0)
      .map(([cur, v]) => `${_CURRENCY_SYMBOLS[cur] || cur}${v}`);
    if (parts.length > 0) return parts.join(" / ");
  }
  // 向后兼容：数字或无值
  if (c) return `¥${c}`;
  return "—";
}
function fmtPct(x) { return x == null ? "—" : (x * 100).toFixed(1) + "%"; }

async function load() {
  const days = $("u-days").value;
  const ws = $("u-ws").value;
  const url = `/api/observability/usage?days=${days}&ws=${encodeURIComponent(ws)}`;
  let u;
  try {
    const res = await fetch(url);
    if (res.status === 401) {
      // 不毁容器（筛选可继续触发）：提示层与内容区分离
      const tip = $("u-auth-tip");
      tip.innerHTML = '需要登录：<a href="/">回主页登录后再来 →</a>';
      tip.classList.remove("hidden");
      for (const el of document.querySelectorAll(
          ".usage-main > section, .usage-main > .panel-grid")) {
        el.style.display = "none";
      }
      return;
    }
    u = await res.json();
  } catch (e) {
    const tip = $("u-auth-tip");
    tip.textContent = "加载失败：服务未就绪";
    tip.classList.remove("hidden");
    return;
  }
  renderWsOptions(u.workspaces || []);
  renderKpi(u);
  renderChart(u.daily || []);
  renderMini($("u-by-ws"), u.by_workspace || [], "ws");
  renderMini($("u-by-model"), u.by_model || [], "model");
  renderMini($("u-by-task"), u.by_task || [], "task");
  renderDetail(u.rows || []);
}

function renderWsOptions(list) {
  const sel = $("u-ws");
  const cur = sel.value;
  sel.innerHTML = '<option value="">全部</option>';
  for (const w of list) {
    const o = document.createElement("option");
    o.value = w; o.textContent = w;
    sel.appendChild(o);
  }
  sel.value = cur;
}

function renderKpi(u) {
  const k = u.kpi || {}, t = u.today || {};
  const cards = [
    ["总调用", fmtFull(k.calls), `今日 ${fmtFull(t.calls)}`],
    ["总输入", fmtFull(k.in_tokens), `今日 ${fmtFull(t.in_tokens)}`],
    ["总输出", fmtFull(k.out_tokens), `今日 ${fmtFull(t.out_tokens)}`],
    ["估算成本", fmtCost(k.cost, k.costs_by_currency), `今日 ${fmtCost(t.cost, t.costs_by_currency)}`],
    ["缓存命中率", fmtPct(k.cache_hit_rate), "命中按低价计费"],
    ["失败率", fmtPct(k.fail_rate), ""],
  ];
  $("u-kpi").innerHTML = "";
  for (const [label, val, sub] of cards) {
    const d = document.createElement("div");
    d.className = "kpi-card";
    d.innerHTML = `<div class="kpi-label"></div><div class="kpi-val"></div><div class="kpi-sub"></div>`;
    d.children[0].textContent = label;
    d.children[1].textContent = val;
    d.children[2].textContent = sub;
    $("u-kpi").appendChild(d);
  }
}

function renderChart(daily) {
  const el = $("u-chart");
  el.innerHTML = "";
  if (!daily.length) { el.textContent = "暂无数据"; return; }
  const max = Math.max(...daily.map(d => d.in_tokens + d.out_tokens), 1);
  for (const d of daily) {
    const col = document.createElement("div");
    col.className = "chart-col";
    col.title = `${d.date}\n输入 ${fmtFull(d.in_tokens)} · 输出 ${fmtFull(d.out_tokens)}`;
    const inH = Math.round(d.in_tokens / max * 100);
    const outH = Math.round(d.out_tokens / max * 100);
    const bar = document.createElement("div");
    bar.className = "chart-bar";
    const segO = document.createElement("i");
    segO.className = "seg-out";
    segO.style.height = outH + "%";
    const segI = document.createElement("i");
    segI.className = "seg-in";
    segI.style.height = inH + "%";
    bar.append(segO, segI);
    const day = document.createElement("div");
    day.className = "chart-day";
    day.textContent = d.date.slice(5);
    col.append(bar, day);
    el.appendChild(col);
  }
  const legend = document.createElement("div");
  legend.className = "chart-legend";
  legend.innerHTML = '<i class="seg-in"></i>输入 <i class="seg-out"></i>输出';
  el.appendChild(legend);
}

function renderMini(table, rows, nameKey) {
  table.innerHTML = "<thead><tr><th></th><th>调用</th><th>输入</th><th>输出</th><th>成本</th></tr></thead>";
  const tb = document.createElement("tbody");
  if (!rows.length) tb.innerHTML = '<tr><td colspan="5">暂无数据</td></tr>';
  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const c of [r[nameKey], fmtFull(r.calls), fmtK(r.in_tokens),
                     fmtK(r.out_tokens), fmtCost(r.cost, r.costs_by_currency)]) {
      const td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    }
    tb.appendChild(tr);
  }
  table.appendChild(tb);
}

function renderDetail(rows) {
  const tb = $("u-detail-rows");
  tb.innerHTML = "";
  if (!rows.length) {
    tb.innerHTML = '<tr><td colspan="10">暂无记录</td></tr>';
    return;
  }
  for (const g of rows.slice().reverse()) {  // 最新日期在前
    const tr = document.createElement("tr");
    const measured = g.calls - g.est_calls;
    const basis = g.est_calls ? `实测 ${measured} / 估算 ${g.est_calls}` : "实测";
    const cells = [g.date, g.ws, `${g.provider} / ${g.model}`, g.task,
                   g.calls, basis, fmtFull(g.in_tokens), fmtFull(g.cache_hit || 0),
                   fmtFull(g.out_tokens), fmtCost(g.cost, g.costs_by_currency)];
    cells.forEach((c, i) => {
      const td = document.createElement("td");
      td.textContent = c;
      if (i === 4 && g.failures > 0) {
        td.textContent = `${c}（失败 ${g.failures}）`;
        td.className = "usage-err";
      }
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  }
}

$("u-days").onchange = load;
$("u-ws").onchange = load;
load();
