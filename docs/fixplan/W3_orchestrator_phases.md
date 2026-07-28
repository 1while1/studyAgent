# W3 详细修复计划：orchestrator 策略模式重构（refactor/orchestrator-phases）

> 对应 docs/FixPlan.md 第三波。前提：W2 已合并。
> 核心目标：将 ChatOrchestrator（324行）的 if/elif 分发逻辑拆为策略模式，
> 与 engine/commands/ 已验证架构同构。

## 目录结构

```
backend/engine/phases/
├── __init__.py          # PhaseRegistry + build 函数
├── base.py              # PhaseHandler ABC + 4 个共享 helper（模块级函数）
├── ended.py             # ENDED/NOT_STARTED 短路
├── prereq.py            # PREREQ 先修诊断
├── interview.py         # INTERVIEW 模拟面试
├── reviewing.py         # REVIEWING 复盘拷问（最高风险）
├── quiz_r1.py           # quiz_r1 第一轮
├── quiz_r2.py           # quiz_r2 第二轮
└── studying.py          # else 兜底（回合计数）
```

## 分发机制（双轴）

| 策略 | matches 条件 | 优先级 |
|------|-------------|--------|
| EndedPhase | `day_phase in (ENDED, NOT_STARTED)` | 1（最高） |
| PrereqPhase | `day_phase == PREREQ` | 2 |
| InterviewPhase | `day_phase == INTERVIEW` | 3 |
| ReviewingPhase | `day_phase == REVIEWING` | 4 |
| QuizR1Phase | `current_stage == "quiz_r1"` | 5 |
| QuizR2Phase | `current_stage == "quiz_r2"` | 6 |
| StudyingPhase | 始终 True（兜底） | 7（最低） |

## 四个修正要点

### 1. 双轴分发
PREREQ/INTERVIEW/REVIEWING 走 day_phase 轴，quiz_r1/quiz_r2 走 current_stage 轴，
studying 兜底。每个策略的 matches(session) 独立判断，registry 按优先级遍历。

### 2. REVIEWING 的 atomic_persist+validator 逐字搬运
phases/reviewing.py 的 post_process 必须逐字搬运原 orchestrator.py L160-200：
- recompute_percentage 在 atomic_persist 之前
- files dict 同时含 StudyState.json 和 Study.md
- Study.md 缺失时 try/except 降级（silent_orch_plan）
- make_validator(config) 传入 config
- BackupService.atomic_persist(files, validator=make_validator(...))
- pending_qa_capture = True 在 day_phase 赋值之后
- silent_orch_review try/except 范围正确

### 3. 共享 helper 下沉 phases/base.py
- current_unit_title(state_store, session)
- next_unit_title(state_store, session)
- interview_title(config, state_store, session)
- record_teach_back(quiz, state_store, config, session, score, extra)
- render_mastery_check 保留在 commands/base.py，phases 直接 import

### 4. 铁律 15 静默语义 + pending_qa_capture 原样保留
- except Exception 保持 observer.log_tool("silent_orch_*", ...) 模式
- pending_qa_capture = True 仅在 ReviewingPhase.post_process 中设置

## 实施步骤

### Step 1: 创建骨架
- phases/base.py: PhaseHandler ABC + 4 个共享 helper
- phases/__init__.py: PhaseRegistry（ordered list + dispatch）
- 不改 orchestrator.py

### Step 2: 迁移 quiz_r1/r2 + studying + ended
- 创建 4 个策略文件
- 修改 orchestrator.py 删除对应分支
- 验证 536 测试全绿

### Step 3: 迁移 INTERVIEW
- 创建 interview.py
- 验证 test_interview.py + 全量 536

### Step 4: 迁移 REVIEWING（最高风险）
- 创建 reviewing.py（atomic_persist 逐字搬运）
- 验证 test_flows TestReviewScore + test_qa_capture + validate + 全量 536

### Step 5: 迁移 PREREQ
- 创建 prereq.py
- 验证 test_prereq.py + 全量 536

### Step 6: 清理 orchestrator.py 为薄壳
- ChatOrchestrator 瘦身为 ~30 行
- 验证全量 536

### Step 7: 新增测试 + 三件套验证
- tests/test_phase_registry.py
- 536+N 单测绿 + validate SUCCESS + 走查 187 全 PASS

## 关键约束

- ChatOrchestrator 构造签名不变：(config, stages, quiz, state_store, memory, templates)
- 外部调用者零改动：routes.py、app.py 通过 TurnEngine 接口调用
- 536 测试零断言改动
- phases 之间禁止互相 import
- render_mastery_check 保留在 commands/base.py

## 不做

- 不动 API 契约、不动前端
- 不改 TurnEngine 接口
- 不改 commands/ 目录
- 不引入新依赖
