# AGENTS.md — study-web 开发指南

通用 AI 学习助手 Web 版（多工作区）：任意代码项目可一键初始化全套学习文档（LLM 生成 + 程序验证），每个工作区绑定一个目标项目。规则执行（模板渲染、FAIL-FAST、阶段流转、落盘校验）由后端强制，内容生成（讲解/提问/拷打）由 LLM 负责。

设计基准：`docs/InteractionModel.md`（改流程代码前必读）。

## 运行与测试

```bash
cd study-web
python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8765   # 启动
python -m unittest discover -s tests                                  # 全部测试（stdlib unittest）
python resources/hooks/validate_study.py <docx_dir> [total_days] [replica_name]  # 改学习数据后必跑
```

- 无前端构建步骤；前端库本地 vendor 在 `frontend/vendor/`（marked / DOMPurify / highlight.js），**不要用 CDN 替换**
- 测试不依赖第三方包、不调真实 LLM（MockLLM）；`test_flows.py` 在 docx 临时副本上跑全流程
- **前端功能交付前必须用 Playwright（pip 包已装）无头浏览器做真实点击验证**：标准走查脚本 `python scripts/ui_walkthrough.py`（需服务运行中），前端交付前必跑。接口级测试不能替代 UI 走查

## 工作区机制（多项目通用化）

- **Workspace 值对象**（`domain/workspace.py`）：slug / title / goal / docx_dir / project_dir / session_path / total_days / replica_name，是工作区一切派生值的唯一来源
- **配置**：`settings.toml` 的 `active_workspace` + `[[workspaces]]`；无该节时由旧顶层键合成默认工作区（向后兼容）。`code_roots` 带 `workspace` 字段按工作区过滤
- **切换/创建**：`POST /api/workspaces/switch|create|rescan` → 写 settings → `app.assemble()` 重建 deps 热切换；聊天会话随工作区隔离（各自 session_path）
- **初始化**：`workspace_service.create`（编排）→ `repo_scanner.scan`（纯函数画像）→ `doc_initializer`（骨架模板渲染 + LLM 生成 Project.md/Study.md + 验证管线逐天 parse 校验，失败带错重试 1 次不过不写盘）
- **资源单源**：`resources/sop/`（SOP 卡）、`resources/hooks/validate_study.py`、`resources/templates/`（初始化骨架）、`resources/prompts/`（LLM 生成提示词）——改行为改资源文件，不改代码
- **零硬编码**：项目名/品牌/天数/复现名一律走 Workspace；代码中禁止出现具体项目名字面量

## 架构（依赖方向单向：`api → engine → services/llm → domain`）

| 层 | 职责 | 关键约束 |
|----|------|---------|
| `backend/domain/` | 纯模型零 IO（SessionContext / DayPhase / QuizMode / Workspace / paths 常量） | 禁止 import 其他任何层 |
| `backend/services/` | 基础设施：state_store / memory_store / study_plan / template_service / backup_service / config_service / config_writer / code_browser / repo_scanner / doc_initializer / workspace_service / review_scheduler（间隔复习采集） | 各服务互不引用（workspace_service 只做编排除外） |
| `backend/llm/` | LLMClient 接口 + openai_compat / mock / fallback + factory 注册表 | 新渠道只加文件 + 注册 |
| `backend/engine/` | stage_machine（配置驱动）/ orchestrator（聊天阶段驱动）/ quiz_engine（评分提取）/ prompt_builder / tool_use（AI 读文件 READ 标记截获+注入续写）/ commands（每 SOP 卡一个 handler）/ hooks（注册式钩子链） | commands 之间禁止互相 import |
| `backend/api/` | FastAPI 路由 + SSE + 静态托管 | 只做编排，不写业务逻辑 |

## 铁律（违反即破坏系统）

1. **模板单源**：所有用户面模板来自 `resources/sop/*.md` 的 `<!-- template:* -->` 锚点块，由 `template_service` 解析。**禁止删改锚点标记，禁止在代码里复制模板文本**。改模板措辞 = 改 SOP 卡。
2. **数据单源**：学习数据只读写当前工作区的 `docx_dir`（StudyState.json / StudyMemory / Study.md / InterviewQA / StudyReview），禁止另建数据副本。
3. **落盘必走规则 14**：`backup_service.atomic_persist()`（备份 → 写 → `validate_study.py` → 失败回滚），禁止直接 `path.write_text` 改学习数据文件（初始化全新工作区除外）。
4. **阶段机数据驱动**：stages/transitions/各阶段给 LLM 的指令全部在 `config/settings.toml`，`stage_machine.py` 不得出现 stage 字面量。
5. **sop_card 三态**：`CommandResult.sop_card` = None（用注册卡）/ `""`（明确不带）/ 文件名。纯教学内容生成（讲解开场等）**必须不带卡**——带卡会导致模型复读卡片模板。
6. **评分契约**：LLM 评价类输出必须含 `【评分：X.X】`，由 `quiz_engine.SCORE_RE` 提取（兼容加粗/半角冒号/带"分"字变体）；无标记不推进。
7. **密钥边界**：key 只进 `.env`（经 `config_writer.update_env_file`），接口只返回掩码（前 4 后 4），禁止日志/响应回显完整 key。
8. **前端渲染**：流式累积用独立 `rawText` 变量 + 节流渲染读 `bubble._pendingText` 最新值（禁止旧快照回退），message/done 事件先取消未触发节流；静态资源必须带 `Cache-Control: no-cache`（中间件已加，勿删）。SSE 事件类型：`delta` / `message` / `tool_read`（AI 读文件，chip 封泡模式）/ `error` / `done`；mermaid 只在终渲染执行。
9. **tool-use 边界**：READ 标记独立一行、单次回复限 `ai_read_max_per_reply`（默认 3）次、单次注入限 `ai_read_max_lines`（默认 200）行；标记与注入内容**不进 chat_history**；读取走 code_browser 只读防护。
10. **交接文档**：功能/架构/约定变化后，同步更新 `AGENTS.md`、`README.md`、`docs/DevLog.md`（bug 史与决策记录）。

## 动态配置

- 阈值/阶段机/指令注册/LLM 主备/工作区：`config/settings.toml`（mtime 热重载；模型相关改动也可走页面「模型配置」热生效）
- 密钥：`study-web/.env`（`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_API_KEY_DEEPSEEK`）
- 运行时会话：各工作区 `session_path`（对话历史 + 阶段状态，可随时清空；学习数据不受影响）

## 扩展路径

| 需求 | 做法 |
|------|------|
| 新触发指令（简单） | `settings.toml [commands."新指令"]`，`handler = "declarative"` |
| 新触发指令（复杂） | `engine/commands/` 加 handler + `registry.py` 注册 |
| 新 LLM 渠道 | `llm/` 实现 LLMClient + `factory._BUILDERS` 注册 + toml 加 `[llm.<name>]` |
| 新落盘校验规则 | `app.py` 中 `hooks.register_post_persist(...)` |
| 新初始化文档类型 | `resources/templates/` 加模板 + `doc_initializer.SKELETON_DOCS` 注册一行 |
| 改初始化生成风格 | 改 `resources/prompts/init_*.md`，零代码 |
| 新增学习模式预设 | `resources/presets/` 加 toml（[[stages]] + description），向导自动出现 |
| 调构建验证（超时/离线） | 改 `settings.toml` 的 `verify_timeout` / `verify_offline`，零代码 |
| 调阈值（行数/及格分/题量） | 改 `settings.toml`，零代码 |

## v1 已知边界

- ~~`[开始今日学习]` 依赖 Study.md 当日已有 `## Day N |` 细化小节~~（已由增量细化解决：初始化自带前 3 天，`[结束今日学习]` 滚动细化次日；失败时需重发结束指令或手动细化）
- 复盘拷打题量靠 prompt 约束，非硬断言
- `[开始写代码]` 的编码启动模板由 LLM 填充（需模块信息）
- 仓库校验（Step 2）简化为目录存在性检查
