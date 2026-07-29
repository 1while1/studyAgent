// ---------- Markdown 渲染 + 代码引用芯片 + toast ----------
// 从 app.js 拆分出的独立功能域模块

marked.setOptions({ breaks: true, gfm: true });

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
      // 克隆后剔除所有按钮再取文本，避免「复制/放大」等按钮文字混入（M10 审查修复）
      const clone = pre.cloneNode(true);
      clone.querySelectorAll("button").forEach(b => b.remove());
      navigator.clipboard.writeText(clone.innerText.trim());
      btn.textContent = "已复制";
      setTimeout(() => (btn.textContent = "复制"), 1500);
    };
    pre.appendChild(btn);
  });
  if (isFinal) renderMermaidBlocks(el);
  linkifyCodeRefs(el);
  if (window.injectZoomButtons) injectZoomButtons(el);  // M10 放大查看
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

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;").replace(/'/g, "&#39;");  // 属性上下文安全（C3）
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
