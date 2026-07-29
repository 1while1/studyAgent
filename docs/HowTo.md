# studyAgent 操作指南

本文档提供常见扩展操作的步骤指引。操作前请先阅读 `AGENTS.md` 铁律约束，并参考 `docs/Architecture.md` 了解模块职责。

---

## 新增工具到 tool_registry

工具通过 `ToolSpec` 注册到 `ToolRegistry`，权限分四级：`READONLY` / `WRITE` / `SANDBOX` / `LLM`。

1. 打开 `backend/engine/tool_registry.py`：
   - 实现 handler 函数：`def _my_tool(ctx: ToolContext, args: dict) -> ToolResult`
   - handler 缺依赖时返回 `ok=False` 明确错误，**不抛异常**
   - 写类工具必须走规则 14（`atomic_persist` / `validator`）
2. 在 `build_default_registry()` 中添加 `ToolSpec`：
   ```python
   reg.register(ToolSpec(
       name="my_tool",
       permission=READONLY,  # 或 WRITE / SANDBOX / LLM
       description="工具描述",
       params={"type": "object", "properties": {...}},
       handler=_my_tool,
   ))
   ```
3. 编写 `tests/test_tool_registry.py` 测试（MockLLM，不调真实 LLM）
4. 更新 `AGENTS.md` 工具数量（如有变化）

**注意**：READ/READ_DOC 标记截获改经 `tool_use.py`，分发走本注册表（铁律 9）。

---

## 新增教学阶段策略

阶段策略通过 `PhaseRegistry` 按优先级分发，`orchestrator` 调用 `dispatch()` 返回首个匹配策略。

1. 在 `backend/engine/phases/` 中新建文件（如 `my_phase.py`）
2. 继承 `PhaseHandler` ABC（定义在 `base.py`），实现：
   - `matches(session: SessionContext) -> bool`：匹配条件
   - `handle(ctx) -> ...`：处理逻辑
   - 可选：`instruction_for(session, user_text)` / `post_process(session, assistant_text)`
3. 在 `phases/__init__.py` 的 `build_registry()` 中注册，**注意优先级顺序**：
   ```
   Ended → Prereq → Interview → Reviewing → QuizR1 → QuizR2
   ```
   新策略插入到合适位置（越靠前优先级越高）
4. 编写测试（参考 `tests/test_phase_registry.py`）

---

## 新增 API 端点

路由按功能域拆分到不同文件，`app.py` 通过 `include_router()` 统一注册。

1. 确定功能域，选择对应路由文件：
   | 功能域 | 路由文件 |
   |--------|---------|
   | 核心 SSE（chat/command） | `routes.py` |
   | 工作区管理 | `workspace_routes.py` |
   | 学习者模型/笔记/话术 | `learner_routes.py` |
   | 代码浏览 | `code_routes.py` |
   | 认证 | `auth_routes.py` |
   | 模型配置/可观测 | `llm_config_routes.py` |

2. 在对应文件中添加路由（FastAPI `APIRouter` 风格）
3. 若是新路由文件，在 `app.py` 的 `include_router()` 中注册
4. 如需 auth 豁免，在 `middleware.py` 的豁免列表添加（仅 `/api/auth/{status,setup,login}` 默认豁免，铁律 14）
5. 编写测试

**注意**：api 层只做编排，不写业务逻辑（铁律约束）。

---

## 新增 LLM 渠道

LLM 渠道通过 `factory.py` 的 `_BUILDERS` 字典注册，`settings.toml` 配置挂载。

1. 在 `backend/llm/` 中新建文件（如 `my_provider.py`）
2. 实现 `LLMClient` 接口（定义在 `base.py`）
3. 在 `factory.py` 的 `_BUILDERS` 中注册：
   ```python
   _BUILDERS["my_provider"] = MyProviderBuilder
   ```
4. 在 `config/settings.toml` 添加配置段：
   ```toml
   [llm.my_provider]
   base_url = "..."
   api_key_env = "LLM_API_KEY_MYPROVIDER"
   model = "..."
   ```
5. 将 API key 添加到 `.env`（铁律 7：key 只进 `.env`）
6. 编写测试（参考 `tests/test_fallback.py`）

---

## 新增 SOP 指令

指令分两条路：声明式（零代码）和 handler（复杂逻辑）。

### 简单指令（声明式，零代码）

在 `config/settings.toml` 的 `[commands."指令名"]` 中添加：

```toml
[commands."我的指令"]
handler = "declarative"
sop_card = ""          # None=用注册卡 / ""=明确不带 / 文件名
mode = ""
```

### 复杂指令（handler）

1. 在 `backend/engine/commands/` 中新建文件（如 `my_command.py`）
2. 继承 `CommandHandler` ABC（定义在 `base.py`），实现处理逻辑
3. 在 `commands/registry.py` 中注册：
   - import 新 handler 类
   - 在 `_CODE_HANDLERS` 字典中添加映射：`"my_command": MyCommandHandler`
4. 在 `config/settings.toml` 添加触发词配置：
   ```toml
   [commands."触发词"]
   handler = "my_command"
   sop_card = "SOP_xxx.md"
   ```
5. 编写测试（参考 `tests/test_slash_commands.py`）

**注意**：commands 之间禁止互相 import（铁律约束）。

---

## 新增教学策略卡（pedagogy）

教学策略卡放在 `resources/pedagogy/` 目录，通过 `render_pedagogy` 渲染，面试指令与 LLM 工具共用同源。

1. 在 `resources/pedagogy/` 中新建 `.md` 卡（如 `my_strategy.md`）
2. 按已有卡格式编写内容
3. 在调用处通过 `render_pedagogy` 渲染（零代码，改资源文件即可）

---

## 新增学习模式预设

预设决定工作区的阶段配置，放在 `resources/presets/` 目录。

1. 在 `resources/presets/` 中新建 `.toml` 文件（如 `my_mode.toml`）
2. 包含 `[[stages]]` 数组 + `description` 字段
3. 向导会自动识别新预设

---

## 新增脚手架类型

脚手架模板树放在 `resources/scaffolds/` 目录，支持 `{{name}}` 占位符。

1. 在 `resources/scaffolds/` 中新建目录（如 `my_scaffold/`）
2. 在目录中放置模板文件树（文件名和内容均支持 `{{name}}` 占位符）
3. 向导/弹窗会自动识别新脚手架类型（零代码）

---

## 新增初始化文档类型

初始化文档骨架由 `doc_initializer.py` 的 `SKELETON_DOCS` 列表控制。

1. 在 `resources/templates/` 中新建模板文件
2. 在 `backend/services/doc_initializer.py` 的 `SKELETON_DOCS` 列表中注册一行
3. 提示词风格通过 `resources/prompts/init_*.md` 调整（零代码）

---

## 调上下文预算/压缩触发

在 `settings.toml` 的 `[context]` 段调整：
- `budget_tokens`：上下文预算上限
- `compress_trigger`：压缩触发比例
- `pin_top_k`：钉住层条数
- `archive_max`：归档层上限

也可通过前端“模型配置 → 上下文窗口”热生效。

---

## 配 cheap 档（压缩渠道）

在 `settings.toml` 添加：
```toml
[llm]
cheap_provider = "deepseek"  # 空 = 复用 strong
```
保存后重启或热生效。

---

## 调拷打反喂

在 `settings.toml` 调整：
- `qa_capture_enabled`：开关
- `qa_capture_max_entries`：最大条目数
- 反喂提示词：`resources/prompts/qa_capture.md`

---

## 配置资料库

在 `settings.toml` 工作区配置中添加：
```toml
[[workspaces]]
materials_dir = "/path/to/materials"
```
调整预取量/清单行数用 `materials_*` 键。

---

## 新增落盘校验规则

在 `backend/api/app.py` 中调用 `hooks.register_post_persist(callback)` 注册。

---

## 调进程/脚手架行为

白名单逻辑在 `backend/services/workshop_service.py`（改前先读铁律 17）。
端口快探 `_PORT_PROBE_TIMEOUT`、杀树宽限 `_STOP_GRACE` 在 `process_mgr.py` 中。
