# Roadmap — 通用编程项目学习助手（改进路线）

> 目标：让 study-web 成为**任意编程项目**的学习助手。
> 本文档持久化 2026-07-22 的短板分析与优先级路线，作为后续开发的需求源。

## 核心缺口诊断

| # | 缺口 | 症状/影响 |
|---|------|----------|
| 1 | **AI 导学看不到代码内容** ⭐ | prompt 只有 Project.md 结构，导师讲源码靠想象 → 虚构类名/路径（AgentPromptConfig 事件的根因）。引用芯片只解决了"人能点"，AI 自己不能读 |
| 2 | **学习无反馈闭环** | 编码写完不能运行/测试/diff；卡壳疑问记录后无间隔复习；掌握度全靠 LLM 自评 |
| 3 | **教学形态单一** | 纯文字，无架构图/时序图（Mermaid 即可解决） |
| 4 | **流程对 Ragent 过度拟合** | replica 复现对大项目不现实；论文阶段对多数项目无对应论文；单元"文档"字段假设有外部教程（通用项目只有代码） |
| 5 | **初始化浅且脆** | 扫描仅 3 层树+构建文件，无入口/依赖分析；25 天计划一次性生成慢易截断、不随项目演进；Study.md 引用路径无存在性校验 |
| 6 | **工程边界** | 单进程全局 deps（多标签页互相污染）；无桌面打包；工作区无删除/归档 |

## P0 — 教学真实性（先做，① 是违和感根源）

- [x] **P0-1 AI 读文件 tool-use 闭环**（2026-07-22 完成）：导师输出 `[READ:路径:L起-止]`（独立一行）→ `engine/tool_use.ToolUseLoop` 行缓冲截获 → code_browser 只读注入真实代码 → 续写。限 3 次/回复（超限静默丢弃）、单次注入 ≤200 行；SSE 新事件 `tool_read`，前端渲染可点击 chip（跳转代码浏览器行高亮）；标记与注入内容均不进 chat_history
- [x] **P0-2 Mermaid 图渲染**（2026-07-22 完成）：vendor mermaid@11（`frontend/vendor/mermaid.min.js`），```mermaid 块终渲染为 SVG，主题随布局（pair=dark/tutor=default），渲染失败回退代码块；prompt 硬约束第 8 条引导导师画图
- [x] **P0-3 Study.md 路径存在性校验**（2026-07-22 完成）：`study_plan.check_unit_docs`——细化单元「文档」字段中的路径形 token 必须在 project_dir 存在（文件/目录均可），初始化与滚动细化两处校验管线均接入，失败带错重试

## P1 — 学习闭环

- [x] **P1-1 编码验证闭环**（2026-07-22 完成）：新指令 `[验证代码]`（第 11 个指令）——验证根=replica 目录否则 project_dir，`code_runner` 固定命令模板跑 Maven/Gradle/npm 编译（args 含"测试"跑测试），`verify_timeout`(300s)/`verify_offline` 可配，结果+日志尾部回喂 AI 点评；真实 mvn compile 冒烟通过（167s ✅）
- [x] **P1-2 增量式 Study.md**（2026-07-22 完成）：初始化只生成全量粗纲 + 前 `init_detail_days`（默认 3）天细化；`[结束今日学习]` 滚动细化次日（`resources/prompts/detail_day_md.md`，注入昨日 StudyMemory 反馈 + Project.md 防虚构，失败重试 1 次保留粗纲不阻塞）；`study_plan.replace_day_section` 拼入；已细化工作区自动跳过
- [x] **P1-3 间隔复习机制**（2026-07-22 完成）：`services/review_scheduler.collect_due` 按 `review_intervals`（默认 1/3/7 天）采集历史卡壳/待解答疑问/<3 分单元，`[开始今日学习]` Step 1「将优先安排」展示 + LLM 指令前缀（开场前 ≤5 分钟逐条回顾）

## P2 — 形态与分发

- [ ] **P2-1 桌面打包**（用户决定暂缓）：Tauri 需 Rust 工具链（本机无），PyInstaller+pywebview 为备选路线，待用户重启此项时定夺
- [x] **P2-2 初始化深度**（2026-07-22 完成）：扫描画像新增——入口识别（SpringBoot 启动类/脚本入口，深 10 层 + 2 万文件预算）、模块依赖线索（构建文件交叉引用）、关键配置（application*.yml/properties 头部）
- [x] **P2-3 流程阶段可配置**（2026-07-22 完成）：`resources/presets/{default,reading,bugfix,article}.toml`，工作区 `preset` 字段覆盖全局 stages；初始化向导「学习模式」下拉；未知预设回退全局
- [x] **P2-4 工作区管理**（2026-07-22 完成）：删除（禁删激活；默认保留磁盘数据，delete_data 仅允许删 study-web/workspaces 内目录）+ 导出（docx zip 下载）；`ConfigService.path` 注入取代全局 SETTINGS_PATH（测试可注入临时配置）

## 实施备忘

- ①② 互不阻塞（一后端一前端），可打包做；做完学习体验质变
- P0-1 是最大工程点：涉及 SSE 流式协议变更（新事件类型 + 中断续流），改前必读 `docs/InteractionModel.md` 与 bug 史中流式相关条目
- 所有新文档类型/提示词仍走 `resources/` 外置原则
