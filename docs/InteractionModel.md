# 交互模型（InteractionModel）

> 设计基准：改流程代码前必读。基于当前代码的形式化描述，非散文。

## 1. 天级生命周期（DayPhase）

```
NOT_STARTED ─[开始今日学习]─→ PLANNING(4步) ─→ PREREQ? ─→ STUDYING ⇄ REVIEWING ─[结束今日学习]─→ ENDED
                                                         ├─ INTERVIEW（M5c 模拟面试）
                                                         └─ 复盘后 pending_qa_capture → 拷打反喂
```

| DayPhase | 枚举值 | 含义 |
|----------|--------|------|
| NOT_STARTED | `not_started` | 当日未开始 |
| PLANNING | `planning` | 4 步计划生成中 |
| PREREQ | `prereq_diagnosing` | 先修诊断中（M7） |
| STUDYING | `studying` | 导学中（含回合复习） |
| INTERVIEW | `interviewing` | 模拟面试中（M5c） |
| REVIEWING | `reviewing` | 今日复盘拷打中 |
| ENDED | `ended` | 已结束 |

- NOT_STARTED / ENDED：orchestrator 不注入任何阶段附加指令，不做 post_process。
- PREREQ / INTERVIEW / REVIEWING：由 PhaseRegistry 分发到对应 Phase handler。

## 2. 单元阶段机（StageMachine）

阶段定义与流转全部由 `settings.toml [[stages]]` 数据驱动，代码不含 stage 字面量。

```
teaching → coding → source_review → paper → quiz_r1 → quiz_r2 → scored → completed(终态)
```

约定：
- `name` 以 `quiz_` 开头 = 掌握度考核回合（QuizEngine 接管）
- `next` 为空串 = 终态
- 每个 stage 携带 `instruction`（LLM 附加指令）与 `sop_step`（显示名）
- `[强制下一内容]` 可从 quiz_* 直跳 completed（标记"未掌握-跳过"）

## 3. 双引擎架构

```
TurnEngine (ABC)
├── instruction_for(session, user_text) → str   # 生成 LLM 附加指令
└── post_process(session, assistant_text) → list[str]  # 回复后状态处理

路由：session.mode + agent_mode_enabled
├── study → ChatOrchestrator（导学引擎）
└── code  → PlannerEngine（agent 模式，ACTION 契约 + plan-act-observe）
```

**PhaseRegistry**（策略模式，W3）：按优先级 `matches(session)` 分发。

注册顺序：EndedPhase → PrereqPhase → InterviewPhase → ReviewingPhase → QuizR1Phase → QuizR2Phase。
StudyingPhase 暂不注册（回合计数由 orchestrator else 分支处理）。

**双轴**：`session.day_phase`（PREREQ / INTERVIEW / REVIEWING）+ `session.current_stage`（quiz_r1 / quiz_r2）。

## 4. 指令系统

### 4.1 导学指令（13 条，`settings.toml [commands]`）

| 指令 | handler | 模式 |
|------|---------|------|
| 开始今日学习 | start_day | — |
| 恢复学习 | resume | — |
| 下一内容 | next_content | — |
| 强制下一内容 | next_content | force |
| 超前学习 | next_content | ahead |
| 同步 | sync | — |
| 开始写代码 | code_mode | — |
| 验证代码 | verify_code | — |
| 模拟面试 | interview | — |
| 先修诊断 | prereq | — |
| 开始今日复盘 | day_review | — |
| 结束今日学习 | end_day | — |
| 跳转天数 | jump_day | — |

声明式（`handler = "declarative"`）走通用解释器；其余为 `commands/` 下代码 handler。

### 4.2 Slash 指令（前端 `/` 前缀，`/api/slash` 路由）

`/clear`（清屏+后端历史归零）、`/model`（切换 LLM 渠道）、`/usage`（用量统计）、`/compact`（手动上下文压缩）。

## 5. 工具使用协议（tool_use.py）

三种标记，同一注入管线：
- `[READ:路径:L起-止]` — 读项目代码（经 CodeBrowser）
- `[READ_DOC:资料id#章节]` — 读学习资料（经 MaterialsService）
- `[ACTION:{"action":"工具名","args":{...},"reason":"..."}]` — planner 动作契约

限流：READ/READ_DOC 合计 ≤ `ai_read_max_per_reply`（3）；ACTION ≤ `planner_max_actions_per_reply`（4）；单次注入 ≤ `ai_read_max_lines`（200 行）。

### 5.1 ToolRegistry 权限四级

| 权限 | 含义 | 工具 |
|------|------|------|
| READONLY | 只读 | read_code, read_doc, search_notes, read_model |
| WRITE | 规则 14 落盘 | write_note, resolve_note, update_model, persist_state, mark_wrong, scaffold_create, edit_file |
| SANDBOX | 沙箱执行 | run_build, process_start, process_stop, process_logs |
| LLM | 派生 LLM 调用 | quiz_generate, retell_assess |

- 写类工具全走规则 14（atomic_persist + validator）
- `update_model` 的 etype 只允许 `[evidence_delta]` 表内类型（铁律 15）
- `persist_state` 白名单操作集：`set_unit_status`（completed 不可用）
- MCP 工具适配器规划中（同一 ToolSpec 导出 marker / native 两种传输 schema）

## 6. 数据层契约

| 类别 | 路径 | 说明 |
|------|------|------|
| 学习状态 | `<docx_dir>/StudyState.json` | 事实源（单元状态/天数/进度） |
| 学习文档 | `<docx_dir>/Study.md` | 每日学习记录 |
| 日记忆 | `<docx_dir>/StudyMemory/Day_NN.md` | WAL 式日志 |
| 概念图 | `<docx_dir>/concepts.json` | 知识点定义 |
| 学习者模型 | `<docx_dir>/learner_model.json` | 掌握度+证据 |
| 笔记 | `<docx_dir>/notes.json` | 卡壳/疑问/心得 |
| 资料库 | `<docx_dir>/materials.json` + `<docx_dir>/materials/_cache/` | 注册资料+解析缓存 |
| 运行时 | `runtime/session.json` | 会话上下文（与 docx 状态分离） |
| 日志 | `runtime/agent.log` | 全量事件日志 |

- 单元状态枚举：`not_started` / `in_progress` / `completed` / `postponed`（`settings.toml status_enum`）
- 落盘规则 14：备份 → 写入 → `validate_study.py 25 ragent-replica` → 失败回滚

## 7. 上下文三层（ContextManager）

| 层 | 内容 | 特性 |
|----|------|------|
| 钉住层 | system prompt + 学习者模型摘要（top-K 薄弱 + 当前单元） | 确定性渲染，永不压缩 |
| 窗口层 | 最近 N 轮对话 | 按生效预算伸缩，条数硬兜底 `max_messages` |
| 归档层 | 压缩摘要（`archive_max_chars` 上限 + 前部逐出） | 有损缓存，StudyMemory 才是真归档 |

预算：`effective_budget = max(1024, min(budget_tokens, model_limit − max_tokens))`
触发：未归档历史 > 可用预算 × `trigger_ratio`(0.8) → 窗口收缩到 可用预算 × 0.5（低水位滞回）
失败：`compress_cooldown`（默认 3 回合）防重试风暴；cheap 失败 → strong 重试一次

## 8. 关键交叉点

| # | 交叉点 | 建模决策 |
|---|--------|---------|
| 1 | `pending_score` | LLM 输出 `【评分：X.X】` 后暂存，quiz_r2 post_process 提取 → scored 阶段确认落盘 |
| 2 | `pending_qa_capture` | 复盘评分落盘后置 True → 下次 orchestrator 触发拷打反喂（QA 提炼到 InterviewQA.md） |
| 3 | `day_phase` vs `current_stage` | day_phase 为天级宏观状态；current_stage 为单元内微观阶段；STUDYING 内由 stage_machine 驱动流转 |
| 4 | 回合复习 vs quiz | STUDYING 中每 5-6 轮自动渲染掌握情况检查（`render_mastery_check`）；`[下一内容]` 推入 quiz_r1 |
| 5 | `interview_cid` / `interview_round` / `interview_score` | 面试独立于 quiz 的 `pending_score`（R4 分离） |
| 6 | `mode` (study/code) | 引擎路由依据：study → ChatOrchestrator，code + agent_mode_enabled → PlannerEngine |
