# Slash 指令系统设计（v1：框架 + /compact）

> 状态：v1 已实现（2026-07-25，feat/slash-commands）：框架 + /compact 全链路落地
> 背景：现有 `[指令]` 是 SOP 学习流程指令（settings.toml [commands.*] 注册 + /api/command 路由 + 前端补全菜单）。
> 本方案新增**并存的 `/` 系统指令命名空间**：即发即执行的工具指令，不走教学回合。

## 命名空间划分

| 前缀 | 性质 | 例子 | 执行方式 |
|------|------|------|---------|
| `[X]` | SOP 学习流程指令 | [开始今日学习] [下一内容] | handler + SOP 卡，可走 LLM 回合 |
| `/x` | 系统操作指令 | /compact（v1 唯一）/ 未来 /clear /usage /model | 直接执行，一轮 SSE 返回结果 |

两个命名空间共用一个输入框，自动补全菜单分组显示（`/` 系统指令 / `[` 学习指令）。

## /compact 语义

- 手动触发上下文压缩：**保留最近 4 轮原文（2 问 2 答），其余归档为 AI 摘要**
- 复用 `ContextManager._compress`（压缩机器不变，手动构造 plan）：
  `plan = { compress_from: archive_upto, compress_upto: len(history) - 4 }`
- 继承全部护栏：概念 ID/问题数机械校验、校验失败原文全保留不丢数据、失败冷却、摘要 4000 字上限
- 历史 ≤ 4 轮时提示「上下文还很小，无需压缩」，不执行
- 返回压缩报告气泡：窗口 X 条 → 归档 Y 条 / 摘要 Z 字；上下文胶囊实时回落
- **v1 不做** `/compact 全部`（连最近 4 轮也压）——防误操作把热上下文压没
- 可逆性备注：原文不删（archive_upto 只是指针），未来可做 /uncompact

## 实施要点

### 后端（~120 行）
- `backend/engine/commands/slash.py`：SLASH_REGISTRY 注册表 + compact handler
- 路由：输入以 `/` 开头 → slash 注册表（与 `[` 路由互不干扰）；执行沿用流程锁
- compact handler 调 `ContextManager._compress`，返回前后对比数据

### 前端（~60 行）
- 输入框键入 `/` 触发补全（复用现有指令菜单组件，加分组标题）
- 结果气泡渲染压缩报告；SSE done 后 refreshCtxStatus 刷新胶囊

### 测试（4-5 个）
- /compact 正常路径（10 轮历史 → 窗口剩 4 条 + 摘要含概念 ID）
- 历史不足 4 轮 → 友好提示不执行
- 校验失败 → 原文保留（mock LLM 输出坏摘要）
- 与 [指令] 路由隔离（/compact 不进 SOP 路由，[下一内容] 不进 slash 路由）

### 走查
- 补一段：输入 `/` 出菜单 → 选 /compact → 报告气泡出现 → 胶囊回落

## 后续扩展位（注册表已通用，各 ~5 行注册）
- ~~`/clear`（搬现有清空按钮逻辑）~~ ✅ v2 已实现（clear 事件前端整屏清空）
- ~~`/usage`（打开用量弹窗）~~ ✅ v2 已实现（首个客户端指令 client=True）
- ~~`/model`（快速切渠道）~~ ✅ v2 已实现（裸跑看渠道 / `/model <渠道>` 直接切换）
- `/uncompact`（依赖 archive_upto 指针回滚，需额外设计）
