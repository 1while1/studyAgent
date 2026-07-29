# 改进2: mark_wrong 工具实现

> 分支：`feat/mark-wrong` | 状态：已完成 | 日期：2026-07-29

## 背景

mark_wrong 是防幻觉闭环的关键工具：用户标记"这讲错了"，系统写入纠正证据到学习者模型，
降低该知识点掌握度（delta = -0.05），防止 AI 继续基于错误讲解。

- `config/settings.toml` L74 已有 `mark_wrong = -0.05` 在 `[evidence_delta]` 表中
- `tool_registry.py` L13 原标注"mark_wrong 留档待 M7 前另立"
- `LearnerService.add_evidence()` 接口已存在，source_ref 幂等

## 改动清单

### 1. `backend/engine/tool_registry.py`

- **模块文档**：L13 "mark_wrong 留档待 M7 前另立" → "mark_wrong 已实现（改进2，防幻觉闭环关键工具）"
- **新增 handler `_mark_wrong`**（L479-505）：
  - 校验 concept_id 非空
  - fail-closed：天数不可解析时拒绝写入（与 `_update_model` 同模式）
  - source_ref = `mark_wrong:{cid}:{date}` 保证同日幂等
  - 调用 `LearnerService.add_evidence(cid, "mark_wrong", source_ref, day)`
  - 返回 injection 文本供 LLM 感知纠正历史
- **注册 ToolSpec**（L730-740）：permission=WRITE，params 含 concept_id（必填）+ reason（可选）

### 2. `tests/test_tool_registry.py`

- **_EXPECTED 白名单**：添加 `"mark_wrong": WRITE`
- **测试夹具**：settings 添加 `mark_wrong = -0.05` 到 `[evidence_delta]`
- **新增 4 个测试**：
  - `test_mark_wrong_writes_evidence`：证据写入 + injection 内容
  - `test_mark_wrong_rejects_empty_concept`：空 concept_id 拒绝
  - `test_mark_wrong_idempotent`：同日重复标记幂等
  - `test_mark_wrong_rejects_no_state_store`：无状态存储时 fail-closed

## 设计决策

1. **fail-closed 天数解析**：与 `_update_model` 保持一致，天数不可解析时拒绝写入而非默认 Day 1
2. **source_ref 自动构造**：用户无需指定 source_ref，由 handler 基于 concept_id + 日期自动生成
3. **injection 文本**：包含 concept_id、reason（如有）、幂等状态，供 LLM 感知纠正上下文
4. **权限 WRITE**：证据写入属于规则 14 落盘操作

## 测试结果

- 新增 4 用例，全量 581 绿（577 + 4）
