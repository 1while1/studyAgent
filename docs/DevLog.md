# DevLog — study-web 开发日志与交接上下文

> 用途：跨会话/压缩后恢复上下文。记录当前状态、关键设计决策、已修复 bug 史。
> 最近更新：2026-07-22（Git 初始化完成 + Roadmap 落盘，待开工 P0）

## 当前运行状态

- **Git**：`study-web/.git`（main），root commit `2acc324`（90 文件）。密钥 `.env`/`opencode.txt` 与数据 `runtime/`、`workspaces/` 已 gitignore。提交流程：分支 + 三件套验证（单测/validate/走查）全绿才 commit
- 启动：`cd study-web && python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8765`
- LLM：主渠道 `openai_compat`（OpenCode Go / deepseek-v4-pro，**被上游 401 风控拦截，待解封**）；
  备用 `deepseek_official`（DeepSeek 官方 deepseek-chat，已充值，**当前实际工作渠道**）
- fallback 自动切换已生效（`llm/fallback.py`）
- 工作区：ragent（默认，`../docx`，Day 2 学习中）/ tinyrag（5 天测试，可删）/ onecoupon（25 天，用户项目，初始化验证通过 25/25）
- 测试：`python -m unittest discover -s tests` → 36 个全绿；UI 走查 46 项全绿
- ⚠️ 走查结束会 `POST /api/session/reset` 清测试消息——**有值得保留的对话时不要跑走查**

## 下一步（已规划，见 docs/Roadmap.md）

**P0 教学真实性**：① AI 读文件 tool-use 闭环（`[READ:路径:Lx-y]` → 后端注入真实代码续写，是"导学不瞎讲"的关键，涉及 SSE 协议变更）② Mermaid 图渲染 ③ Study.md 路径存在性校验
**P1 学习闭环**：④ 编码验证（跑用户代码测试）⑤ 增量式 Study.md ⑥ 卡壳/疑问间隔复习
**P2 形态**：⑦ 桌面打包 ⑧ 初始化深度 ⑨ 阶段可配置 ⑩ 工作区删除/导出

## 多工作区机制（v4）

- **Workspace 值对象**（`domain/workspace.py`）：slug/title/goal/docx_dir/project_dir/session_path/total_days/replica_name
- settings.toml：`active_workspace` + `[[workspaces]]`；code_roots 带 `workspace` 字段过滤；无 [[workspaces]] 时旧配置自动合成默认工作区（向后兼容）
- 切换：`POST /api/workspaces/switch` → `app.assemble()` 重建 deps；聊天会话按工作区隔离
- **初始化向导**（顶栏工作区下拉 → 新建工作区）：填项目目录/目标/天数 → 扫描预览 → `repo_scanner` 生成画像 → LLM 生成 Project.md + Study.md → **验证管线**（Project.md 结构检查、Study.md 逐天 `parse_day_text` 解析）→ 失败带错重试 1 次不过不写盘 → 骨架模板写 StudyState/ReplicaPlan/DocIndex/InterviewQA → 注册 settings + code_root + 自动切换
- **重新扫描**：下拉里「↻ 重新扫描项目结构」重新生成 Project.md（prompt 防虚构路径的数据源）
- **资源单源**：`resources/sop/`（模板锚点）、`resources/hooks/validate_study.py`（参数化 docx_dir/total_days/replica_name）、`resources/templates/`（初始化骨架）、`resources/prompts/`（LLM 生成提示词）。`docx/SOP` 保留给 CLI 助手，study-web 以 resources 为准
- **零硬编码**：title/goal/total_days/replica_name/project_dir 全走 Workspace；已清除 7 处 Ragent 字面量（prompt 角色行、start_day 仓库路径、study_plan 前缀剥除、total_days、warmup SOP 卡名、应用标题、代码引用示例）

## 功能清单（已实现）

| 模块 | 说明 |
|------|------|
| 学习流程 | 10 指令、五步状态机、2 回合追问、评分标记落盘、FAIL-FAST 双选项、天数递进 |
| 聊天 | SSE 流式、Markdown 渲染（节流 200ms 最新值渲染 + rawText 累积器）、代码高亮+复制、思考中指示、历史回填 |
| 双模式 | **知识学习**（tutor：暖纸书房，米白+赭石+衬线标题）/ **源码学习**（pair：IDE 深色 #1e1e1e + #0e86d8）。顶栏分段控件切换，模式绑定主题（无独立深浅切换） |
| 布局三区 | 侧栏=纯学习仪表盘（进度/今日单元/同步速览/会话状态一行）；顶栏=模式切换+工作区下拉+工具图标；输入框上方=指令胶囊条 |
| 指令唤起 | 胶囊条点击 + 输入框键入 `[` 弹出补全菜单（Enter 选首项，Esc 关闭，防输入法误触发） |
| 多工作区 | 顶栏下拉切换/新建（初始化向导：扫描→LLM 生成→验证管线）/重新扫描 Project.md；会话与代码根随工作区隔离 |
| 代码浏览器 | 源码学习模式内：roots 持久化（settings.toml `[[code_roots]]` 按工作区过滤）、树懒加载、行号+高亮、标签页式文件头、**IDE 状态栏**（路径·语言·行数·UTF-8）、树折叠/换行开关/树宽拖拽记忆 |
| 片段提问 | 选区浮动按钮 → textarea（换行保留）；聊天渲染为展开式片段卡片；**点 📎 引用跳转代码浏览器打开文件 + 滚动定位 + 黄色行高亮** |
| 代码引用芯片 | AI 回答中反引号路径自动转为可点击芯片；`/api/code/resolve` 三级解析（根前缀→直接相对→后缀索引，60s 缓存）；点击 → 源码学习模式打开文件 + 行高亮；完整路径失败时**按文件名回退定位**；找不到弹 toast。prompt 硬约束第 6 条 + system prompt 注入当前工作区 `Project.md` 防虚构路径 |
| 模型配置页 | 主/备渠道、模型/URL/Key（掩码）、测试连接、保存热生效 |

## 关键设计决策（不要回退）

1. **模板单源** = docx/SOP 锚点；**数据单源** = docx/ 文件；落盘必走规则 14（备份→写→validate→回滚）
2. **sop_card 三态**：纯教学内容生成必须 `sop_card=""`（带卡会让模型复读模板，已踩坑）
3. **start_day 清空 chat_history**：新开始=新对话，防旧进度泄漏（已踩坑）
4. **流式 rawText 累积器**：禁止从 bubble.textContent 回读再渲染（渲染污染→乱码，已踩坑）
5. **静态资源 `Cache-Control: no-cache`**（app.py 中间件）：防新旧 JS/HTML 混搭（已踩坑）
6. **前端交付前必须 Playwright 真实点击验证**（用户定的规矩）：优先跑 `scripts/ui_walkthrough.py`
7. **模式绑定主题**：知识学习=暖纸浅色，源码学习=IDE 深色，无独立深浅切换按钮；主题变量按 `body[data-layout]` 分两套（v3 起，`data-theme` 已废弃）
8. **三区分离**（v3 用户拍板）：状态在侧栏、模式与工具在顶栏、指令贴输入框；模式切换唯一入口 = 顶栏分段控件 `#mode-tutor/#mode-pair`，不再设悬浮胶囊/侧栏按钮
9. **代码面板专属源码学习模式**：tutor 下隐藏；v2 的面板宽屏/拖拽调宽已随旧双布局移除（pair 下面板自适应充满）

## Bug 史（重要，防重犯）

| Bug | 根因 | 修复 |
|-----|------|------|
| 聊天全挂 | opencode 流含空 choices 块 | openai_compat 跳过空块 |
| 内容流完即消失 | message 事件误标 firstDelta，清理误删内容泡 | delta 到达总是清 thinking 态 |
| 回复乱码缝合怪 | 节流渲染后从 textContent 回读累积 | rawText 独立累积器 |
| 模型复读 FAIL-FAST | 指令带整卡 + 用户输入命中触发场景 | 纯教学内容 sop_card="" |
| 模型"接着旧课讲" | 重开后历史残留 assistant 消息 | start_day 清空 history + 指令成对写入 |
| 评分卡死 | 正则不认 `分`字/加粗/半角冒号 | SCORE_RE 全变体兼容 |
| 重新开始死路 | 注册表只认 `[...]` | 纯文本别名映射 |
| 侧栏收不回 | 收起按钮随栏消失 | 悬浮 ☰ 展开按钮 |
| 代码浏览点击无反应 | 浏览器新旧缓存混搭 | no-cache 中间件 |
| 宽屏按钮点不动 | layout-toggle 悬浮胶囊遮挡 | tutor 模式隐藏胶囊，侧栏按钮替代 |
| 宽屏还原 NaNpx | `a \|\| b ? c : d` 运算符优先级 | 显式分支 |
| 片段消息全文糊屏 | 旧格式正则过严 | SNIPPET_RE 容错（围栏换行/前缀可缺） |
| 片段代码换行被吞 | 输入框是单行 `<input>`，赋值 `\n` 被 HTML 规范剥掉，历史片段消息全被压成一行 | 输入框改 `<textarea rows=1>` + Enter 发送/Shift+Enter 换行（`isComposing` 防输入法误发）+ 自动增高 ≤160px |
| 流式回复"截断"（句中断） | 节流渲染竞态：done 终渲染后，迟到的 200ms 节流定时器用**调度时旧快照**回退气泡内容；后端其实已完整落盘（刷新即恢复） | 节流触发时渲染挂在 bubble 上的最新文本（`_pendingText`），message/done 事件先 `cancelThrottledRender()` |
| 向导按钮触发空指针 | 「扫描预览」复用了 `.cfg-test` 样式类，被模型配置的全局委托 handler 接住，`data-section` 为空 → `getElementById("test-undefined")` = null | cfg-test 委托加 `#provider-sections` 作用域守卫（样式类与行为钩子分离的教训） |
| 25 天 Study.md 初始化必失败 | LLM 默认 max_tokens=4096，25 天计划需 5-6k token，输出截断在 Day 19 左右 → 校验缺 Day 20-24 | 初始化生成走 `init_max_tokens`（settings 可配，默认 8192 = DeepSeek 输出硬顶） |
| opencode 401 | 账号被上游风控（非程序问题） | fallback 到 DeepSeek 官方 |

## UI 版本

- **v4（2026-07-22）**：多工作区通用化 —— 顶栏工作区下拉（切换/新建/重新扫描），初始化向导（表单→扫描预览→LLM 生成→验证管线→自动切换），品牌与代码根随工作区隔离。走查 46 项全绿。
- **v3（2026-07-22）**：双模式重构 —— 「知识学习」暖纸书房风（米白 #f5f0e6 + 赭石 #bc6c3b + 衬线标题 + 深棕侧栏）；「源码学习」IDE 风（#1e1e1e 编辑器底 + #0e86d8 状态蓝 + 标签页文件头 + 底部状态栏）。三区分离布局：侧栏纯仪表盘（单元改状态圆点、同步计数并为一行）、顶栏分段模式控件 + 工具图标、输入框上方指令胶囊条 + `[` 补全菜单。移除：深色切换按钮、layout-toggle 悬浮胶囊、面板宽屏/拖拽。
- **v2（2026-07-22）**：整体视觉打磨 —— 靛蓝品牌色系 + 渐变强调、侧栏分区卡片化、聊天气泡居中栏（≤880px）+ 渐变用户泡、悬浮胶囊输入条、全局滚动条/选区/焦点环样式、表格斑马纹、代码复制按钮悬停显现。
- 走查脚本 v2 起**自包含**——真实发送片段提问验证卡片渲染+流式+刷新回填，结束时自动 `POST /api/session/reset` 清理测试消息。

## 待办 / 已知边界

- opencode 解封后自动回主渠道，无需操作
- Study.md 需当日 `## Day N |` 细化小节才能 start_day（Day 3+ 还是路线图格式，需 CLI 助手先细化）
- 复盘题量靠 prompt 约束；编码启动模板由 LLM 填充；仓库校验简化
- v1 未做：模拟面试模式、论文联网检索、多用户、桌面打包

## 上下文恢复指引（新会话）

1. 读本文件 + `AGENTS.md` + `docs/InteractionModel.md`；接开发任务再读 `docs/Roadmap.md`
2. 跑 `python -m unittest discover -s tests` 与 `python resources/hooks/validate_study.py ../docx 25 ragent-replica` 确认基线
3. 服务若在跑（8765）：`python scripts/ui_walkthrough.py` 全量 UI 走查
4. 前端改动后必须 Playwright 点击走查再交付；提交走分支 + 三件套全绿

