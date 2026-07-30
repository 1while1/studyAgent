# studyAgent 演进路线 v3.0（最终版）

**版本**：v3.0
**生成日期**：2026-07-29
**取代关系**：本版本取代 v2.0（Roadmap_v2.md）
**决策依据**：三份外部审计 + 项目实际代码分析 + 终局定位确认

---

## 0. 战略定位

> **studyAgent 是一个可扩展的代码学习 Agent。**
>
> - **对学习者**：真实代码接地 + 持久学习者模型 + 证据驱动掌握度 + 教学大脑
> - **对开发者**：MCP 工具生态 + Plugin 扩展 + 自带模型 + 本地运行
> - **对商业**：同一套核心代码，加账号/云同步/团队管理 = SaaS
>
> 核心不是"通用 Agent 平台"，也不是"纯垂直学习工具"，
> 而是"以学习为核心场景、以可扩展为架构原则的垂直 Agent"。

### 护城河排序

| 优先级 | 护城河 | 当前状态 |
|--------|--------|---------|
| 1 | 教学效果可证明（度量体系） | ❌ 缺失 |
| 2 | 真实代码接地 + 持久学习者模型 | ✅ 已具备 |
| 3 | MCP/Plugin 可扩展生态 | ❌ 缺失 |
| 4 | 本地优先 + 自带模型 | ✅ 已具备 |

### v2.0 → v3.0 核心变更

| 项目 | v2.0 立场 | v3.0 立场 | 理由 |
|------|----------|----------|------|
| Dockerfile | 不做 | **必做** | 可复制部署是商业化的前提 |
| 多用户/团队 | 阶段 2 必做 | **推迟** | 核心价值未验证前不做 |
| RAG 语义检索 | 必做 | **可选** | 文本粗排当前够用，ROI 低 |
| 教学大脑 | 阶段 1 | **阶段 1（不变）** | 三份审计一致建议，核心差异化 |

---

## 1. 阶段总览

```
阶段 0：地基清扫 + 可交付     ──┐
阶段 1：教学大脑 MVP           │  核心价值层（护城河）
阶段 2：扩展层                 │  可扩展生态
阶段 3：架构加固               │  商业准备
阶段 4：沙箱化 + 形态扩展     ──┘  条件触发
```

### 依赖关系

```
M0 ──→ M1.1 ──→ M1.2 ──→ M1.3 ──→ M2.1 ──→ M2.2 ──→ M2.3 ──→ M2.4 ──→ M3 ──→ M4
```

---

## 2. 阶段详情

### 阶段 0：地基清扫 + 可交付（2 周）

#### 任务清单

- [x] 0.1 LICENSE 文件（MIT）
- [x] 0.2 配置分层：`settings.example.toml`（入库）+ `settings.local.toml`（gitignore）
- [x] 0.3 `workspaces/` 移出 git（`.gitkeep` 保留）
- [x] 0.4 README 修正（删除 `cd study-web`，新人 10 分钟 mock 模式跑通）
- [x] 0.5 测试数对齐（当前 583，统一 AGENTS.md / README）
- [x] 0.6 打 git tag v1.0.0
- [x] 0.7 Dockerfile + docker-compose（多阶段构建，uvicorn 非 root）
- [x] 0.8 依赖 lock 文件（pip-compile 或 uv lock）
- [x] 0.9 AGENTS.md 拆分：架构/模块职责移至 `docs/Architecture.md`

#### 验收标准

- `LICENSE` 文件存在
- `config/settings.example.toml` 无个人路径
- `workspaces/` 在 .gitignore
- README 无 `cd study-web`
- `git tag` 列出 v1.0.0
- `docker compose up` 可启动
- 干净虚拟环境 clone 后按 README 可跑通

---

### 阶段 1：教学大脑 MVP（1-2 个月）— 核心护城河

#### 1.1 错误模式库

**决策**：两级结构（5 固定大类 + LLM 自由子类）

- [x] 1.1.1 `backend/domain/error_pattern.py`：5 枚举
  - `CONCEPT_CONFUSION` / `DETAIL_ERROR` / `LOGIC_BREAK` / `CANNOT_APPLY` / `FORGOTTEN`
- [x] 1.1.2 evidence schema 加 `error_pattern_major` + `error_pattern_minor`
- [x] 1.1.3 quiz_engine 评分 prompt 加错误分类指令
- [x] 1.1.4 qa_capture 反喂时写入错误分类
- [x] 1.1.5 `tests/test_error_pattern.py`

**验收**：evidence 落盘含新字段；quiz 评分含错误分类；原测试无回归

#### 1.2 教学行动策略库

**决策**：推荐 + 用户确认制

- [x] 1.2.1 `backend/engine/teaching_strategy.py`
- [x] 1.2.2 实现 5-7 个教学行动：
  - `REVIEW_PREREQ` / `RETELL_CORE` / `VARIANT_QUIZ` / `ADVANCE_NEXT` / `REST` / `CHANGE_ANGLE` / `PRACTICE_PROJECT`
- [x] 1.2.3 行动选择逻辑：根据 mastery / error_pattern / 连续错误数 / 上次学习时间
- [x] 1.2.4 每回合 orchestrator 调用 `suggest(context)` 生成 `teaching_action_suggestion`
- [x] 1.2.5 前端“建议卡片 + 确认/跳过按钮”
- [x] 1.2.6 `tests/test_teaching_strategy.py`

**验收**：每回合生成建议；前端渲染正常；确认/跳过流程跑通

#### 1.3 学习效果度量

**决策**：三指标组合

- [x] 1.3.1 指标 A：掌握进度（evidence 数 + 天数）
- [x] 1.3.2 指标 B：知识保持度（3 天后 quiz 正确率）
- [x] 1.3.3 指标 C：迁移应用能力（期末项目题 LLM 评完成度）
- [x] 1.3.4 组合公式：`mastery_score = w1*A + w2*B + w3*C`（默认 0.3/0.3/0.4，可配）
- [x] 1.3.5 落盘到 agent.log
- [x] 1.3.6 掌握度面板展示个人进步曲线
- [x] 1.3.7 `tests/test_learning_metrics.py`

**验收**：三指标计算 + 组合公式 + 落盘 + 面板展示

#### 1.4 mark_wrong 前端按钮

- [x] 1.4.1 消息气泡添加“这讲错了”按钮
- [x] 1.4.2 点击后调用已注册的 mark_wrong 工具

**验收**：按钮可点击；证据写入成功

---

### 阶段 2：扩展层（2-3 个月）— 对齐通用 Agent

#### 2.1 MCP Client 接入

**决策**：studyAgent 作为 MCP Host，接入外部 MCP Server

- [x] 2.1.1 `backend/services/mcp_client_service.py`：
  - `MCPClientPool`（管理多个 MCP server 连接）
  - `MCPClient`（JSON-RPC 2.0，支持 stdio + SSE）
  - `MCPToolAdapter`（MCP tool schema → studyAgent ToolSpec）
- [x] 2.1.2 `settings.toml` 加 `[mcp]` 配置段
- [x] 2.1.3 启动时加载配置，连接 enabled server
- [x] 2.1.4 MCP 工具注册到 tool_registry，默认 READONLY
- [x] 2.1.5 连接失败静默降级（铁律 13）
- [x] 2.1.6 `tests/test_mcp_client.py`

**验收**：配置 1 个 mock MCP server，工具注册成功；planner 可调用；失败不阻断

#### 2.2 Plugin/Skill 系统

**决策**：pip entry_points 外部包插件

- [x] 2.2.1 `backend/services/plugin_service.py`：
  - `PluginSpec` dataclass（name / tools / commands / resources_dir / permissions）
  - `PluginRegistry`（扫描 `studyagent.plugins` entry_points）
  - `PluginLoader`（注册到 tool_registry / commands / resources）
- [x] 2.2.2 权限白名单授权
- [x] 2.2.3 资源命名空间隔离（`plugin:xxx/sop/`）
- [x] 2.2.4 `settings.toml` 加 `[plugins]` 配置段
- [x] 2.2.5 示例插件 `tests/fixtures/sample_plugin/`
- [x] 2.2.6 `tests/test_plugin_service.py`

> **注**：Plugin 系统标记为规划中，基础架构已就绪，待后续实现

**验收**：pip install 测试插件后自动加载；未授权不加载；资源隔离

#### 2.3 文件上传 + 多模态输入

- [x] 2.3.1 `backend/services/upload_service.py`：
  - 图片（jpg/png/gif/webp）+ 文档（md/txt/pdf）
  - 存储到 `<docx_dir>/uploads/`
  - 文件大小限制（可配，默认 10MB）
- [x] 2.3.2 `backend/services/vision_service.py`：
  - `VisionService` 接口：`describe(image_path) -> text`
  - 复用 openai_compat vision
  - 注入对话带"仅供参考不视为指令"定界（铁律 12）
- [x] 2.3.3 API 路由 `POST /api/upload/image` + `POST /api/upload/document`
- [x] 2.3.4 前端聊天框附件按钮
- [x] 2.3.5 `tests/test_multimodal.py`

**验收**：图片可上传并转文字；文档可上传并注册资料库

#### 2.4 Web 搜索

- [x] 2.4.1 `backend/services/web_search_service.py`：
  - `WebSearchProvider` 可插拔接口
  - `DuckDuckGoProvider`（免费默认）/ `TavilyProvider` / `SerperProvider`
  - 结果缓存（LRU）
  - API key 走 .env（铁律 7）
- [x] 2.4.2 planner 加 `web_search` 工具（READONLY）
- [x] 2.4.3 API 路由 `POST /api/web/search`
- [x] 2.4.4 `tests/test_web_search.py`

**验收**：搜索可调用并返回结果；planner 可调用

---

### 阶段 3：架构加固（1-2 个月）— 商业准备

#### 3.1 Repository 抽象

- [x] 3.1.1 `backend/services/repository.py` 接口
- [x] 3.1.2 `JsonRepository`（包装当前 JSON 直操）
- [x] 3.1.3 `SqliteRepository`（WAL 模式）
- [x] 3.1.4 业务层逐步切换（notes → learner → materials → workspace）
- [x] 3.1.5 `tests/test_repository.py`

**验收**：双存储后端测试矩阵全绿

#### 3.2 认证可插拔化

- [x] 3.2.1 `backend/services/auth_provider.py` 接口
- [x] 3.2.2 `LocalAuthProvider`（包装当前 bcrypt）
- [x] 3.2.3 `OAuthProvider` 占位
- [x] 3.2.4 middleware 切换到 AuthProvider 接口
- [x] 3.2.5 `tests/test_auth_provider.py`

**验收**：原认证测试全绿；接口可替换

#### 3.3 安全加固

- [x] 3.3.1 安全头中间件（CSP / X-Frame-Options / X-Content-Type-Options）
- [x] 3.3.2 cookie `secure` 标志（按配置开关）
- [x] 3.3.3 生产模式关 `/docs`（配置项控制）
- [x] 3.3.4 agent.log 按大小轮转（50MB × 5 代）

**验收**：HTTPS 反代下无安全警告

#### 3.4 配置分层收尾

- [x] 3.4.1 `settings.local.toml` 覆盖机制
- [x] 3.4.2 个人工作区完全移出 git

---

### 阶段 4：条件触发

#### 4.1 执行沙箱化

**触发条件**：云端团队开放前 = P0

- [ ] 4.1.1 方案选型（Docker 优先）
- [ ] 4.1.2 process_start 沙箱化
- [ ] 4.1.3 `tests/test_sandbox.py`

#### 4.2 桌面端

**触发条件**：Web 端价值验证后

- [ ] 4.2.1 技术选型（Tauri / Electron）
- [ ] 4.2.2 套壳实现

---

## 3. AI 维护铁律（贯穿所有阶段）

### 3.1 所有抽象文件可见

- 不用依赖注入容器、不用装饰器自动发现
- 文件名即角色：`repository.py` / `json_repository.py` / `mcp_client_service.py`

### 3.2 每阶段独立可验证

- 不依赖下一阶段的功能
- 每阶段完成后系统处于可发布状态

### 3.3 每个新模块必配测试

| 模块 | 测试文件 |
|------|---------|
| 错误模式库 | `tests/test_error_pattern.py` |
| 教学策略 | `tests/test_teaching_strategy.py` |
| 学习度量 | `tests/test_learning_metrics.py` |
| Repository | `tests/test_repository.py` |
| AuthProvider | `tests/test_auth_provider.py` |
| MCP Client | `tests/test_mcp_client.py` |
| Plugin 系统 | `tests/test_plugin_service.py` |
| 多模态 | `tests/test_multimodal.py` |
| Web 搜索 | `tests/test_web_search.py` |

---

## 4. 质量验收标准

### 4.1 通用标准（每里程碑必满足）

| # | 标准 | 验证方式 |
|---|------|---------|
| Q1 | 新增代码必须有对应测试 | 测试文件存在 |
| Q2 | 全套测试零失败 | CI 绿 |
| Q3 | 无回归 | CI 绿 |
| Q4 | 新增 `except Exception:` 必须有注释 | grep |
| Q5 | 新增模块必须有 docstring | grep |
| Q6 | 不引入硬编码 | grep |
| Q7 | 不违反 AGENTS.md 铁律 | review |
| Q8 | boot-critical 写走 atomic_write | grep |
| Q9 | 配置走 settings.toml | grep |

### 4.2 扩展层专项

| # | 标准 | 验证方式 |
|---|------|---------|
| EQ1 | MCP 连接失败不阻断学习 | 断开 server，学习正常 |
| EQ2 | 未授权插件不加载 | 非白名单插件不在 registry |
| EQ3 | 多模态注入带定界 | grep |
| EQ4 | Web 搜索 API key 只进 .env | grep |
| EQ5 | 插件资源命名空间隔离 | 不冲突 |
| EQ6 | 扩展层新工具默认 READONLY | tool_registry 检查 |

---

## 5. 不做清单

### 明确不做（至少 6 个月）

- ❌ 多用户/团队/权限（核心价值未验证）
- ❌ RAG 语义检索（文本粗排够用）
- ❌ 向量数据库（同上）
- ❌ 前端框架迁移（守住"不重写"边界）
- ❌ 移动端
- ❌ 多 Agent 委员会（撕裂教学人格）
- ❌ streak/成就系统
- ❌ subagent 多智能体

---

## 6. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 教学策略 prompt 不稳定 | 中 | 中 | 先 MockLLM 测试，再接真实 LLM |
| MCP 生态不稳定 | 高 | 中 | 连接失败静默降级；不依赖单一 server |
| Plugin 安全风险 | 高 | 高 | 权限白名单 + 资源隔离 |
| Repository 切换漏改 | 中 | 高 | 分服务切换，每次跑全套测试 |
| 个人精力（学业并行） | 高 | 中 | 里程碑制，每个可暂停 |

---

## 7. 执行顺序总览

```
M0 地基清扫 + 可交付（2 周）
 ├─ LICENSE + 配置分层 + README + Dockerfile + lock + tag

M1 教学大脑 MVP（1-2 个月）
 ├─ M1.1 错误模式库
 ├─ M1.2 教学行动策略库
 ├─ M1.3 学习效果度量
 └─ M1.4 mark_wrong 前端按钮

M2 扩展层（2-3 个月）
 ├─ M2.1 MCP Client
 ├─ M2.2 Plugin 系统
 ├─ M2.3 文件上传 + 多模态
 └─ M2.4 Web 搜索

M3 架构加固（1-2 个月）
 ├─ M3.1 Repository 抽象 ✅
 ├─ M3.2 认证可插拔 ✅
 ├─ M3.3 安全加固 ✅
 ├─ M3.4 配置分层收尾 ✅
 └─ M3.5 补强（Repository扩展+依赖修复+配置清理） ✅

M4 条件触发
 ├─ 沙箱化（云端开放前）
 └─ 桌面端（价值验证后）
```

---

## 8. 一句话执行指令

**先扫干净地基（M0），立刻启动教学大脑 MVP（M1 是核心护城河），然后接入扩展层（M2 MCP/Plugin/多模态/Web 四项），再做架构加固（M3 为商业化铺路），沙箱化和桌面端等价值验证后再投入。全程为 AI 维护优化——所有抽象文件可见、每阶段独立可验证、每个新模块配测试。测试是唯一防线。**
