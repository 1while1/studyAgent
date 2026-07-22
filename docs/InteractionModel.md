# 交互模型（InteractionModel）

> 本文档是 study-web 的开发基准：对 `docx/SOP/`（14 条全局规则 + 8 张 SOP 卡）与 `docx/StudyFlow.md` 的形式化核对结论。修改任何流程代码前，先对照本文与 SOP 原文。

## 1. 天级生命周期（Day Lifecycle）

```
未开始 ──[开始今日学习]──> 计划生成(4步) ──> 学习中 ⇄ 编码模式 ⇄ 复盘模式 ──[结束今日学习]──> 已结束
                │                                  ▲
                └── FAIL-FAST: StudyMemory 已存在 → 双选项 STOP（[恢复学习]/重新开始）
[恢复学习] = 从中断单元重入；[跳转天数] = 重置 current_day 后重入
```

## 2. 单元级阶段机（Unit Stage Machine，五步导学循环，规则 13.4）

```
not_started → teaching(文档带读) → coding(Replica编码) → source_review(源码对照)
            → paper(论文带读) → quiz_r1(追问回合1) → quiz_r2(追问回合2)
            → scored(终期评分) → completed
[强制下一内容] 可从 quiz_* 直跳 completed（标记"未掌握-跳过"）
```

阶段定义（与规则 13.4 五步对应）：

| stage | 含义 | 进入条件 | 退出到下一阶段的条件 |
|-------|------|---------|---------------------|
| teaching | 步骤一：文档带读 | 单元开场模板输出后 | AI 判断讲完，用户确认或发 `[开始写代码]` |
| coding | 步骤二：Replica 交互式编码 | 理论讲完（FAIL-FAST） | Demo 跑通（用户自述/同步代码完成） |
| source_review | 步骤三：源码深度对照 | coding 完成 | Why/Where/QA 讲完 |
| paper | 步骤四：论文带读 | source_review 完成 | 核心章节带读完 |
| quiz_r1 | 步骤五-1：第一轮追问（What/How） | 用户说 `[下一内容]` 或五步走完 | 用户提交答案 |
| quiz_r2 | 步骤五-2：第二轮追问（Why/Where 底层） | quiz_r1 点评完成 | 用户提交答案 |
| scored | 终期评分 + 推进征求 | LLM 输出 `【评分：X.X】` | ≥及格线且用户确认 → 落盘 completed |

## 3. 逻辑交叉点（统一建模决策）

| # | 交叉点 | 出处 | 程序建模决策 |
|---|--------|------|-------------|
| 1 | 五步循环步骤二(Replica编码) 与 `[开始写代码]` 是同一阶段两个入口 | 规则13.4 vs SOP_开始写代码 | 统一 `coding` stage；命令 = 显式进入/继续，进入时 FAIL-FAST |
| 2 | 「掌握情况检查」有两个触发源：5-6 轮自动 + `[下一内容]` | 规则2 vs SOP_下一内容 Step1 | 同一渲染函数 `render("mastery_check")`；回合计数器后端维护 |
| 3 | `[下一内容]` 的 4 回合推进 与 quiz_r1/r2/scored 是同一流程 | SOP_下一内容 Step1-4 | 命令 = 推入 quiz_r1，之后由阶段机驱动 |
| 4 | 复盘连环追问 与 单元 2 回合追问同机制不同目的 | SOP_复盘 vs 规则13 | 复用 `QuizEngine`，mode=unit_gate/day_review，题量及格线走配置 |
| 5 | 应急机制（时间压缩/模拟面试/编码卡壳降级）无确定触发器 | StudyFlow §10 | v1 做成显式用户指令/按钮，不自动检测 |
| 6 | AI 主动询问同步的 5 个时机依赖语义判断 | StudyFlow §6.2 | v1 由 LLM 在 system prompt 引导下提示，落盘仍走 `sync` 指令确定性路径 |

## 4. 控制流 vs 内容生成（设计第一原则）

- **代码强制（确定性）**：模板渲染、FAIL-FAST、stage 流转、状态枚举、回合计数、评分标记提取、备份→落盘→validate→回滚、阈值检查
- **LLM 生成（内容）**：讲解正文、追问题目、点评、拷打、StudyReview 正文、论文带读
- 接口约定：LLM 评价类输出必须带 `【评分：X.X】` 标记，后端正则提取；无标记 → 保持"需巩固"不推进（FAIL-FAST）

## 5. 数据层契约

- 事实源：`docx/StudyState.json`；WAL：`docx/StudyMemory/Day_<NN>.md`；派生：`Study.md` / `InterviewQA.md` / `StudyReview/`
- 单元状态枚举：`not_started` / `in_progress` / `completed` / `postponed`
- 任何落盘遵循规则 14：备份（`docx/hooks/backup/`）→ 写入 → `python docx/hooks/validate_study.py` → 失败回滚
- Web 应用与 CLI 助手并行可用：模板以 SOP 卡内 `<!-- template:* -->` 锚点块为唯一可执行版本
