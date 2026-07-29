# 改进5：前端模块化拆分

## 背景
`frontend/app.js` 原始 3272 行单文件，按功能域拆分为多个独立 JS 文件，保持 `<script>` 标签加载模式（不使用 ES modules）。

## 拆分方案

| 文件 | 功能域 | 提取行数 | 关键导出 |
|------|--------|---------|---------|
| `markdown.js` | Markdown 渲染 + 代码引用芯片 + toast | ~126 | `renderMarkdownInto`, `showToast`, `escapeHtml` |
| `code-browser.js` | 代码浏览器（目录树/Monaco/保存/拖拽） | ~428 | `openCodeFile`, `loadCodeRoots`, `flashLines`, `codeState` |
| `llm-config.js` | 模型配置弹窗 | ~138 | `openLlmConfig`, `saveLlmConfig` |
| `workspace-mgr.js` | 工作区切换/创建/扫描/导出 | ~176 | `loadWorkspaces`, `switchWorkspace` |
| `mastery.js` | 掌握度面板（战术板/雷达/预警） | ~563 | `openLearner`, `renderRadar`, `refreshUrgentWidget` |
| `notes-page.js` | 笔记管理（CRUD/编辑器/合并/蒸馏） | ~511 | `openNotes`, `notesState` |
| `process-mgr.js` | 进程管理 + 实战工坊 | ~198 | `refreshProcesses`, `tailProcLog` |

## app.js 保留内容（~1040 行）
- 全局 DOM 引用和状态变量
- SSE 通信（`streamPost`/`sendChat`/`sendCommand`）— 铁律 8 核心
- 消息气泡渲染（`addMessage`/`addUserMessage`/`addToolReadChip`）
- 状态面板刷新（`refreshState`）
- 指令补全菜单
- 侧边栏逻辑
- 资料弹窗/资料库（`openDoc`/`openMaterials`/`openMaterialPreview`）
- 双模式切换（`setLayout`/`setAgentMode`）
- 认证门控 + fetch 包装
- LLM 状态条/上下文仪表/用量弹窗
- 面试话术库
- 初始化代码

## 跨文件依赖
通过全局作用域访问（与 `viewer.js`/`usage.js` 同一模式）：
- `markdown.js` → `window.marked`, `window.DOMPurify`, `window.hljs`（vendor 库）
- `code-browser.js` → `showToast`（markdown.js）, `setLayout`（app.js，运行时调用）
- `mastery.js` → `openMaterials`, `openMaterialPreview`（app.js，运行时调用）
- `process-mgr.js` → `loadCodeRoots`, `codeState`（code-browser.js）
- `workspace-mgr.js` → `escapeHtml`, `showToast`（markdown.js）
- `notes-page.js` → `renderMarkdownInto`, `showToast`（markdown.js）

## Script 加载顺序
```html
<script src="vendor/marked.min.js"></script>
<script src="vendor/purify.min.js"></script>
<script src="vendor/highlight.min.js"></script>
<script src="vendor/mermaid.min.js"></script>
<script src="viewer.js"></script>
<script src="markdown.js"></script>      ← 基础渲染（被其他模块依赖）
<script src="code-browser.js"></script>  ← 代码浏览器
<script src="llm-config.js"></script>    ← 模型配置
<script src="workspace-mgr.js"></script> ← 工作区
<script src="mastery.js"></script>       ← 掌握度
<script src="notes-page.js"></script>    ← 笔记
<script src="process-mgr.js"></script>   ← 进程
<script src="app.js"></script>           ← 核心（最后加载）
```

## 约束检查
- ✅ 铁律 8：`streamPost` 的 try/catch/finally + 发送锁保留在 app.js
- ✅ 全局函数签名不变
- ✅ 跨文件引用通过全局作用域
- ✅ vendor 库保持 `<script>` 标签加载
- ✅ 583 测试全绿（前端拆分不影响后端测试）
