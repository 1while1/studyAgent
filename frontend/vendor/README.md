# frontend/vendor — 本地前端库（禁止用 CDN 替换）

| 库 | 版本 | 文件 | 用途 |
|----|------|------|------|
| marked | （早期引入） | marked.min.js | Markdown 渲染 |
| DOMPurify | （早期引入） | purify.min.js | XSS 过滤 |
| highlight.js | （早期引入） | highlight.min.js + github-dark.min.css | 聊天代码块高亮 |
| mermaid | 11 | mermaid.min.js | Mermaid 图终渲染 |
| monaco-editor | **0.52.2**（2026-07-23 自 jsdelivr 拉取，字节数逐项校验 + node --check 语法校验） | monaco/vs/（loader.js、editor/editor.main.js+css、base/worker/workerMain.js、basic-languages/ 全量 81 语言、nls.messages.zh-cn.js、base/browser/ui/codicons/codicon/codicon.ttf，共 87 文件 5.0MB） | M6 实战工坊：源码学习（pair）布局的代码查看/编辑组件。**仅 pair 布局首次打开文件时动态加载**（设计硬规）；workers 经 data-URL 包装指 workerMain.js；未 vendor language/ 智能感知目录（ts/css/html/json intellisense 舍弃，保留 monarch 高亮） |

> Monaco 版本号固定在此文件登记（AgentDesign §7 硬要求）；升级需重跑下载校验并更新本行。
