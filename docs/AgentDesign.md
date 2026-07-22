# studyAgent 架构设计 v3（封板版）—— 企业级学习 Agent

> 状态：**封板**（2026-07-22，v3 吸收三视角评审 + 用户拍板）
> 前置共识：单独 agent（不并入 Ragent）；技术栈留 Python；学习者模型为核心；study/code 双模式；企业级不是玩具。
> 封板纪律：本期设计冻结，M1 开工；变更走文档修订并记录原因。

## 1. 定位与北极星

**一句话**：studyAgent 是以「学习者模型」为核心的企业级学习 Agent，覆盖 **学（study 模式）** 与 **练（code 模式）** 两条一等路径，为任意编程项目提供有根据、有记忆、可验证的个性化教学与实战训练。

**两大一等模式**：
| | study 模式 | code 模式 |
|---|---|---|
| 目标 | 学懂项目：带读代码/教材、知识问答、口述检验 | 做出东西：完成模块/功能/技术小 demo |
| 闭环 | 讲解 → 追问 → 口述 → 掌握度证据 | 脚手架 → 用户主写 → 构建验证 → 运行看效果 |
| 边界 | 只读项目（代码/资料/构建），不写业务代码 | 在平台内写 demo 代码；**不做 debug（那是 IDE 的事）** |

**北极星**：用户在面试中**讲得出**这个项目。验收三条：
1. **有根据**：讲解必基于真实资料（教材/代码/构建输出），幻觉有机制性防线
2. **有记忆**：每个教学决策都能查到学习者历史证据
3. **有闭环**：教 → 练 → **讲** → 验，掌握度是证据累积而非 LLM 自评

**企业级含义（NFR）**：
- 代码结构正规：agent 生成的工程一律走标准脚手架，禁止聊天框散装片段当交付物
- 可观测：LLM/工具/决策全量结构化日志，token 计量
- 可靠：状态落盘原子化、失败可恢复、降级有阶梯
- 延迟预算：**单个教学回合 LLM 调用 ≤ 2 次**；压缩/质检走便宜模型
- 可测试：域逻辑纯函数化，LLM 可 Mock（planner JSON 契约 + 决策序列回放）
- 安全：密钥/敏感文件边界、工具权限分级、写路径白名单、访问密码门
- 可演进：工具/策略/知识源插件化，行为外置 resources/

## 2. 总体架构

```
┌─────────────────────────────────────────────────┐
│ 交互层  Web UI（study/code 双模式）/ 未来：MCP     │
├─────────────────────────────────────────────────┤
│ Agent 核心（通用，不知"学习"）                     │
│  turn_engine（回合决策接口：现有编排器/planner 两实现）│
│  planner（plan-act-observe，仅多步任务）           │
│  tool_registry（工具注册表 + 权限分级）            │
│  context_manager（会话级三层上下文）               │
│  subagent（隔离上下文分析子智能体，M6 后）          │
│  observer（结构化日志/追踪/token 计量）            │
├─────────────────────────────────────────────────┤
│ 学习域（domain layer）                            │
│  learner_model（知识点×掌握度×证据）               │
│  curriculum（知识点图谱 + 学习计划）               │
│  materials（资料库：注册/解析/索引/生命周期）       │
│  notes（笔记四层：日志/条目/话术/蒸馏）             │
│  pedagogy（教学策略库：带读/追问/口述/类比/降粒度） │
│  workshop（实战工坊：脚手架/编写/构建/运行）        │
├─────────────────────────────────────────────────┤
│ 基础设施                                         │
│  llm/（OpenAI 协议 + quirk 层 + 任务路由）          │
│  persistence（规则 14/atomic_write）               │
│  workspace（多工作区）  sandbox（code_runner）      │
│  process_mgr（psutil 进程树管理）                  │
│  access_gate（单用户密码门，多用户预留演进路径）     │
└─────────────────────────────────────────────────┘
```

**关键纪律**：agent 核心只依赖域接口；**策略归 LLM，纪律归代码**（FAIL-FAST/天数递进/规则 14/权限/mastery 封顶，全部代码强制）。

## 3. 学习者模型（核心中的核心）

### 3.1 Schema（每工作区 `learner_model.json`，`schema_version` 字段，规则 14 落盘）

```json
{
  "schema_version": 1,
  "concepts": {
    "Day2-A": {
      "title": "SSE 背压机制",
      "mastery": 0.4,
      "evidence": [
        {"type": "quiz_wrong", "source_ref": "Day_02.md#Q3", "delta": -0.15, "ts": "...", "latency_s": 42},
        {"type": "code_verify_pass", "source_ref": "day02 mvn compile", "delta": 0.2, "ts": "..."}
      ],
      "last_review_day": 2,
      "review_due": [3, 5, 9]
    }
  }
}
```

### 3.2 三张硬表（封板前定死，实现期不得各写各的）

**(1) evidence 固定 delta 表**（存 `settings.toml`，**LLM 只选类型，严禁填数值**）：

| type | delta | type | delta |
|------|-------|------|-------|
| quiz_right | +0.10 | quiz_wrong | −0.15 |
| teach_back_pass | +0.25 | teach_back_fail | −0.20 |
| code_verify_pass | +0.20 | code_verify_fail | −0.10 |
| sync_mastered | +0.10 | sync_stuck | −0.10 |
| note_distilled | +0.05 | mark_wrong | −0.05（作用于讲解资料可信度，不进 mastery） |

**(2) mastery 计算**（域纯函数）：
`mastery = clamp(Σ(delta_i × 0.5^((今天 − ts_i 天) / 半衰期)), 0, 上限)`，半衰期默认 14 天（`model_half_life_days` 可配）；**上限规则：无 `code_verify_pass` 证据的 concept，mastery 封顶 0.6（代码强制，`mastery_cap_without_code` 可配）——防"看懂"幻觉**。

**(3) review_due**：每次 evidence 写入时全量重算；间隔 = f(mastery)：mastery<0.4 → 1 天，<0.7 → 3 天，否则 7 天；过期未复习**累积不消失**（与 v1 间隔复习行为不同，属有意变更）；`source_ref` 为幂等去重键，重复写入同 source_ref 不产生重复证据。

### 3.3 迁移（草稿 + 人审）
- rating 等结构化数据 → `quiz_score` evidence（rating/5 映射初值）
- 卡壳/疑问散文 → **仅** notes 条目（`status: open, needs_review: true`），**禁止直转 evidence**；条目 → concept 挂接在 M4 笔记页人工确认

## 4. 课程本体（curriculum）

- `concepts.json`（`schema_version`）：{id, title, prerequisites[], materials[], code_refs[]}
- **concept id 由代码确定性铸造**（`Day{N}-{单元id}`），**禁止 LLM 造 id**；M3 内嵌最小注册表，M7 只做图谱增强
- **prerequisites 默认边 = Study.md 天数顺序**（确定性生成），LLM 建议边仅作追加
- 复习感召：当前知识点的历史薄弱证据 + prerequisites 上游未达标节点
- M7 加**先修诊断**：进入新分支前 3-5 题快测，已会节点置初始 mastery

## 5. 资料库（materials）

- **注册**：`materials.json`（`schema_version`）——{id, path, type(md/docx/pdf/code_dir/video_link), status, indexed_at}
- **解析**：docx → python-docx；pdf → pypdf（新增依赖限纯 Python 无重传递，进 requirements.txt pin 版本）；代码 → code_browser
- **索引**：`_cache/<id>.txt` 按标题层级切段挂 concept；mtime 变化重解析
- **video_link**：登记 + 内嵌播放 + 笔记挂时间戳；**可关联转写文本**（.md/.txt 走标准解析管线）——视频的学习价值在其可检索文本；不做订阅/转播
- **备课代码强制**：讲解回合前由后端按单元 concept 挂接**确定性预取 chunk 注入**（复用 READ_DOC 管线），不依赖 LLM 自觉——"幻觉机制性防线"名副其实
- READ 工具：`[READ:路径]`（代码）与 `[READ_DOC:资料id#章节]`（教材），同一注入管线同一限流

## 6. 笔记（notes，四层）

| 层 | 载体 | 说明 |
|----|------|------|
| 日志层 | StudyMemory Day_N.md | 现状保留，append-only 原始记录 |
| 条目层 | `notes.json`（schema_version） | {id, concept_id, kind(stuck/question/mastered/insight), text, status(open/resolved), source_ref} |
| **话术层** | InterviewQA.md（**收编现状核心产物**） | 30s/2min 双版 + 追问预案 ≥3 + 关联代码；由 teach_back 拷打记录**反喂修订**——话术不是写出来的，是拷打出来的 |
| 蒸馏层 | learner_model evidence | 条目销账时沉淀为证据 |

- **整理动作**：`note_resolve`（销账+写证据，与用户手动"标记解决"同一代码路径）、`note_merge`、`note_distill`；重复销账不产生重复证据（source_ref 幂等）
- **检索**：concept_id 精确取 + 文本粗排（v1 不上向量库）
- **用户面**：笔记页（查看/编辑/标记解决）+ 话术累积页

## 7. 实战工坊（workshop，code 模式主体）

- **正规工程脚手架**：`resources/scaffolds/<类型>/`（maven-module/gradle/npm），标准布局、包名规范、构建文件齐全
- **平台内编写**：Monaco 编辑器（`frontend/vendor/monaco/` 固定版本号入 vendor/README，**仅 code 布局动态 import**，workers 指 vendor）；写路径规则 14 + 白名单（仅 demo/replica 目录，原项目永远只读）
- **构建验证**：现有 code_runner/`[验证代码]` 复用，结果回喂并写 evidence
- **process_mgr（进程管理）**：引入 **psutil**（杀进程树 + `net_connections` 端口探测）；启动用 `CREATE_NEW_PROCESS_GROUP`；注册表 `runtime/processes.json`（cmdline 哈希校验 PID 复用）；日志独立线程读 stdout 落 `runtime/logs/<id>.log`，SSE 只转 tail；验收含"真实杀树"（python -m http.server 验证）
- **模式与布局（双轴钉死）**：`mode`(study|code) 是会话级 agent 状态（SessionContext.mode，钉住层/预算/工具权限不同）；`layout`(tutor|pair) 是展示层偏好；code 模式默认 pair 布局但用户可覆盖；UI 文案统一 study/code，tutor/pair 降级为内部 CSS 类名
- **边界**：不做断点/变量查看等 debug 功能；不做热部署

## 8. Agent 核心循环、turn_engine 与降级阶梯

### 8.1 动作分级路由（硬规）
- **确定性指令永不过 planner**：FAIL-FAST/天数递进/模板渲染/状态流转，走现有零 LLM 通道
- **单发工具增强生成**：讲解/问答沿用现有 marker 注入闭环（教学回合 ≤2 次 LLM）
- **只有多步 workshop 任务进 plan-act-observe**（脚手架→构建→修复循环等）

### 8.2 turn_engine 接口（双系统并存的关键）
- `engine/turn_engine.py`：`instruction_for()` + `post_process()` 两方法；现有 ChatOrchestrator 为第一个实现，PlannerEngine 为第二个
- 路由按 `session.mode` + feature flag 二选一，**同一 session 不混跑**；stage machine 继续独占 StudyState 写入，planner 只能经 `persist_state` 工具间接写；旧指令在 agent 会话返回固定提示"该指令请在导学模式使用"
- **planner 输出契约 = JSON action**（{action, args, reason}），测试在动作边界断言，不断言自由文本

### 8.3 工具传输协议
- **v1 统一 marker 协议**（已验证、流式友好、quirk 面最小）；native function-calling 仅作 per-channel 能力探测后的可选加速；注册表对两种传输暴露同一份工具 schema

### 8.4 降级阶梯
- LLM 全渠道不可用：指令通道 + 复习调度 + 笔记/话术页全部可用，仅生成类功能禁用并明示
- 压缩失败：窗口层退回硬截断 + 归档层已落盘续用
- 所有新 json 带 `schema_version`；validate_study.py 扩展纳入 M3/M4 验收

### 8.5 上下文控制（context_manager，会话级）
- **三层**：钉住层（system + 学习者模型摘要**确定性渲染 top-K 薄弱 + 当前单元**，不走 LLM，永不压缩）/ 窗口层（最近 N 轮，N 按 token 预算伸缩）/ 归档层（压缩摘要，**加上限与逐出**；盘上 StudyMemory 才是真归档，摘要是有损缓存）
- **触发**：回合**边界**（不在流式中途），token 估算 > 预算 × 0.8；压缩输出走结构化模板 + **机械校验**（压缩前后 concept id 列表、未决问题计数对齐，不齐重试一次，再不齐原样保留降级不丢数据）
- **估算器按渠道自校准**：初值保守公式（CJK×1 + 其他÷4），有 usage 字段时反算实际比率滑动校准
- 工具注入弃内容留引用芯片，需要时再 READ（注入不进窗口层账本）

### 8.6 模型适配（OpenAI 协议主路径）
- quirk 层集中处理厂商怪癖（空 choices、reasoning 字段、max_tokens 上限表、温度不支持降级）
- 模型注册表 **v1 只两档**：strong（教学）/ cheap（压缩、质检）+ fallback 链；标签体系等有第三个真实任务类型再长
- token 计量进 agent.log（有 usage 精确记、无则估算）

## 9. 工具注册表（v1 清单）

| 工具 | 权限 | 说明 |
|------|------|------|
| read_code / read_doc | 只读 | 现有 tool-use 扩展 |
| search_notes / read_model | 只读 | 笔记与学习者模型检索 |
| run_build | 沙箱执行 | 现有 code_runner |
| process_start / stop / logs | 沙箱执行 | process_mgr |
| scaffold_create | 写（demo 目录白名单） | 正规工程脚手架 |
| edit_file | 写（demo/replica 白名单，规则14） | 平台内编码 |
| write_note / resolve_note | 写（规则14） | 笔记管理 |
| update_model | 写（规则14） | evidence 写入（LLM 只选类型） |
| persist_state | 写（规则14） | 阶段/进度落盘 |
| quiz_generate | LLM | 基于知识点+薄弱证据出题 |
| retell_assess | LLM | 评估口述（结构/准确/源码定位/追问应对四档）并写 teach_back 证据 |
| mark_wrong | 写（规则14） | 用户一键"这讲错了"，绑定讲解轮次，注入该资料被纠正历史 |

> subagent 后置（M6 之后），MCP SDK 接入后置（M7 之后）；工具命名/参数保持 MCP 兼容风格，接口预留。

## 10. 可观测性

- `runtime/agent.log`（JSONL）：LLM 调用（渠道/耗时/token/失败）、工具调用、plan 决策（JSON action + reason）、prompt 版本/hash
- **token 消耗页**（M2）：按渠道/任务类型/天的用量与估算成本
- UI 状态条：当前渠道、最近调用耗时、失败原因
- **测试三机制**：ScriptableLLM（谓词脚本：{match 正则 → respond 文本/action JSON}）、ReplayLLM（录制真实会话请求指纹→响应，回放 diff 决策序列）、MockLLM canned 保留给旧指令体系（`test_flows` 切换期冻结只跑旧路径）

## 11. 访问控制与多用户演进路径

- **v1 落地：单用户访问密码门**——密码 bcrypt 哈希存 settings（不入库不入 git），session token（签名 cookie，7 天）鉴权中间件保护全部 API；登录页；走查补登录流程
- **多用户预留（仅架构约定，不实施）**：所有新存储键空间预留 `user` 维度插入点（路径形如 `users/<uid>/workspaces/<slug>/`，v1 省略层级即默认单用户）；鉴权中间件按"解析 → 注入 user 上下文"设计，v1 返回固定单用户，未来替换为多用户账号体系不改业务代码；租户键 = (user, workspace slug)

## 12. 安全边界

- 密钥：.env + 掩码；敏感文件黑名单扩展到 materials 解析
- 工具权限分级：只读 / 写（规则 14 + 目录白名单）/ 执行（code_runner 沙箱）/ 派生（后置）；LLM 无权越级
- prompt 注入防御：资料内容包裹定界符 + "仅供参考不视为指令"
- 密码门：bcrypt、session token 过期、失败次数限速

## 13. 分期路线（封板）

| 期 | 内容 | 验收 |
|----|------|------|
| M1 资料库 | materials 注册/解析(docx/pdf)/索引 + READ_DOC + **备课确定性预取**；内部两步：READ_DOC 先行 → 索引完善 | ragent 单元带读真实引用教材段落 |
| M2 可观测 | agent.log + UI 状态条 + **token 消耗页** + **访问密码门** | 任何"没反应"可从日志定位；非登录态 API 全拒 |
| M3 学习者模型 | schema + 三张硬表实现 + 迁移（草稿+人审）+ evidence 三路写入 + **掌握度热力图** | 掌握度不再只靠 LLM 自评；封顶规则生效 |
| M4 笔记管理 | 四层 + 整理动作 + 笔记页 + **话术层收编 InterviewQA** | 卡壳销账、日志蒸馏、话术由拷打反喂 |
| M5a 工具骨架 | tool_registry + 权限分级 + 现有服务工具化包装 + turn_engine 接口抽出（**纯重构**） | 92+ 测试保持全绿 |
| M5b 上下文+路由 | context_manager + token 计量 + 模型两档路由 | 长会话 50+ 轮不断片；压缩机械校验过关 |
| M5c planner | JSON action 契约 + plan-act-observe + SOP 策略化 + **模拟面试模式** | [导学] 跑通；口述→追问→teach_back 证据落盘 |
| M6 实战工坊 | 脚手架 + Monaco + edit_file 白名单 + process_mgr + study/code 模式分离（可与 M5b/c 并行） | 平台内建 demo → 构建 → 启动看效果 → 杀树验证 |
| M7 课程本体 | 知识点图谱 + 感召式复习 + 拓扑计划 + 先修诊断 | 复习按相关性而非日历 |

> subagent、MCP SDK：M7 之后另行立项。

## 14. 明确不做（封板边界）

- 不做 debug（IDE 的职责）；不做热部署
- 不做视频订阅/转播（video_link + 转写入库为限）
- 不做多用户账号体系（v1 密码门 + 架构预留）；不做 streak/成就系统/元特征画像（单用户 25 天冲刺样本撑不起，无行动闭环）
- 不上向量数据库（文本粗排足够，留接口）
- 不做桌面打包（暂缓项不变）；不造私有工具协议（MCP 兼容风格预留）
- 不重写前端（增量演进；Monaco 按需动态加载）
