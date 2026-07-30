# studyAgent 架构详解

## 分层架构

```
api → engine → services/llm → domain
```

依赖方向**单向**，禁止反向引用。`domain` 层禁止 import 任何其他层。

## 各层模块职责

### api/ — 编排层

只做 HTTP 编排，不写业务逻辑。

| 文件 | 职责 |
|------|------|
| `app.py` | FastAPI 应用入口 + 生命周期（startup/shutdown）+ 静态文件托管 + `include_router` 注册 |
| `routes.py` | 核心 SSE 路由（`/api/chat`、`/api/command`） |
| `middleware.py` | `auth_gate` 中间件 + CORS 配置 |
| `workspace_routes.py` | 工作区 CRUD、切换、重新扫描、导出、会话管理 |
| `learner_routes.py` | 学习者模型（concepts/evidence/mastery）、笔记 CRUD、话术（InterviewQA） |
| `code_routes.py` | 代码浏览器（目录树 + 文件读取 + suggest） |
| `auth_routes.py` | 认证（登录/登出/状态/初始化密码） |
| `llm_config_routes.py` | 模型配置热生效 + 可观测数据（token 计量/agent.log） |
| `upload_routes.py` | 文件上传路由（POST /api/upload + GET /uploads/） |
| `security_headers.py` | 安全响应头（CSP / X-Frame-Options / X-Content-Type-Options） |

### engine/ — 引擎层

核心业务引擎，commands 之间禁止互相 import。

| 文件/目录 | 职责 |
|-----------|------|
| `orchestrator.py` | `ChatOrchestrator`：chat 编排入口，协调阶段机 + 引擎 + 上下文 |
| `phases/` | 阶段策略（PhaseRegistry 双轴分发，按优先级匹配） |
| `commands/` | 指令处理器（每 SOP 卡一个 + verify_code + interview） |
| `turn_engine.py` | 双引擎接口 + mode×flag 路由（study/code 模式分发） |
| `planner.py` | Agent 引擎：ACTION 契约 + plan-act-observe 循环 |
| `tool_registry.py` | 工具注册表（权限四级：READONLY / WRITE / SANDBOX / LLM） |
| `context_manager.py` | 上下文三层（recent/pinned/archived）+ 预算钳制 + 压缩机械校验 |
| `stage_machine.py` | 配置驱动阶段机（禁止 stage 字面量，铁律 4） |
| `quiz_engine.py` | 评分引擎（`【评分：X.X】` 契约，1.0-5.0，铁律 6） |
| `prompt_builder.py` | Prompt 构建（系统提示 + 上下文组装） |
| `tool_use.py` | READ/READ_DOC/ACTION 标记截获与分发 |
| `note_actions.py` | 笔记销账编排（`resolve_note` 单一路径，铁律 16） |
| `qa_capture.py` | 拷打反喂（异常静默不阻断，铁律 16） |
| `teaching_strategy.py` | 教学行动策略库（7 行动 + suggest_action 规则引擎） |
| `session_store.py` | 会话 JSON 读写（损坏自动 `.corrupt.bak`） |
| `hooks/` | 后置钩子（`pipeline.py` + `validate_hook.py`，落盘后校验） |

#### phases/ — 阶段策略详情

| 文件 | 策略类 | 匹配条件 |
|------|--------|---------|
| `base.py` | `PhaseHandler`（ABC） | — |
| `ended.py` | `EndedPhase` | 学习已结束 |
| `prereq.py` | `PrereqPhase` | 先修诊断（同日幂等） |
| `interview.py` | `InterviewPhase` | 面试/访谈阶段 |
| `reviewing.py` | `ReviewingPhase` | 复盘阶段 |
| `quiz_r1.py` | `QuizR1Phase` | 第一轮测验 |
| `quiz_r2.py` | `QuizR2Phase` | 第二轮测验 |
| `studying.py` | `StudyingPhase` | 学习中（暂未注册，回合计数仍在 orchestrator） |
| `__init__.py` | `PhaseRegistry` + `build_registry()` | 按优先级注册分发 |

注册优先级：Ended → Prereq → Interview → Reviewing → QuizR1 → QuizR2

#### commands/ — 指令处理器详情

| 文件 | Handler 类 | 触发指令 |
|------|-----------|---------|
| `base.py` | `CommandHandler`（ABC） | — |
| `start_day.py` | `StartDayHandler` | `[开始今日学习]` |
| `resume.py` | `ResumeHandler` | `[恢复学习]` |
| `next_content.py` | `NextContentHandler` | `[下一内容]` |
| `sync.py` | `SyncHandler` | `[同步]` |
| `code_mode.py` | `CodeModeHandler` | `[开始写代码]` |
| `day_review.py` | `DayReviewHandler` | `[开始今日复盘]` |
| `end_day.py` | `EndDayHandler` | `[结束今日学习]` |
| `jump_day.py` | `JumpDayHandler` | `[跳到第N天]` |
| `verify_code.py` | `VerifyCodeHandler` | `[验证代码]` |
| `interview.py` | `InterviewHandler` | `[开始拷打]` |
| `prereq.py` | `PrereqHandler` | 先修诊断 |
| `declarative.py` | `DeclarativeHandler` | 声明式指令（零代码） |
| `registry.py` | `CommandRegistry` | 触发词 → handler 映射 + 纯文本别名 |
| `slash.py` | — | `/` 斜杠指令解析 |

### services/ — 基础设施层

各服务互不引用（`workspace_service` 只做编排除外；`backup_service` 属落盘基础设施例外）。

| 文件 | 职责 |
|------|------|
| `state_store.py` | 学习状态 JSON 读写 |
| `memory_store.py` | 记忆（chat_history）读写 |
| `study_plan.py` | 学习计划生成与管理 |
| `template_service.py` | SOP 模板渲染（`resources/sop/*.md` 锚点块） |
| `backup_service.py` | 备份 + `atomic_persist`（规则 14：备份→写→validate→失败回滚） |
| `config_service.py` | 配置热重载（`settings.toml` mtime 监听） |
| `config_writer.py` | 配置写入（四函数共用进程内 RLock，铁律 17） |
| `code_browser.py` | 代码只读浏览（含 suggest 候选 + 敏感文件过滤） |
| `repo_scanner.py` | 项目目录扫描 |
| `doc_initializer.py` | 学习文档骨架初始化（`SKELETON_DOCS` 注册） |
| `workspace_service.py` | 工作区管理（创建/切换/删除/导出，唯一允许编排多服务的例外） |
| `workshop_service.py` | 实战工坊（demo/replica 写白名单 + 脚手架 + 代码保存，铁律 17） |
| `process_mgr.py` | 进程管理（起停/杀树/端口探测/日志，kill 前 cmdline 哈希校验） |
| `materials_service.py` | 资料库（注册/解析/索引/备课预取，`materials.json` + `_cache/`） |
| `review_scheduler.py` | 间隔复习调度 |
| `code_runner.py` | 构建执行 + verify 根解析 |
| `observer.py` | `agent.log` 记账 + token 计量（异常静默吞掉，铁律 13） |
| `learner_service.py` | 学习者模型（concepts + evidence + mastery 衰减重算 + 图谱方法） |
| `notes_service.py` | 笔记管理（CRUD / 合并 / 蒸馏，kind ∈ {stuck,question,mastered,insight}） |
| `qa_service.py` | 话术服务（InterviewQA.md 读写 + parse/render/落盘） |
| `auth_service.py` | 认证（bcrypt 密码哈希，铁律 14） |
| `repository.py` | 存储仓库抽象（Repository 接口 + JsonRepository） |
| `auth_provider.py` | 认证提供者接口（AuthProvider + LocalAuthProvider） |
| `log_analyzer.py` | 日志分析器（结构化查询/统计 + /api/logs 端点） |
| `mcp_client_service.py` | MCP Client（MCPClientPool + JSON-RPC 2.0 stdio + 命令白名单） |
| `plugin_service.py` | Plugin 系统（PluginSpec + PluginRegistry + entry_points 扫描） |
| `upload_service.py` | 文件上传（类型/大小校验 + 存储） |
| `vision_service.py` | 图片分析（base64/路径输入 + LLM Vision API） |
| `web_search_service.py` | Web 搜索（DuckDuckGoProvider + 缓存） |

### llm/ — LLM 层

新渠道只加文件 + 注册。

| 文件 | 职责 |
|------|------|
| `base.py` | `LLMClient` 接口定义 |
| `openai_compat.py` | OpenAI 协议主路径（timeout 可配） |
| `mock.py` | `MockLLM`（测试用，不调真实 LLM） |
| `fallback.py` | 降级策略（主渠道失败切换备用） |
| `factory.py` | 工厂注册表（`_BUILDERS` 字典，按名挂载） |
| `observed.py` | 观测包装（装饰器模式，接入 observer 记账） |

### domain/ — 纯模型层（零 IO）

禁止 import 其他任何层。

| 文件 | 职责 |
|------|------|
| `enums.py` | `DayPhase` 枚举（学习阶段状态） |
| `models.py` | `SessionContext` 等核心数据模型 |
| `workspace.py` | `Workspace` 值对象（slug/title/goal/docx_dir/project_dir 等，工作区唯一来源） |
| `paths.py` | 路径常量（runtime_dir 等） |
| `learner.py` | 学习者模型数据（Concept / Evidence / Mastery） |
| `sensitive.py` | 敏感文件过滤黑名单（.env/证书/私钥，铁律 7） |
| `error_pattern.py` | 错误模式分类（5 大类枚举 + 提取逻辑） |
| `learning_metrics.py` | 学习效果度量（BKT + FSRS + 三指标组合） |

## 前端结构

| 文件 | 职责 |
|------|------|
| `index.html` | 主页面 |
| `app.js` | 主逻辑（SSE 流式渲染 + 路由 + 状态管理） |
| `markdown.js` | Markdown 渲染（marked + DOMPurify + highlight.js + mermaid） |
| `code-browser.js` | 代码浏览器页面 |
| `viewer.js` | 文档查看器 |
| `workspace-mgr.js` | 工作区管理 UI |
| `mastery.js` | 学习者模型可视化 |
| `notes-page.js` | 笔记管理页面 |
| `process-mgr.js` | 进程管理 UI（M6 实战工坊） |
| `llm-config.js` | 模型配置 UI |
| `style.css` | 全局样式 |
| `usage.html` / `usage.js` | 使用说明页面 |
| `vendor/` | 前端库本地（marked / DOMPurify / highlight.js / mermaid / monaco-editor） |

## 资源目录

| 目录 | 用途 |
|------|------|
| `resources/sop/` | SOP 模板（`<!-- template:* -->` 锚点块，铁律 1） |
| `resources/templates/` | 文档骨架模板（`doc_initializer.SKELETON_DOCS` 注册） |
| `resources/prompts/` | LLM 提示词（init / detail_day / context_compress / qa_capture） |
| `resources/presets/` | 学习模式预设（default / reading / bugfix / article） |
| `resources/pedagogy/` | 教学策略卡（面试指令与 LLM 工具共用同源） |
| `resources/scaffolds/` | 脚手架模板树（`{{name}}` 占位符，gradle / maven-module / npm） |
| `resources/hooks/` | 落盘后校验钩子（`validate_study.py`） |

## 数据流

```
用户输入
  → api/routes.py（SSE 端点）
    → engine/orchestrator.py（编排）
      → engine/commands/（指令匹配 → handler 处理）
      → engine/phases/（阶段策略 → instruction_for）
      → engine/turn_engine.py（双引擎路由）
        → engine/planner.py（ACTION 循环）
        → engine/tool_use.py（标记截获）
          → engine/tool_registry.py（工具分发）
      → engine/context_manager.py（上下文组装）
      → llm/（LLM 调用）
      → services/（状态/模板/资料/观测）
    → backup_service.atomic_persist（落盘）
  → SSE 响应（delta/message/tool_read/error/done）
```
