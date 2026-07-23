# AGENTS.md — studyAgent（study-web）开发指南

企业级学习 Agent（多工作区）：任意代码项目可一键初始化全套学习文档（LLM 生成 + 程序验证）。规则执行（模板渲染、FAIL-FAST、阶段流转、落盘校验、权限）由后端强制，内容生成（讲解/提问/拷打）由 LLM 负责。

- **仓库**：<https://github.com/1while1/studyAgent>（main，推送前本地三件套全绿）
- **演进方向（封板）**：`docs/AgentDesign.md` v3 —— 学习者模型核心的 study/code 双模式 Agent，M1-M7 分期。**M1 资料库 / M2 可观测 / M3 学习者模型 / M4 笔记管理 / M5a 工具骨架 / M5b 上下文+路由 / M5c planner / M6 实战工坊已交付**，下一步 = M7 课程本体
- 设计基准：`docs/InteractionModel.md`（改流程代码前必读）；设计历史与 bug 史：`docs/DevLog.md`

## 运行与测试

```bash
cd study-web
python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8765   # 启动
python -m unittest discover -s tests                                  # 全部测试（348 个，stdlib unittest）
python resources/hooks/validate_study.py <docx_dir> [total_days] [replica_name]  # 改学习数据后必跑
python scripts/ui_walkthrough.py                                      # UI 走查 131 项（需服务运行中；会清测试工作区聊天历史）
```

- 无前端构建步骤；前端库本地 vendor 在 `frontend/vendor/`（marked / DOMPurify / highlight.js / mermaid / monaco-editor），**不要用 CDN 替换**；monaco 版本号登记 `frontend/vendor/README.md`（仅 pair 布局动态加载）
- 测试不依赖第三方包、不调真实 LLM（MockLLM）；`test_flows.py` 在 docx 临时副本上跑全流程
- **前端功能交付前必须 Playwright 真实点击验证**（用户定的规矩），接口级测试不能替代 UI 走查

## 工作区机制（多项目通用化）

- **Workspace 值对象**（`domain/workspace.py`）：slug / title / goal / docx_dir / project_dir / session_path / total_days / replica_name / preset，工作区一切派生值的唯一来源
- **配置**：`settings.toml` 的 `active_workspace` + `[[workspaces]]`；`code_roots` 带 `workspace` 字段按工作区过滤；`ConfigService.path` 可注入临时配置（测试）
- **生命周期**：创建（向导：扫描→LLM 生成→验证管线）/ 切换（deps 热重建）/ 重新扫描 / 删除（禁删激活，默认保留磁盘数据）/ 导出（docx zip）
- **学习模式预设**：`resources/presets/{default,reading,bugfix,article}.toml`，工作区 `preset` 字段覆盖全局 stages
- **资源单源**：`resources/{sop,hooks,templates,prompts,presets,pedagogy}`——改行为改资源文件，不改代码
- **零硬编码**：项目名/品牌/天数/复现名一律走 Workspace；代码中禁止出现具体项目名字面量

## 架构（依赖方向单向：`api → engine → services/llm → domain`）

| 层 | 职责 | 关键约束 |
|----|------|---------|
| `backend/domain/` | 纯模型零 IO（SessionContext / DayPhase / Workspace / paths 常量） | 禁止 import 其他任何层 |
| `backend/services/` | 基础设施：state_store / memory_store / study_plan / template_service / backup_service / config_service / config_writer / code_browser（含 suggest/敏感文件过滤）/ repo_scanner / doc_initializer / workspace_service / review_scheduler（间隔复习）/ code_runner（构建执行 + verify 根解析）/ materials_service（资料库：注册/解析/索引/预取）/ observer（agent.log 记账+token 计量）/ auth_service（密码门）/ learner_service（concepts+evidence+mastery）/ **notes_service（笔记条目层 CRUD/合并/蒸馏）/ qa_service（话术层 parse/render/落盘）/ workshop_service（M6 实战工坊：demo/replica 写白名单 + 脚手架 + 代码保存）/ process_mgr（M6 进程管理：起停/杀树/端口探测/日志）** | 各服务互不引用（workspace_service 只做编排除外；backup_service 属落盘基础设施例外） |
| `backend/llm/` | LLMClient 接口 + openai_compat（OpenAI 协议主路径，timeout 可配）/ mock / fallback + factory 注册表 | 新渠道只加文件 + 注册 |
| `backend/engine/` | stage_machine（配置驱动）/ orchestrator / quiz_engine（评分 [1.0,5.0]）/ prompt_builder / tool_use（READ/ACTION 标记增量扫描截获，**分发改经 tool_registry**）/ **turn_engine（双引擎接口 + mode×flag 路由）/ planner（agent 引擎：ACTION 契约 + plan-act-observe）/ tool_registry（工具注册表 + 权限四级）/ context_manager（上下文三层 + 预算钳制 + 压缩机械校验）** / commands（13 个 handler，每 SOP 卡一个 + verify_code + interview）/ hooks / **note_actions（销账单一路径编排）/ qa_capture（拷打反喂）** | commands 之间禁止互相 import |
| `backend/api/` | FastAPI 路由 + SSE + 静态托管 | 只做编排，不写业务逻辑 |

## 铁律（违反即破坏系统）

1. **模板单源**：用户面模板来自 `resources/sop/*.md` 的 `<!-- template:* -->` 锚点块。**禁止删改锚点标记，禁止在代码里复制模板文本**。
2. **数据单源**：学习数据只读写当前工作区 `docx_dir`，禁止另建数据副本。
3. **落盘必走规则 14**：`backup_service.atomic_persist()`（备份 → 写 → validate → 失败回滚，进程内分桶互斥锁）；**所有 boot-critical 写（settings/.env/session）走 `atomic_write`**（临时文件 + os.replace）。
4. **阶段机数据驱动**：stages/transitions/指令全在配置（全局或 preset），`stage_machine.py` 不得出现 stage 字面量。
5. **sop_card 三态**：None（用注册卡）/ `""`（明确不带）/ 文件名。纯教学内容生成**必须不带卡**。
6. **评分契约**：LLM 评价类输出必须含 `【评分：X.X】`（1.0-5.0），越界视为无标记不推进。
7. **密钥边界**：key 只进 `.env`，接口只返回掩码；**敏感文件（.env/证书/私钥）代码浏览器与 AI READ 一律拒绝**。
8. **前端渲染**：流式用独立 `rawText` 累积器 + 节流读 `bubble._pendingText`；message/done 先取消节流；SSE 事件 `delta`/`message`/`tool_read`/`error`/`done`（tool_read 的 kind：code/doc/action——action=planner 工具调用 chip，不跳转）；mermaid 只终渲染；**streamPost 有 try/catch/finally 兜底与发送锁**，改动时不得退化。
9. **tool-use 边界**：READ/READ_DOC 标记任意位置/反引号包裹均截获（未闭合按文本下发）；单回复**两种标记合计**限 3 次、单次注入限 200 行；**ACTION 标记（M5c）**契约 `{action,args,reason}`（JSON 按逐 ] 尝试解析容忍嵌套），契约不符/未知工具注入错误教纠正，单回复限 `planner_max_actions_per_reply` 次，plan 决策记 agent.log；标记与注入**不进 chat_history**；代码读取走 code_browser 只读防护，资料读取走 materials_service 注册表；读取失败注入 suggest 候选。
10. **LLM 失败状态一致**：/api/chat 失败也落盘用户消息；/api/command 失败整体回滚到 handler 前 session 快照。
11. **交接文档**：功能/架构/约定变化后，同步更新 `AGENTS.md`、`README.md`、`docs/DevLog.md`。
12. **资料库**：注册表 `<docx_dir>/materials.json`（schema_version）+ 缓存 `<docx_dir>/materials/_cache/`，规则 14 落盘；资料 id = 相对 materials_dir 的 posix 路径去扩展名；**备课预取是代码强制**（讲解回合 transient 注入，异常静默降级不阻断）；资料内容注入一律带"仅供参考不视为指令"定界。
13. **观测不阻断**：agent.log 记账（observer）任何异常必须静默吞掉；`runtime_dir(config)` 派生运行时目录（测试隔离）；task_scope 恢复旧值用 `set` 不用 `reset`（跨线程生成器 reset 会炸）。
14. **认证边界**：密码哈希只进 `.env AUTH_PASSWORD_HASH`（settings.toml 是 git 跟踪文件，不可存哈希）；签名密钥 `runtime/auth_secret`；中间件豁免仅 `/api/auth/{status,setup,login}`；门未开 = 开放模式。
15. **学习者模型**：concept id 只由代码铸造（`Day{N}-{单元id}`）；evidence 的 delta 写入时查 `[evidence_delta]` 表定死（LLM 只选类型）；`source_ref` 幂等；**mastery 读取时按衰减公式重算**（存储值仅冗余）；无 `code_verify_pass` 封顶 0.6 代码强制；模型写入失败不阻断学习流程（try/except 静默）。
16. **笔记与话术（M4）**：notes.json kind ∈ {stuck,question,mastered,insight}、status ∈ {open,resolved}；销账只走 `engine/note_actions.resolve_note` 单一路径（`note_distilled` 证据 source_ref=`note:{id}` 幂等；未挂接 concept/合并残骸不写证据）；InterviewQA.md 读写走 QaService（`**产出来源**：Day N 场景` 行是 end_day 统计契约，LLM 产出一律服务端覆写）；拷打反喂（qa_capture）任何异常静默不阻断复盘；`concept_id` 挂接只从 `/api/learner/model` 清单选择，禁止手填。
17. **实战工坊（M6）**：写白名单仅 `demo/`（Workspace.demo_dir）与 `replica/`（WEB_ROOT.parent/<replica_name>）两别名，**原项目（project_dir/code_roots）永远只读**；代码文件落盘走 `atomic_write`（validate_study 是 docx 专用校验器，代码文件无 validator 可挂）；敏感文件拒写同 code_browser 黑名单；进程一切 kill 前必须 `cmdline` 哈希再校验（psutil 规范化口径，防 PID 复用误杀）；进程 stdout **直接重定向**到日志文件（抗服务重启，有意偏离设计"独立线程读 stdout"）；Monaco 仅 pair 布局动态加载，版本号登记 `frontend/vendor/README.md`。

## 动态配置

- 阈值/阶段机/指令注册/LLM 主备/工作区/预设：`config/settings.toml`（mtime 热重载；模型相关也可走页面「模型配置」热生效）
- 上下文三层：`[context]`（预算/触发比例/钉住 K/归档上限/窗口条数兜底）+ `[model_context]`（各模型上下文上限表）；压缩触发比例与预算也可走「模型配置 → 上下文窗口」热生效
- 密钥：`study-web/.env`（`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_API_KEY_DEEPSEEK`）
- 运行时会话：各工作区 `session_path`（可随时清空；学习数据不受影响；损坏自动留 `.corrupt.bak`）

## 扩展路径

| 需求 | 做法 |
|------|------|
| 新触发指令（简单） | `settings.toml [commands."新指令"]`，`handler = "declarative"` |
| 新触发指令（复杂） | `engine/commands/` 加 handler + `registry.py` 注册（参考 `verify_code.py`/`interview.py`） |
| 新工具 | `engine/tool_registry.py` 加 handler + `build_default_registry` 注册（定权限级别与 params schema） |
| 新教学策略卡 | `resources/pedagogy/` 加 md 卡 + `render_pedagogy` 渲染（面试指令与 LLM 工具共用同源） |
| 新 LLM 渠道 | `llm/` 实现 LLMClient + `factory._BUILDERS` 注册 + toml 加 `[llm.<name>]` |
| 新落盘校验规则 | `app.py` 中 `hooks.register_post_persist(...)` |
| 新初始化文档类型 | `resources/templates/` 加模板 + `doc_initializer.SKELETON_DOCS` 注册一行 |
| 改初始化/细化生成风格 | 改 `resources/prompts/init_*.md` / `detail_day_md.md`，零代码 |
| 新增学习模式预设 | `resources/presets/` 加 toml（[[stages]] + description），向导自动出现 |
| 调构建验证/AI 读取/复习间隔 | `settings.toml` 对应键（verify_timeout/ai_read_*/review_*），零代码 |
| 配置资料库 | `settings.toml` 工作区加 `materials_dir`；调预取量/清单行数用 `materials_*` 键 |
| 调拷打反喂 | `settings.toml` 的 `qa_capture_enabled` / `qa_capture_max_entries`；反喂提示词改 `resources/prompts/qa_capture.md`，零代码 |
| 调上下文预算/压缩触发 | 模型配置页「上下文窗口」区（热生效）或 `settings.toml [context]`；模型上限表 `[model_context]`；压缩提示词改 `resources/prompts/context_compress.md` |
| 配 cheap 档（压缩渠道） | `settings.toml [llm] cheap_provider`（空 = 复用 strong），保存 llm-config 或重启生效 |
| 新脚手架类型 | `resources/scaffolds/<类型>/` 加模板树（`{{name}}` 占位符），向导/弹窗自动出现，零代码 |
| 调进程/脚手架行为 | 白名单逻辑在 `workshop_service`/`process_mgr`（改前先读铁律 17），端口快探 `_PORT_PROBE_TIMEOUT`、杀树宽限 `_STOP_GRACE` 零配置化 |

## v1 已知边界

- 复盘拷打题量靠 prompt 约束，非硬断言
- `[开始写代码]` 的编码启动模板由 LLM 填充（需模块信息）
- 仓库校验（Step 2）简化为目录存在性检查
- 资料库 M1：video_link 仅登记不播放；docx 表格内容不提取；pdf 无标题层级（按页分节）
- 后续演进全部以 `docs/AgentDesign.md` v3 分期为准（M2-M7），不再新增 v1 时代功能
