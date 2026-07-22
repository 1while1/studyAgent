# SOP: [同步] XXX

## 触发场景

用户说 `[同步] <子类型> <内容>`，5 种子类型：

| 子类型 | 用途 | 写入位置 |
|--------|------|---------|
| `已掌握` | 标记已掌握 | StudyMemory「已掌握」字段 |
| `卡壳` | 标记薄弱点 | StudyMemory「卡壳」字段 + 复盘重点 |
| `疑问` | 标记疑问 | StudyMemory「疑问」字段，AI 优先解答 |
| `面试话术` | 追加面试问答 | `docx/InterviewQA.md` |
| `代码完成` | 标记模块完成 | StudyMemory「代码完成」+ `ReplicaPlan.md` |

---

## 执行前必读（MUST READ）

1. `docx/SOP/_GLOBAL_RULES.md`
2. `docx/SOP/SOP_同步.md`（本卡）
3. `docx/StudyFlow.md` 第 6 节（[同步] 机制）
4. 对应活跃天的 `docx/StudyMemory/Day_N.md` (以 JSON 状态中的 current_day 为准)
5. （仅 `面试话术` 子类型）`docx/InterviewQA.md`
6. （仅 `代码完成` 子类型）`docx/ReplicaPlan.md`

---

## FAIL-FAST 自检

- [ ] 子类型是否在 5 种之内？（不在则提示用户"未识别子类型，可选：已掌握/卡壳/疑问/面试话术/代码完成"）
- [ ] 内容是否为空？（空则提示用户补充）
- [ ] `docx/StudyState.json` 是否存在，且当前活跃天对应的 `docx/StudyMemory/Day_N.md` 是否存在？（不存在则提示先 `[开始今日学习]`）

---

## 步骤（MUST 按顺序）

### Step 1: 解析子类型并落盘

**落盘前置（按 `_GLOBAL_RULES.md` 规则 14）**：任何分支修改文件前，**必须**先将目标文件备份到 `docx/hooks/backup/`（同文件名加 `.bak` 后缀）；落盘后涉及 `StudyState.json` 或单元进度的修改，**必须**运行 `python docx/hooks/validate_study.py`，失败则用备份恢复并报告错误。

按子类型走对应分支：

#### 分支 A: `[同步] 已掌握 XXX`

1. Edit StudyMemory「已掌握」字段，追加 `XXX`
2. 输出确认：

<!-- template:sync_mastered -->
```
已记录：「<XXX>」标记为已掌握。
```
<!-- /template:sync_mastered -->

#### 分支 B: `[同步] 卡壳 XXX`

1. Edit StudyMemory「卡壳」字段，追加 `XXX`
2. 当前对话内补一次讲解（用不同方式：画图/类比/对比）
3. 输出确认：

<!-- template:sync_stuck -->
```
已记录卡壳：「<XXX>」，复盘时会重点拷问。
我再用 <画图/类比/简化> 方式讲一遍：
<重新讲解>
```
<!-- /template:sync_stuck -->

**禁止**：只记录不重新讲解。

#### 分支 C: `[同步] 疑问 XXX`

1. Edit StudyMemory「疑问」字段，追加 `XXX（待解答）`
2. 立即解答（不等到复盘）
3. 解答后 Edit 改为 `XXX（已解答）`
4. 输出：

<!-- template:sync_question -->
```
你的疑问：<XXX>
我的解答：
<解答内容>

已记录到 StudyMemory，标记为「已解答」。
```
<!-- /template:sync_question -->

#### 分支 D: `[同步] 面试话术 XXX`

1. Read `docx/InterviewQA.md`
2. 按 StudyFlow.md 第 12 节模板，Edit 追加：

<!-- template:interview_qa_entry -->
```markdown
## <问题标题>

**标签**：#<模块> #<技术点>
**关联代码**：`<文件路径>:<行号>`

**精简版（30秒）**：
<内容>

**展开版（2分钟）**：
<内容>

**追问预案**：
- Q: <追问 1>
  A: <答 1>
- Q: <追问 2>
  A: <答 2>
- Q: <追问 3>
  A: <答 3>

**产出来源**：Day <N> <场景>
```
<!-- /template:interview_qa_entry -->

3. **必须**生成 ≥ 3 个追问预案（少于 3 个 = 违规）

**写入前自检清单**（任一不通过禁止落盘，按 `_GLOBAL_RULES.md` 规则 7）：
- [ ] `## <问题标题>` 二级标题 `##` 保留（不可改为纯文本）
- [ ] 5 处 `**标签**：` `**关联代码**：` `**精简版（30秒）**：` `**展开版（2分钟）**：` `**追问预案**：` 加粗 `**` 全部保留
- [ ] `**产出来源**：` 加粗保留
- [ ] 关联代码字段中行内代码反引号 `` ` `` 保留
- [ ] 追问预案 3 组 `- Q: ... A: ...` 列表项 `- ` 保留
- [ ] 占位符 `<问题标题>` `<模块>` `<技术点>` `<文件路径>:<行号>` `<内容>` `<追问>` `<答>` 已替换为实际值

4. 输出确认：

```
已追加面试话术到 InterviewQA.md：
- 标题：<问题标题>
- 追问预案：<3 个简列>
```

#### 分支 E: `[同步] 代码完成 XXX`

1. Edit StudyMemory「代码完成」字段，追加 `XXX 模块`
2. Edit `ReplicaPlan.md` 对应模块状态从「进行中」改为「已完成」
3. 提问验证：

<!-- template:sync_code_done -->
```
模块「<XXX>」标记为完成。请用 30 秒口述这个模块的设计思路。

（我会判断你是否真懂，不懂的话回滚 [同步]）
```
<!-- /template:sync_code_done -->

4. 用户回答后：
   - 讲清楚 → 保留同步
   - 没讲清楚 → 回滚 Edit，回复"看起来还没真正理解，回到源码导读"

### Step 2: 输出综合确认

任何子类型完成后，输出一句话总结：

<!-- template:sync_summary -->
```
[同步] 已落盘：<位置>
当前 StudyMemory 状态：已掌握 <X> 项 / 卡壳 <Y> 项 / 疑问 <Z> 项
```
<!-- /template:sync_summary -->

---

## 禁止行为（FORBIDDEN）

- ❌ `[同步] 卡壳` 时只记录不重新讲解
- ❌ `[同步] 疑问` 时只记录不立即解答
- ❌ `[同步] 面试话术` 时追问预案少于 3 个
- ❌ `[同步] 代码完成` 时不验证用户能否口述
- ❌ 在内存中"记着"不立即写入文件

---

## 完成判据（POST-CONDITIONS）

- [ ] 对应文件已 Edit 并落盘
- [ ] 子类型对应的额外动作已完成（卡壳 → 重讲；疑问 → 解答；代码完成 → 验证）
- [ ] Step 2 综合确认已输出
