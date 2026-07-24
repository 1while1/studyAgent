// 内容放大查看器（M10）：AI 气泡里的 Mermaid 图 / 图片 / 代码段全屏查看
// - 图表类：滚轮缩放 + 拖拽平移 + 适应屏幕/原始大小（SVG 放大不糊）
// - 代码类：等宽全宽 + 换行开关 + 复制
// 触发：.mermaid / .md img 点击（cursor: zoom-in）；pre 右上角「放大」按钮
"use strict";

(function () {
  // ---- 遮罩 DOM（一次性创建） ----
  const overlay = document.createElement("div");
  overlay.id = "viewer-overlay";
  overlay.className = "hidden";
  overlay.innerHTML =
    '<div class="viewer-toolbar">' +
    '  <button data-act="zoom-out" title="缩小">−</button>' +
    '  <span id="viewer-scale">100%</span>' +
    '  <button data-act="zoom-in" title="放大">＋</button>' +
    '  <button data-act="fit" title="适应屏幕">适应</button>' +
    '  <button data-act="actual" title="原始大小">1:1</button>' +
    '  <button data-act="wrap" title="换行开关" class="viewer-code-only">换行</button>' +
    '  <button data-act="copy" title="复制" class="viewer-code-only">复制</button>' +
    '  <button data-act="close" title="关闭（Esc）">×</button>' +
    "</div>" +
    '<div class="viewer-stage"><div class="viewer-content"></div></div>';
  document.body.appendChild(overlay);

  const stage = overlay.querySelector(".viewer-stage");
  const content = overlay.querySelector(".viewer-content");
  const scaleLabel = overlay.querySelector("#viewer-scale");
  let scale = 1, tx = 0, ty = 0, kind = "";

  function apply() {
    content.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    scaleLabel.textContent = Math.round(scale * 100) + "%";
  }

  function open(node, k) {
    kind = k;
    content.innerHTML = "";
    content.appendChild(node);
    overlay.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    overlay.classList.toggle("viewer-code", k === "code");
    if (k === "code") {
      scale = 1; tx = 0; ty = 0;
    } else {
      fit();  // 图表/图片默认适应屏幕
      return;
    }
    apply();
  }

  function close() {
    overlay.classList.add("hidden");
    document.body.style.overflow = "";
    content.classList.remove("wrap");  // 重置换行状态，下次打开代码默认不换行
    content.innerHTML = "";
  }

  function fit() {
    const box = content.firstElementChild;
    if (!box) return;
    const w = box.scrollWidth || box.clientWidth || 1;
    const h = box.scrollHeight || box.clientHeight || 1;
    scale = Math.min(stage.clientWidth / (w + 40), stage.clientHeight / (h + 80), 1);
    tx = 0; ty = 0;
    apply();
  }

  function zoomAt(factor, cx, cy) {
    const next = Math.min(8, Math.max(0.05, scale * factor));
    if (cx != null) {  // 以光标为锚点缩放
      const r = stage.getBoundingClientRect();
      const px = cx - r.left - r.width / 2;
      const py = cy - r.top - r.height / 2;
      tx = px - (px - tx) * (next / scale);
      ty = py - (py - ty) * (next / scale);
    }
    scale = next;
    apply();
  }

  // ---- 工具栏 ----
  overlay.querySelector(".viewer-toolbar").addEventListener("click", (e) => {
    const act = e.target.dataset && e.target.dataset.act;
    if (!act) return;
    if (act === "close") close();
    else if (act === "zoom-in") zoomAt(1.25);
    else if (act === "zoom-out") zoomAt(0.8);
    else if (act === "fit") fit();
    else if (act === "actual") { scale = 1; tx = 0; ty = 0; apply(); }
    else if (act === "wrap") content.classList.toggle("wrap");
    else if (act === "copy") {
      navigator.clipboard.writeText(content.innerText || "");
      e.target.textContent = "已复制";
      setTimeout(() => (e.target.textContent = "复制"), 1500);
    }
  });

  // ---- 滚轮缩放 / 拖拽平移 / 关闭 ----
  stage.addEventListener("wheel", (e) => {
    if (kind === "code") return;
    e.preventDefault();
    zoomAt(e.deltaY < 0 ? 1.15 : 0.87, e.clientX, e.clientY);
  }, { passive: false });

  let drag = null, downAt = null, suppressClick = false;
  stage.addEventListener("mousedown", (e) => {
    if (kind === "code") return;
    e.preventDefault();  // 阻止原生拖拽/文本选中打断平移
    drag = { x: e.clientX - tx, y: e.clientY - ty };
    downAt = { x: e.clientX, y: e.clientY };
    stage.classList.add("dragging");
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    tx = e.clientX - drag.x; ty = e.clientY - drag.y;
    apply();
  });
  window.addEventListener("mouseup", (e) => {
    // 拖拽松手（位移 > 5px）会紧跟一个 click，抑制它防止误关闭
    if (drag && downAt && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 5) suppressClick = true;
    drag = null; downAt = null;
    stage.classList.remove("dragging");
  });
  overlay.addEventListener("click", (e) => {
    if (suppressClick) { suppressClick = false; return; }
    if (e.target === overlay || e.target === stage) close();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.classList.contains("hidden")) close();
  });

  // ---- 触发绑定（事件委托，历史与后续渲染通吃；幂等） ----
  window.bindContentViewer = function (root) {
    if (root._viewerBound) return;
    root._viewerBound = true;
    root.addEventListener("click", (e) => {
      // Mermaid 图 / 图片：点击本体放大
      const mer = e.target.closest(".mermaid");
      if (mer && mer.querySelector("svg")) {
        const svg = mer.querySelector("svg").cloneNode(true);
        svg.removeAttribute("style");
        svg.removeAttribute("width");   // width="100%" 会让 fit 测量失真，靠 viewBox 自适应
        svg.removeAttribute("height");
        svg.style.maxWidth = "none";
        open(svg, "graph");
        return;
      }
      const img = e.target.closest(".md img");
      if (img) {
        const pic = document.createElement("img");
        pic.src = img.src;
        pic.alt = img.alt || "";
        open(pic, "graph");
        if (!pic.complete) pic.addEventListener("load", fit, { once: true });  // 未加载完时加载后重新 fit
        return;
      }
      // 代码块「放大」按钮
      const zb = e.target.closest(".zoom-btn");
      if (zb) {
        const pre = zb.closest("pre");
        const clone = pre.cloneNode(true);
        clone.querySelectorAll(".copy-btn,.zoom-btn").forEach(b => b.remove());
        open(clone, "code");
      }
    });
  };

  // 给 pre 注入「放大」按钮（与复制并排）；renderMarkdownInto 每轮调用
  window.injectZoomButtons = function (el) {
    el.querySelectorAll("pre").forEach(pre => {
      if (pre.querySelector(".zoom-btn")) return;
      const btn = document.createElement("button");
      btn.className = "zoom-btn";
      btn.textContent = "放大";
      pre.appendChild(btn);
    });
  };
})();
