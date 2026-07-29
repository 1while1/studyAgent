# studyAgent 演进路线 v2.0

**版本**：v2.0（扩展层升级版）
**生成日期**：2026-07-29
**适用对象**：项目后续开发 Agent（AI 主导维护）
**审计基准**：2026-07-29 实测代码库 + 多轮战略对话决策
**取代关系**：本版本取代 v1.0 中"明确不做"清单——MCP/Plugin/RAG/多模态/Web 搜索从"排除项"升级为"必做项"

---

## 0. 决策变更说明

### 0.1 v1.0 → v2.0 的核心变化

| 能力 | v1.0 立场 | v2.0 立场 | 变更理由 |
|---|---|---|---|
| MCP 协议 | YAGNI，不做 | **必做**（MCP Client） | 用户决策，扩展工具生态 |
| Plugin/Skill | 当前 registry 够用 | **必做**（pip entry_points 外部包插件） | 支持第三方扩展 |
| RAG 语义检索 | 文本粗排够用 | **必做**（资料库 + 笔记 + 历史 + 自定义知识库三源统一） | 提升检索准确度 |
| 多模态输入 | 稀释差异化 | **必做**（图片 + 文档 + Web 搜索） | 用户决策 |
| Web 浏览搜索 | 稀释差异化 | **必做** | 用户决策 |

### 0.2 变更带来的影响

- 扩展层从"暂缓"升级为**重头工程**，工程量与教学大脑 MVP（阶段 1）相当
- 阶段排序调整：扩展层（阶段 2.5）位于双轨地基（阶段 2）之后、沙箱化（阶段 3）之前
- 新增依赖：embedding 模型、向量存储、vision LLM、Web 搜索 API
- 架构冲击：tool_registry 必须重构以支持 MCP 工具 + Plugin 工具的统一调度

---

## 1. 核心定位（不变）

> **面向计算机技术学习者的开源学习 Agent，支持个人开箱即用与团队协作教学。**
>
> 差异化护城河：真实代码接地 + 持久学习者模型 + 证据驱动掌握度 + 教学大脑 + 可扩展生态。
>
> 部署形态：可下载桌面端 + 可自部署 web 端 + 可选云端团队服务。形态服从价值。

---

## 2. 阶段总览（v2.0 调整后）

```
阶段 0：地基清扫              ──┐
阶段 1：教学大脑 MVP           │  核心价值层（护城河）
阶段 2：双轨地基               │
阶段 2.5：扩展层（NEW）        │  ← v2.0 新增
阶段 3：沙箱化                 │  安全边界
阶段 4：形态扩展               ──┘  桌面端
```

### 阶段依赖关系

```
M0 ─→ M1.1 ─→ M1.2 ─→ M1.3 ─→ M2.1 ─→ M2.2 ─→ M2.3 ─→ M2.5 ─→ M3 ─→ M4
                                                  │
                                                  └─ 扩展层在双轨地基完成后启动
                                                     （需要 Repository + AuthProvider + 团队 schema 支持）
```

---

## 3. 阶段详情

### 阶段 0：地基清扫（前置必做，无变化）

#### 0.1 任务清单

- [ ] 0.1.1 选定 LICENSE（MIT），添加 LICENSE 文件
- [ ] 0.1.2 配置分层：
  - `config/settings.toml` → `config/settings.example.toml`（入库，移除个人工作区）
  - `config/settings.local.toml`（gitignore，个人用）
- [ ] 0.1.3 `workspaces/` 加入 .gitignore，仓库只保留 `workspaces/.gitkeep`
- [ ] 0.1.4 `git rm -r --cached workspaces/`
- [ ] 0.1.5 README 修正：删除失真的 `cd study-web`
- [ ] 0.1.6 测试数对齐：跑 `python -m unittest discover -s tests`，统一 AGENTS.md / README
- [ ] 0.1.7 CI 修复：移除 `|| true`，移除 `if [ -d workspaces/ragent ]` 前置，改为 CI 临时构造测试工作区
- [ ] 0.1.8 打 git tag v1.0.0
- [ ] 0.1.9 AGENTS.md 拆分：架构/模块职责移至 `docs/Architecture.md`，AGENTS.md 只保留铁律/约束/边界

#### 0.2 验收标准

- `LICENSE` 文件存在
- `config/settings.example.toml` 入库，无个人路径（`D:\IntelliJ IDEA` 等）
- `config/settings.local.toml` 在 .gitignore
- `workspaces/` 在 .gitignore，仓库只有 `workspaces/.gitkeep`
- README 无 `cd study-web`
- AGENTS.md / README 测试数与实测一致（572 ± 实际执行数）
- CI validate 步骤无 `|| true`
- CI 无 `if [ -d workspaces/ragent ]` 前置
- `git tag` 列出 v1.0.0
- `docs/Architecture.md` 存在
- **冒烟测试**：干净虚拟环境 clone 仓库，按 README 指引能成功启动 uvicorn 并访问 /docs

---

### 阶段 1：教学大脑 MVP（核心护城河，无变化）

#### 1.1 错误模式库

**决策**：两级结构（5 固定大类 + LLM 自由子类）

**任务清单**：

- [ ] 1.1.1 新建 `backend/domain/error_pattern.py`，定义 5 枚举：
  - `CONCEPT_CONFUSION`（概念混淆）
  - `DETAIL_ERROR`（记错细节）
  - `LOGIC_BREAK`（逻辑链断裂）
  - `CANNOT_APPLY`（不会应用）
  - `FORGOTTEN`（忘记）
- [ ] 1.1.2 evidence schema 加 `error_pattern_major: str | None`（枚举值）
- [ ] 1.1.3 evidence schema 加 `error_pattern_minor: str | None`（LLM 自由文本子类）
- [ ] 1.1.4 quiz_engine 评分 prompt 加错误分类指令，LLM 顺手输出 JSON：
  ```json
  {"score": 3.5, "error_major": "CONCEPT_CONFUSION", "error_minor": "将 BFS 当成 DFS"}
  ```
- [ ] 1.1.5 qa_capture 反喂时也写入这两个字段
- [ ] 1.1.6 编写 `tests/test_error_pattern.py`，覆盖：
  - 枚举校验
  - LLM 输出解析（合法/非法 JSON 容错）
  - evidence 落盘
  - 反喂写入
  - 衰减计算不受影响
- [ ] 1.1.7 现有 quiz 流程无回归（原 quiz 测试全绿）

**验收标准**：
- `backend/domain/error_pattern.py` 存在，5 枚举定义
- evidence 落盘的 JSON 含两个新字段
- quiz 评分 LLM 输出含错误分类
- qa_capture 反喂写入错误分类
- `tests/test_error_pattern.py` 全绿
- 原 quiz 测试无回归

#### 1.2 教学行动策略库

**决策**：推荐 + 用户确认制

**任务清单**：

- [ ] 1.2.1 新建 `backend/engine/teaching_strategy.py`
- [ ] 1.2.2 实现 5-7 个教学行动：
  - `REVIEW_PREREQ`（补先修）
  - `RETELL_CORE`（重讲核心）
  - `VARIANT_QUIZ`（出变体题）
  - `ADVANCE_NEXT`（推进下一概念）
  - `REST`（休息）
  - `CHANGE_ANGLE`（换角度）
  - `PRACTICE_PROJECT`（练项目）
- [ ] 1.2.3 行动选择逻辑：根据学习者模型当前状态（mastery / error_pattern / 连续错误数 / 上次学习时间）选 top-1 行动
- [ ] 1.2.4 每回合 orchestrator 调用 `teaching_strategy.suggest(context)` 生成 `teaching_action_suggestion` 字段
- [ ] 1.2.5 前端 UI 渲染"建议卡片 + 确认/跳过按钮"
- [ ] 1.2.6 用户确认后执行对应行动；跳过则走默认流程
- [ ] 1.2.7 编写 `tests/test_teaching_strategy.py`，覆盖：
  - 行动选择逻辑（各状态对应行动）
  - 推荐生成
  - 用户确认流转
  - 跳过流转
  - MockLLM 场景

**验收标准**：
- `backend/engine/teaching_strategy.py` 存在，5-7 个行动实现
- 每回合生成 `teaching_action_suggestion` 字段
- 前端"建议卡片 + 确认/跳过按钮"渲染正常
- `tests/test_teaching_strategy.py` 全绿
- 用户确认/跳过流程跑通

#### 1.3 学习效果度量

**决策**：三指标组合 → 掌握分；个人展示进步曲线 + 团队管理员面板

**任务清单**：

- [ ] 1.3.1 指标 A：掌握进度（evidence 数 + 天数）
- [ ] 1.3.2 指标 B：知识保持度（3 天后 quiz 正确率）
- [ ] 1.3.3 指标 C：迁移应用能力（期末项目题，LLM 评完成度）
- [ ] 1.3.4 三指标组合公式：`mastery_score = w1*A + w2*B + w3*C`，默认权重 0.3/0.3/0.4（可配）
- [ ] 1.3.5 落盘到 agent.log
- [ ] 1.3.6 掌握度面板展示个人进步曲线（时间序列）
- [ ] 1.3.7 团队管理员面板占位（阶段 2.3 schema 出来后接）
- [ ] 1.3.8 编写 `tests/test_learning_metrics.py`，覆盖：
  - 三指标计算
  - 组合公式
  - 落盘格式
  - 数据查询

**验收标准**：
- 三指标计算逻辑存在
- 组合公式实现
- 落盘到 agent.log
- 掌握度面板展示个人曲线
- `tests/test_learning_metrics.py` 全绿

---

### 阶段 2：双轨地基 + 本地团队（无变化）

#### 2.1 Repository 抽象

**任务清单**：

- [ ] 2.1.1 新建 `backend/services/repository.py` 接口，定义 CRUD 抽象方法
- [ ] 2.1.2 新建 `backend/services/json_repository.py`，包装当前 JSON 直操
- [ ] 2.1.3 `SqliteRepository` 占位实现（NotImplementedError）
- [ ] 2.1.4 业务层逐步切换：
  - notes_service
  - learner_service
  - materials_service
  - workspace_service（最后）
- [ ] 2.1.5 编写 `tests/test_repository.py`，验证 JsonRepository 行为与原 JSON 直操一致

**验收标准**：
- `backend/services/repository.py` 接口存在
- `JsonRepository` 包装当前实现
- `SqliteRepository` 占位
- 业务层切换后原 572 测试全绿
- `tests/test_repository.py` 全绿

#### 2.2 认证可插拔化

**任务清单**：

- [ ] 2.2.1 新建 `backend/services/auth_provider.py` 接口
- [ ] 2.2.2 `LocalAuthProvider` 包装当前 bcrypt 密码门
- [ ] 2.2.3 `OAuthProvider` 占位（NotImplementedError）
- [ ] 2.2.4 middleware 切换到 AuthProvider 接口
- [ ] 2.2.5 编写 `tests/test_auth_provider.py`

**验收标准**：
- `AuthProvider` 接口存在
- `LocalAuthProvider` 行为与原 bcrypt 一致
- `OAuthProvider` 占位
- 原认证测试全绿

#### 2.3 Workspace 多用户 schema

**任务清单**：

- [ ] 2.3.1 Workspace 加 `owner_id: str`
- [ ] 2.3.2 Workspace 加 `members: list[dict]`（`{user_id, role}`）
- [ ] 2.3.3 role 枚举：`owner / teacher / member`
- [ ] 2.3.4 visibility 枚举：`private / shared / public`
- [ ] 2.3.5 编写 `tests/test_workspace_members.py`

**验收标准**：
- Workspace 含 4 个新字段
- `tests/test_workspace_members.py` 全绿

#### 2.4 本地小型团队

**任务清单**：

- [ ] 2.4.1 本地模式支持 Workspace 多用户读写（与云端同 schema）
- [ ] 2.4.2 本地多用户读写权限校验
- [ ] 2.4.3 仅无跨设备同步

**验收标准**：
- 本地模式可创建多用户 Workspace
- 权限校验生效
- 无云同步（本地数据不出设备）

#### 2.5 三种团队形态

**任务清单**：

- [ ] 2.5.1 教师-学生（owner/teacher 看全部，member 仅看自己）
- [ ] 2.5.2 学习小组（成员互见笔记和进度）
- [ ] 2.5.3 资源协作（独立学习 + 共享资料库）

**验收标准**：
- 三种形态可本地跑通
- 权限矩阵符合定义

---

### 阶段 2.5：扩展层（v2.0 新增）

> **这是 v2.0 的核心新增内容。** 四项扩展能力（MCP/Plugin/RAG/多模态+Web 搜索）位于双轨地基完成之后、沙箱化之前。
>
> **依赖前置**：扩展层需要 Repository（阶段 2.1）支持自定义知识库存储，需要 AuthProvider（阶段 2.2）支持插件权限校验，需要 Workspace 多用户 schema（阶段 2.3）支持团队级插件配置。

#### 2.5.1 MCP Client 接入

**决策**：MCP Client 角色——studyAgent 作为 MCP Host，接入外部 MCP 服务器。

**架构设计**：

```
┌─ studyAgent engine ──────────────────────────┐
│  tool_registry（统一调度）                    │
│    ├─ 内置工具（17 个，当前已有）             │
│    └─ MCP 工具适配器（NEW）                   │
│         ├─ MCPClientPool（管理多个 MCP server）│
│         ├─ MCPToolAdapter（统一 ToolSpec 接口）│
│         └─ MCP config（settings.toml 配置）   │
└──────────────────────────────────────────────┘
        ↓ JSON-RPC 2.0 over stdio/SSE
┌─ 外部 MCP Server ────────────────────────────┐
│  GitHub MCP / Filesystem MCP / Search MCP   │
│  / Browser MCP / 自定义 MCP ...              │
└──────────────────────────────────────────────┘
```

**任务清单**：

- [ ] 2.5.1.1 新建 `backend/services/mcp_client_service.py`：
  - `MCPClientPool`：管理多个 MCP server 连接
  - `MCPClient`：单个 MCP server 的 JSON-RPC 2.0 客户端（支持 stdio + SSE 两种 transport）
  - `MCPToolAdapter`：将 MCP tool schema 转换为 studyAgent `ToolSpec`
- [ ] 2.5.1.2 `settings.toml` 加 `[mcp]` 配置段：
  ```toml
  [[mcp.servers]]
  name = "github"
  transport = "stdio"
  command = "npx"
  args = ["-y", "@modelcontextprotocol/server-github"]
  env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }
  enabled = true

  [[mcp.servers]]
  name = "filesystem"
  transport = "stdio"
  command = "npx"
  args = ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE_DIR}"]
  enabled = true
  ```
- [ ] 2.5.1.3 启动时 `MCPClientPool` 加载配置，连接所有 enabled server
- [ ] 2.5.1.4 `MCPToolAdapter` 将 MCP tools 注册到 `tool_registry`，权限级别默认 `READONLY`（可配）
- [ ] 2.5.1.5 planner 的 ACTION 标记可调用 MCP 工具
- [ ] 2.5.1.6 MCP server 连接失败静默降级（不阻断学习流程，符合"观测不阻断"铁律）
- [ ] 2.5.1.7 编写 `tests/test_mcp_client.py`，覆盖：
  - 配置解析
  - stdio/SSE transport 模拟
  - tool schema 转换
  - 连接失败降级
  - 工具调用流转

**验收标准**：
- `backend/services/mcp_client_service.py` 存在
- `settings.toml` 支持 `[mcp.servers]` 配置
- 配置 1 个 mock MCP server，工具能注册到 tool_registry
- planner ACTION 能调用 MCP 工具
- 连接失败不阻断学习流程
- `tests/test_mcp_client.py` 全绿

#### 2.5.2 Plugin/Skill 系统（pip entry_points）

**决策**：外部包插件，通过 pip entry_points 注册。

**架构设计**：

```
┌─ studyAgent plugin loader ────────────────────┐
│  PluginRegistry                                │
│    ├─ scan_entry_points(group="studyagent.plugins")│
│    ├─ 加载插件 manifest（PluginSpec）          │
│    └─ 注册到 tool_registry / commands / resources│
└──────────────────────────────────────────────┘
        ↑ pip install studyagent-plugin-xxx
┌─ 第三方插件包（PyPI）────────────────────────┐
│  setup.py: entry_points={"studyagent.plugins": ["xxx = myplugin:plugin"]}│
│  plugin = PluginSpec(                         │
│    name="xxx",                                │
│    tools=[...],                               │
│    commands=[...],                            │
│    resources_dir="resources/",                │
│    permissions={...}                          │
│  )                                            │
└──────────────────────────────────────────────┘
```

**任务清单**：

- [ ] 2.5.2.1 新建 `backend/services/plugin_service.py`：
  - `PluginSpec` dataclass：name / tools / commands / resources_dir / permissions
  - `PluginRegistry`：扫描 `studyagent.plugins` entry_points 组，加载插件
  - `PluginLoader`：加载插件，注册到 tool_registry / commands registry / resources 路径
- [ ] 2.5.2.2 插件权限模型：
  - 插件在 manifest 中声明所需权限（工具/指令/资源类型）
  - 用户在 settings.toml 白名单授权
  - 未授权插件不加载
- [ ] 2.5.2.3 插件资源隔离：
  - 插件的 resources/ 目录挂载到独立命名空间（如 `plugin:xxx/sop/`）
  - 避免与内置 resources 冲突
- [ ] 2.5.2.4 插件配置：
  ```toml
  # settings.toml
  [plugins]
  enabled = ["studyagent-plugin-git"]  # 白名单
  autoload = true  # 启动时自动扫描 entry_points
  ```
- [ ] 2.5.2.5 编写示例插件 `tests/fixtures/sample_plugin/`：
  - `setup.py` 含 entry_points
  - `sample_plugin.py` 定义一个简单工具
- [ ] 2.5.2.6 编写 `tests/test_plugin_service.py`，覆盖：
  - entry_points 扫描
  - 插件加载
  - 工具/指令注册
  - 权限校验
  - 资源命名空间隔离
  - 未授权插件不加载

**验收标准**：
- `backend/services/plugin_service.py` 存在
- `pip install` 一个测试插件包后，启动 studyAgent 能自动扫描并加载
- 插件工具能注册到 tool_registry
- 插件指令能注册到 commands registry
- 未授权插件不加载
- `tests/test_plugin_service.py` 全绿

#### 2.5.3 RAG 语义检索（三源统一）

**决策**：资料库 + 笔记 + 历史对话 + 自定义知识库，统一向量索引。

**架构设计**：

```
┌─ studyAgent RAG 层 ──────────────────────────┐
│  VectorStore（统一向量存储）                  │
│    ├─ MaterialsSource（资料库 chunks）        │
│    ├─ NotesSource（笔记 chunks）              │
│    ├─ HistorySource（历史对话 chunks）         │
│    └─ CustomSource（自定义知识库 chunks，NEW） │
│                                               │
│  EmbeddingService（embedding 生成）           │
│    ├─ 接口：embed(text) -> vector             │
│    ├─ OpenAIEmbedding（openai_compat 复用）   │
│    └─ LocalEmbedding（sentence-transformers） │
│                                               │
│  RetrieverService（检索服务）                │
│    ├─ retrieve(query, top_k) -> chunks[]     │
│    ├─ 多源召回 + 加权重排                    │
│    └─ 与 materials_service 文本粗排互补       │
└──────────────────────────────────────────────┘
```

**任务清单**：

- [ ] 2.5.3.1 新建 `backend/services/embedding_service.py`：
  - `EmbeddingService` 接口：`embed(text: str) -> list[float]`
  - `OpenAIEmbedding`：复用 openai_compat，调 `text-embedding-3-small` 等
  - `LocalEmbedding`：用 `sentence-transformers` 本地模型（如 `all-MiniLM-L6-v2`）
- [ ] 2.5.3.2 新建 `backend/services/vector_store.py`：
  - `VectorStore` 接口：`add / search / delete`
  - `InMemoryVectorStore`（默认，FAISS 或 numpy）
  - `SqliteVectorStore`（sqlite-vec 扩展，与 Repository 抽象协同）
  - `ChromaVectorStore` 占位（未来可选）
- [ ] 2.5.3.3 三源索引器：
  - `MaterialsIndexer`：资料库文档分 chunk + embed + 入库
  - `NotesIndexer`：笔记条目 embed + 入库
  - `HistoryIndexer`：历史对话摘要后 embed + 入库
- [ ] 2.5.3.4 自定义知识库：
  - Workspace 加 `knowledge_bases: list[dict]`（路径 + 名称 + 描述）
  - `CustomIndexer`：扫描知识库目录，支持 md/txt/pdf
  - 知识库与资料库分离存储（避免污染）
- [ ] 2.5.3.5 `RetrieverService`：
  - 多源召回（每源 top_k，合并后重排）
  - 加权重排（资料库 > 笔记 > 历史 > 自定义，权重可配）
  - 与 materials_service 文本粗排互补（两段式：粗排 + 精排）
- [ ] 2.5.3.6 增量索引：
  - 文档/笔记变更时增量更新向量（不重建全量）
  - 落盘记录索引版本（`<docx_dir>/materials/_cache/vector_index.json`）
- [ ] 2.5.3.7 索引失败静默降级（符合"观测不阻断"铁律）
- [ ] 2.5.3.8 编写 `tests/test_rag.py`，覆盖：
  - embedding 生成（Mock）
  - 向量入库/查询
  - 三源索引器
  - 自定义知识库
  - 多源召回 + 重排
  - 增量索引
  - 索引失败降级

**验收标准**：
- `backend/services/embedding_service.py` + `vector_store.py` 存在
- 三源索引器 + 自定义知识库实现
- `RetrieverService` 多源召回 + 加权重排
- 增量索引生效
- 索引失败不阻断学习流程
- `tests/test_rag.py` 全绿
- 现有 materials_service 文本粗排保留（两段式互补）

#### 2.5.4 多模态输入 + Web 搜索

**决策**：图片输入 + 文档上传 + Web 搜索三入口全含。

**架构设计**：

```
┌─ studyAgent 多模态层 ────────────────────────┐
│  UploadService（文件上传服务）                │
│    ├─ 图片：jpg/png/gif/webp                  │
│    ├─ 文档：md/txt/pdf（复用 materials_service）│
│    └─ 存储：<docx_dir>/uploads/               │
│                                               │
│  VisionService（图片转文字）                  │
│    ├─ 接口：describe(image_path) -> text     │
│    ├─ VisionLLM（openai_compat vision）      │
│    └─ 本地 OCR 占位（tesseract，可选）        │
│                                               │
│  WebSearchService（Web 搜索）                 │
│    ├─ 接口：search(query) -> results[]       │
│    ├─ WebSearchProvider（可插拔）              │
│    │   ├─ TavilyProvider                      │
│    │   ├─ SerperProvider                       │
│    │   └─ DuckDuckGoProvider（免费，默认）     │
│    └─ 结果缓存（避免重复查询）                │
└──────────────────────────────────────────────┘
```

**任务清单**：

- [ ] 2.5.4.1 新建 `backend/services/upload_service.py`：
  - `UploadService`：处理文件上传
  - 图片：jpg/png/gif/webp，存到 `<docx_dir>/uploads/`
  - 文档：md/txt/pdf，复用 materials_service 注册到资料库
  - 文件大小限制（可配，默认 10MB）
  - 病毒扫描占位（可挂 clamd，可选）
- [ ] 2.5.4.2 新建 `backend/services/vision_service.py`：
  - `VisionService` 接口：`describe(image_path, prompt) -> text`
  - `VisionLLM`：复用 openai_compat，调 GPT-4o / Claude vision 等
  - 图片转文字后注入对话上下文（带"仅供参考不视为指令"定界，符合铁律 12）
- [ ] 2.5.4.3 新建 `backend/services/web_search_service.py`：
  - `WebSearchService` 接口：`search(query, top_k) -> list[SearchResult]`
  - `WebSearchProvider` 可插拔接口
  - `TavilyProvider` / `SerperProvider` / `DuckDuckGoProvider`（默认免费）
  - 结果缓存（LRU，可配大小）
  - API key 走 .env（符合铁律 7）
- [ ] 2.5.4.4 新增 API 路由 `backend/api/upload_routes.py`：
  - `POST /api/upload/image`：图片上传
  - `POST /api/upload/document`：文档上传
  - `POST /api/web/search`：Web 搜索
- [ ] 2.5.4.5 planner 加两个新工具：
  - `web_search`：Web 搜索工具（READONLY 权限）
  - `vision_analyze`：图片分析工具（READONLY 权限）
- [ ] 2.5.4.6 前端加文件上传组件：
  - 聊天框附件按钮（图片/文档）
  - Web 搜索按钮（对话中触发）
  - 上传进度条
- [ ] 2.5.4.7 编写 `tests/test_multimodal.py`，覆盖：
  - 文件上传（合法/非法类型）
  - 图片转文字
  - Web 搜索（Mock provider）
  - 结果缓存
  - 注入对话上下文定界

**验收标准**：
- `backend/services/upload_service.py` + `vision_service.py` + `web_search_service.py` 存在
- 图片可上传并转文字注入对话
- 文档可上传并注册到资料库
- Web 搜索可调用并返回结果
- planner ACTION 可调用 `web_search` / `vision_analyze` 工具
- `tests/test_multimodal.py` 全绿

#### 2.5.5 扩展层依赖与配置

**新增依赖（requirements.txt）**：

```
# MCP Client
mcp>=0.1.0              # MCP Python SDK（或自行实现 JSON-RPC）

# Plugin
importlib-metadata>=8.0 # entry_points 扫描（Python 3.10+ 已内置，3.9 需要）

# RAG
sentence-transformers>=3.0  # 本地 embedding（可选）
numpy>=1.26              # 向量计算
# sqlite-vec>=0.1         # SQLite 向量扩展（可选，未来用）

# 多模态
python-multipart>=0.0.9 # FastAPI 文件上传
# tesseract 依赖系统级安装，不在 requirements.txt

# Web 搜索
httpx>=0.27             # HTTP 客户端（Web 搜索 API）
```

**新增 settings.toml 配置段**：

```toml
[mcp]
enabled = true
default_permission = "readonly"

[[mcp.servers]]
name = "github"
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
enabled = false  # 默认关闭，用户按需开启

[plugins]
enabled = []
autoload = true

[rag]
enabled = true
embedding_provider = "openai"  # openai / local
embedding_model = "text-embedding-3-small"
local_model = "all-MiniLM-L6-v2"
vector_store = "memory"  # memory / sqlite
top_k = 5
source_weights = { materials = 0.4, notes = 0.3, history = 0.2, custom = 0.1 }

[multimodal]
upload_enabled = true
max_upload_mb = 10
vision_provider = "openai"
web_search_provider = "duckduckgo"  # duckduckgo / tavily / serper
web_search_cache_size = 100
```

**新增 .env 变量**：

```bash
# MCP
GITHUB_TOKEN=...
# Web 搜索
TAVILY_API_KEY=...
SERPER_API_KEY=...
# RAG（如用 OpenAI embedding，复用 LLM_API_KEY）
```

---

### 阶段 3：沙箱化（云端开放前必做，无变化）

#### 3.1 任务清单

- [ ] 3.1.1 沙箱方案选型：Docker / Firecracker microVM / WASM runtime
- [ ] 3.1.2 process_start 沙箱化实现
- [ ] 3.1.3 编写 `tests/test_sandbox.py`

#### 3.2 触发条件

- **云端团队开放前 = P0**
- 未开放 = P3（暂缓）

#### 3.3 验收标准

- process_start 在沙箱内执行
- 沙箱外不可访问
- `tests/test_sandbox.py` 全绿

---

### 阶段 4：形态扩展（价值验证后，无变化）

#### 4.1 任务清单

- [ ] 4.1.1 桌面端技术选型：Tauri / Electron / PyWebView
- [ ] 4.1.2 桌面端套壳实现

#### 4.2 触发条件

- 教学大脑 MVP + 双轨地基 + 扩展层验证后

---

## 4. AI 维护优化铁律（贯穿所有阶段）

> **这三条是针对"纯 AI 开发"约束追加的，比阶段排序更重要。**

### 4.1 所有抽象必须文件可见，不做"约定优于配置"

- 不用依赖注入容器、不用插件注册装饰器、不用"自动发现"
- 接口在 `repository.py`、实现在 `json_repository.py` / `sqlite_repository.py`，文件名即角色
- MCP 工具适配器在 `mcp_client_service.py`、插件加载器在 `plugin_service.py`，文件名即角色
- **理由**：AI 改代码靠 grep 文件名定位，隐式约定 AI 看不到

### 4.2 每个阶段交付必须可独立验证，不依赖下一阶段

- M1.1 错误模式库单独可跑，不依赖 M2.1 Repository
- M2.1 Repository 抽象单独可跑，不依赖 M2.5 扩展层
- M2.5.1 MCP Client 单独可跑，不依赖 M2.5.2 Plugin
- M2.5.3 RAG 单独可跑，不依赖 M2.5.4 多模态
- **理由**：AI 一次性做完一个阶段，跨阶段依赖会导致 AI 改一半忘记衔接

### 4.3 每个新模块必须有对应的单元测试

| 模块 | 测试文件 |
|---|---|
| 错误模式库 | `tests/test_error_pattern.py` |
| 教学策略 | `tests/test_teaching_strategy.py` |
| 学习度量 | `tests/test_learning_metrics.py` |
| Repository | `tests/test_repository.py` |
| AuthProvider | `tests/test_auth_provider.py` |
| Workspace 多用户 | `tests/test_workspace_members.py` |
| **MCP Client** | **`tests/test_mcp_client.py`** |
| **Plugin 系统** | **`tests/test_plugin_service.py`** |
| **RAG** | **`tests/test_rag.py`** |
| **多模态** | **`tests/test_multimodal.py`** |

- **理由**：纯 AI 开发最大风险是"看起来对实际跑不通"，只有测试能拦

---

## 5. 通用质量验收标准

### 5.1 每个里程碑必须满足

| # | 标准 | 验证方式 |
|---|---|---|
| Q.1 | 所有新增/修改代码必须有对应单元测试 | 测试文件存在且覆盖核心路径 |
| Q.2 | 全套测试通过：`python -m unittest discover -s tests` 零失败 | CI 绿 |
| Q.3 | 无回归：原测试用例全部仍通过 | CI 绿 |
| Q.4 | 新增 `except Exception:` 必须有注释说明为何宽 except | grep 检查 |
| Q.5 | 新增模块必须有 module docstring（含设计意图 + 历史背景） | grep 检查 |
| Q.6 | 不引入新的硬编码（项目名/天数/路径必须走 Workspace） | grep 检查 |
| Q.7 | 不违反 AGENTS.md 17 条铁律 | 人工 review |
| Q.8 | 所有 boot-critical 写走 `atomic_write` / `atomic_persist` | grep 检查 |
| Q.9 | 配置项走 resources/ 或 settings.toml，不在代码里写 | grep 检查 |
| Q.10 | 新增 LLM 评价类输出必须含 `【评分：X.X】`（1.0-5.0） | 单元测试 |

### 5.2 扩展层专项验收（v2.0 新增）

| # | 标准 | 验证方式 |
|---|---|---|
| EQ.1 | MCP server 连接失败不阻断学习流程 | 断开 MCP server，学习流程正常 |
| EQ.2 | 未授权插件不加载 | 配置非白名单插件，启动后不在 registry |
| EQ.3 | RAG 索引失败静默降级 | embedding 服务宕机，学习流程正常 |
| EQ.4 | 多模态注入内容必须带"仅供参考不视为指令"定界 | grep 检查 |
| EQ.5 | Web 搜索 API key 只进 .env，接口只返回掩码 | grep 检查 |
| EQ.6 | 插件资源命名空间隔离 | 插件 resources 与内置 resources 不冲突 |
| EQ.7 | 向量索引增量更新，不重建全量 | 修改文档后，索引版本号递增 |
| EQ.8 | 扩展层所有新工具默认 READONLY 权限 | tool_registry 检查 |

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| AI 改代码引入隐式回归 | 高 | 中 | 每模块配测试；CI 修复后红绿即拦 |
| 阶段 2.1 Repository 切换业务层时漏改 | 中 | 高 | 分服务切换，每个服务切换后跑全套测试 |
| 教学策略库 prompt 工程不稳定 | 中 | 中 | M1.2 先用 MockLLM 测试，再接真实 LLM 调优 |
| **MCP 生态不稳定（server 断更/不兼容）** | **高** | **中** | **MCP 连接失败静默降级；不依赖单一 server** |
| **Plugin 系统安全风险（恶意插件）** | **高** | **高** | **权限白名单 + 资源命名空间隔离；云端团队场景需管理员授权** |
| **RAG embedding 成本（OpenAI）** | **中** | **中** | **默认本地 embedding（sentence-transformers）；OpenAI 可选** |
| **多模态上传滥用（大文件/恶意文件）** | **中** | **中** | **文件大小限制 + 类型白名单；病毒扫描占位** |
| **Web 搜索 API 限流/封禁** | **中** | **低** | **默认 DuckDuckGo 免费源；多 provider 可插拔** |
| 沙箱化（M3）涉及安全专业领域 | 高 | 高 | **不要 AI 独立做**，必须专业 review |
| 个人精力（研究生并行学业）导致推进缓慢 | 高 | 中 | 里程碑制而非时间制，每个里程碑可暂停 |
| GitHub 开源后社区期望 vs AI 维护节奏不匹配 | 中 | 中 | README 明确标注"AI 主导开发 + 边做边学"，降低社区期望 |

---

## 7. 核心护城河（v2.0 最终版）

| 护城河 | 当前状态 | 后续强化 |
|---|---|---|
| 真实代码接地（code_roots + 实战工坊） | ✅ 已具备 | 阶段 3 沙箱化保护 |
| 持久学习者模型（evidence + mastery 衰减） | ✅ 已具备 | 阶段 1.1 加错误模式两级库 |
| 证据驱动掌握度（code_verify 封顶 0.6） | ✅ 已具备 | 阶段 1.3 升级为三指标组合掌握分 |
| 教学大脑 | ❌ 当前是工作流 | 阶段 1.2 行动策略库 + 推荐确认制 |
| 本地/云端双轨中立 | ❌ 当前是本地单机 | 阶段 2 Repository + AuthProvider 可插拔 |
| 团队协作 | ❌ 当前不支持 | 阶段 2.3-2.5 三种团队形态 |
| **可扩展生态** | ❌ 当前工具硬编码 | **阶段 2.5 MCP Client + Plugin + RAG + 多模态** |

---

## 8. 不做清单（v2.0 修正）

### 8.1 仍不做

- ❌ Dockerfile（暂缓到形态确定）
- ❌ 商业 SaaS 计费（用户自带 key 已砍掉）
- ❌ 为未来社区贡献者优化架构（当前是 AI 主导维护）
- ❌ Firecracker / WASM 作为首选沙箱（Docker 优先）

### 8.2 从"不做"升级为"必做"（v2.0 变更）

- ✅ MCP 协议接入（MCP Client 角色）
- ✅ Plugin/Skill 系统（pip entry_points 外部包插件）
- ✅ RAG 语义检索（三源统一 + 自定义知识库）
- ✅ 多模态输入（图片 + 文档）
- ✅ Web 浏览搜索（多 provider 可插拔）

---

## 9. 执行顺序总览

```
M0 地基清扫
 ├─ LICENSE + 数据剥离
 ├─ README + CI 修复
 ├─ 测试数对齐
 └─ AGENTS.md 拆分

M1 教学大脑 MVP（核心护城河）
 ├─ M1.1 错误模式库（两级结构）
 ├─ M1.2 教学行动策略库（推荐 + 确认）
 └─ M1.3 学习效果度量（三指标组合）

M2 双轨地基
 ├─ M2.1 Repository 抽象
 ├─ M2.2 AuthProvider 可插拔
 ├─ M2.3 Workspace 多用户 schema
 ├─ M2.4 本地小型团队
 └─ M2.5 三种团队形态

M2.5 扩展层（v2.0 新增）
 ├─ M2.5.1 MCP Client
 ├─ M2.5.2 Plugin 系统
 ├─ M2.5.3 RAG 语义检索
 └─ M2.5.4 多模态 + Web 搜索

M3 沙箱化（条件触发）
 └─ process_start 沙箱化

M4 桌面端（条件触发）
 └─ Tauri / Electron 套壳
```

---

## 10. 一句话执行指令

**先扫干净地基（M0），立刻启动教学大脑 MVP（M1.1 错误模式库是最小切片），铺双轨地基（M2.1 Repository + M2.2 AuthProvider + M2.3 团队 schema），然后启动扩展层（M2.5 MCP/Plugin/RAG/多模态四项），沙箱化和桌面端等价值验证后再投入。全程为 AI 维护优化——所有抽象文件可见、每阶段独立可验证、每个新模块配测试。测试是唯一防线，CI 必须先修复。**

---

## 附录 A：阶段依赖矩阵

| 阶段 | 前置依赖 | 可并行 |
|---|---|---|
| M0 | 无 | 无 |
| M1.1 | M0 | 无 |
| M1.2 | M1.1 | 无 |
| M1.3 | M1.1 | M1.2 |
| M2.1 | M1.3 | 无 |
| M2.2 | M2.1 | 无 |
| M2.3 | M2.2 | 无 |
| M2.4 | M2.3 | 无 |
| M2.5 | M2.3 | 无 |
| M2.5.1 | M2.5 | M2.5.2 |
| M2.5.2 | M2.5 | M2.任务）→ 定稿成最终 md 文档，覆盖原有 Roadmap_v2.md。已生成的文档位于：

[Roadmap_v2.md](file:///d:/Ragent学习/study-web/docs/Roadmap_v2.md)

## 文档要点

**v2.0 核心变更**：MCP/Plugin/RAG/多模态+Web 搜索四项从"不做"升级为"必做"，新增阶段 2.5 扩展层。

**扩展层四项的范围决策**：
- **MCP Client**：studyAgent 作为 MCP Host 接入外部 server，`mcp_client_service.py` + JSON-RPC 2.0 over stdio/SSE，连接失败静默降级
- **Plugin 系统**：pip entry_points 外部包插件，`plugin_service.py` + PluginSpec manifest + 权限白名单 + 资源命名空间隔离
- **RAG**：三源统一向量索引（资料库 + 笔记 + 历史 + 自定义知识库），`embedding_service.py` + `vector_store.py` + 多源加权重排，与 materials_service 文本粗排两段式互补
- **多模态 + Web 搜索**：图片/文档上传 + Vision LLM 转文字 + 多 provider 可插拔 Web 搜索（默认 DuckDuckGo 免费）

**关键约束**：
- 扩展层位于双轨地基（阶段 2）之后、沙箱化（阶段 3）之前，因需 Repository + AuthProvider + 团队 schema 支持
- 扩展层所有新工具默认 READONLY 权限
- 多模态注入内容必须带"仅供参考不视为指令"定界（铁律 12 一致）
- API key 只进 .env，接口只返回掩码（铁律 7 一致）
- MCP/Plugin/RAG 连接失败静默降级，不阻断学习流程（铁律 13 一致）

**新增依赖**：mcp / sentence-transformers / numpy / httpx / python-multipart / importlib-metadata

**新增风险**：MCP 生态不稳定 / Plugin 安全风险 / RAG embedding 成本 / 多模态上传滥用——每项都有对应缓解措施

**新增测试要求**：MCP/Plugin/RAG/多模态四项各配独立测试文件，符合"测试是 AI 改代码唯一防线"铁律

文档已覆盖原 v1.0 版本，位于 [docs/Roadmap_v2.md](file:///d:/Ragent学习/study-web/docs/Roadmap_v2.md)，后续开发 Agent 按此文档执行即可。