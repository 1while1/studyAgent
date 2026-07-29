// ---------- 掌握度面板（战术板 / 战略雷达 / 复习预警） ----------
// 从 app.js 拆分出的独立功能域模块

const masteryPage = document.getElementById("mastery-page");
document.getElementById("open-learner").onclick = openLearner;
document.getElementById("mastery-close").onclick = () => masteryPage.classList.add("hidden");
masteryPage.addEventListener("click", (e) => {
  if (e.target === masteryPage) masteryPage.classList.add("hidden");
});

// evidence 类型 → 人性化中文名
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

  const curDay = model.current_day;
  const isToday = (c) => c.id.startsWith(`Day${curDay}-`);
  const isUrgent = (c) => c.evidence.length && (c.due || c.mastery < 0.4);
  const remediation = model.remediation_order || [];
  const ridx = (c) => { const i = remediation.indexOf(c.id); return i < 0 ? 9999 : i; };
  const urgent = concepts.filter(isUrgent).sort(
    (a, b) => (ridx(a) - ridx(b)) || (b.due - a.due) ||
              (a.mastery - b.mastery) || a.id.localeCompare(b.id));
  const today = concepts.filter(c => isToday(c) && !isUrgent(c));
  const rest = concepts.filter(c => !isToday(c) && !isUrgent(c));

  document.getElementById("ms-today-day").textContent = curDay;
  renderMasterySection("ms-urgent", urgent,
    "🎉 没有紧急项——没有到期复习，也没有薄弱知识点，保持节奏！");
  renderMasterySection("ms-today", today,
    "（今日单元的知识点将在考核/同步后自动出现）");
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

  if (expandCid) {
    const row = document.querySelector(
      `.mastery-row[data-cid="${CSS.escape(expandCid)}"]`);
    if (row) {
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
  pct.textContent = c.evidence.length ? (c.mastery * 100).toFixed(1) + "%" : "无证据";
  top.appendChild(pct);
  row.appendChild(top);
  const hair = document.createElement("div");
  hair.className = "mr-hair " + band;
  hair.style.width = Math.round(c.mastery * 100) + "%";
  row.appendChild(hair);
  row.onclick = () => toggleMasteryDetail(row, c);
  return row;
}

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
  const advice = document.createElement("div");
  advice.className = "md-advice";
  advice.textContent = masteryAdvice(c);
  detail.appendChild(advice);
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
  if (c.prerequisites.length) {
    const p = document.createElement("div");
    p.className = "learner-meta";
    p.textContent = `先修：${c.prerequisites.join("、")}`;
    detail.appendChild(p);
  }
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
    const decay = document.createElement("div");
    decay.className = "md-decay";
    decay.textContent = "证据随时间衰减：半衰期 14 天（14 天前的证据权重减半）。保持复习与实战，掌握度才不会回落。";
    det.appendChild(decay);
  }
  detail.appendChild(det);
}

// 关联资料直达
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

// ---- 战略雷达 ----

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
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
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
  const hasAny = Object.keys(counts).length > 0;
  box.classList.toggle("is-empty", !hasAny);
  if (!hasAny) {
    const tip = document.createElement("div");
    tip.className = "heat-empty";
    tip.textContent = "暂无学习活动";
    box.appendChild(tip);
  }
}

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
  const pmap = {};
  for (const c of concepts) pmap[c.id] = c.prerequisites || [];
  const unmastered = new Set(concepts
    .filter(c => c.evidence.length && c.mastery < 0.7).map(c => c.id));
  const upstreamOf = (cid) => {
    const out = [], seen = new Set([cid]);
    const stack = [...(pmap[cid] || [])];
    while (stack.length) {
      const n = stack.pop();
      if (seen.has(n)) continue;
      seen.add(n); out.push(n);
      stack.push(...(pmap[n] || []));
    }
    return out;
  };
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
      pct.textContent = c.evidence.length ? (c.mastery * 100).toFixed(1) + "%" : "—";
      row.append(dot, main, pct);
      const ups = upstreamOf(c.id);
      const weakUps = ups.filter(id => unmastered.has(id));
      if (weakUps.length) {
        const badge = document.createElement("span");
        badge.className = "tl-badge";
        badge.textContent = `▲${weakUps.length}`;
        badge.title = `上游未达标 ${weakUps.length} 个（先补根基再学本节点）`;
        row.appendChild(badge);
      }
      row.addEventListener("mouseenter", () => {
        for (const id of ups) {
          const r = box.querySelector(`.tl-row[data-cid="${CSS.escape(id)}"]`);
          if (r) r.classList.add("tl-upstream");
        }
      });
      row.addEventListener("mouseleave", () => {
        box.querySelectorAll(".tl-upstream")
          .forEach(r => r.classList.remove("tl-upstream"));
      });
      row.onclick = () => {
        document.querySelector(".drawer-tab[data-mtab='tactical']").click();
        openLearner(c.id);
      };
      box.appendChild(row);
      if (String(day) === curDay && !currentRow) currentRow = row;
    }
  }
  if (box.querySelector(".tl-badge")) {
    const lg = document.createElement("div");
    lg.className = "tl-legend";
    lg.textContent = "▲n = 补弱优先级（先修链第 n 顺位）";
    box.appendChild(lg);
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

// ---- 侧栏复习预警 widget ----

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
      m.textContent = (c.mastery * 100).toFixed(1) + "%";
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
