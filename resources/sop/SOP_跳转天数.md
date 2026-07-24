# SOP: [跳转天数]

## 触发场景

用户说 `[跳转天数] Day <X>` 或 `[跳转天数] <X>`，强制调整活跃天数进度并重置学习路线图。

---

## 执行前必读（MUST READ）

按顺序 Read：
1. `docx/StudyState.json`
2. `docx/SOP/_GLOBAL_RULES.md`
3. `docx/SOP/SOP_跳转天数.md`（本卡）
4. `docx/Study.md`

---

## FAIL-FAST 自检

- [ ] 输入的跳转天数 `<X>` 是否在 1 到 25 之间？（不在则提示“跳转天数超出范围，必须在 1-25 之间”）
- [ ] `docx/StudyState.json` 文件是否可读写？

---

## 步骤（MUST 按顺序）

### Step 1: 修改 JSON 状态
1. 读取 `docx/StudyState.json`。
2. 将 `current_day` 字段更新为 `<X>`。
3. 将 `active_day_completed` 设为 `false`。
4. 在 `days` 对象中，确保存在键 `"<X>"`：
   * 若不存在：初始化该天的基本结构（含 `units` 列表为空、`sync_records` 等）。
   * 若已存在：询问用户：“检测到 Day <X> 已有历史进度。重置该天进度？回 [是] 重置 / [否] 保留历史继续。”
5. 将 Day `<X>` 之前的所有天数在 JSON 中标记为已完成（若无历史记录，初始化为空完成态）；将 Day `<X>` 之后的所有天数记录清除或置为 pending。
6. 计算并更新 `overall_completion_percentage` 值为 `((X - 1) / <总天数>) * 100`。
7. 覆写更新 `docx/StudyState.json`。

### Step 2: 调整 Study.md 与物理文件
1. Read `docx/Study.md`。
2. 更新其整体完成度百分比。
3. 将 Day `<X>` 下的标题加上进行中标记，将 Day `<X>` 之后的所有已完成（✅）标记清除。
4. 如果有历史 `docx/StudyMemory/Day_<XX>.md` 文件且用户选择重置，将其重新初始化为 Day X 的初始模板。

### Step 3: 生成跳转后计划并导学
1. 提取 `Study.md` 中 Day `<X>` 的内容大纲，进行细化，在 JSON 中存入单元列表。
2. 输出跳转确认模板并开始讲解第一个单元：

<!-- template:jump_confirm -->
```
---【计划跳转完成】---
已强行跳转至：Day <X>
当前整体进度：<Y>%
本日目标：<大纲目标>

下一步：开始导学 Day <X> 第一个单元「<单元名>」。
---
```
<!-- /template:jump_confirm -->

---

## 禁止行为（FORBIDDEN）

- ❌ 跳转至不存在的天数（例如 Day 26）
- ❌ 跳转时不更新 JSON 中的 `current_day` 与百分比导致状态漂移
- ❌ 未经确认直接清空用户已有的 Day X 历史记录

---

## 完成判据（POST-CONDITIONS）

- [ ] JSON 中的 `current_day` 已修改为新天数
- [ ] `Study.md` 中的完成度百分比与标记已同步更新
- [ ] 输出了跳转确认模板，并开启新单元讲解
