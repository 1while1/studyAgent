# 改进3：跨币种成本聚合修复

## 问题
`observer.py` 的 `usage_summary()` 直接累加不同币种（CNY/USD）的 cost 值，产生无意义的混合数字。`usage.js` 的 `fmtCost` 硬编码 `¥` 符号。

## 修复方案

### 后端 observer.py
- `_acc()` 辅助函数增加 `currency` 参数，按币种分桶累加到 `costs_by_currency: dict[str, float]`
- `totals` / `kpi` / `today` / `by_ws` / `by_model` / `by_task` / `rows` 均新增 `costs_by_currency` 字段
- 保留 `cost` 字段（向后兼容），单币种场景值不变

### 前端 usage.js
- `fmtCost(c, costsByCurrency)` 支持多币种：
  - 传入字典时按币种显示（CNY→¥, USD→$, EUR→€, GBP→£, JPY→¥）
  - 多币种：`¥12.3 / $0.1`
  - 单币种：`¥12.3`
  - 向后兼容：只传数字保持原行为
- KPI 卡片、三栏汇总表、明细表全部适配

### 前端 app.js
- usage 弹窗的 summary/today 文本使用多币种格式化

### 测试
- `test_cross_currency_aggregation`：构造含 CNY/USD 的日志，验证分桶聚合正确
- `test_single_currency_backward_compat`：单币种场景 `cost` 字段值不变

## 向后兼容
- 旧 `cost` 字段保留，数值为所有币种成本之和（与旧行为一致）
- 新增 `costs_by_currency` 字段，前端优先使用
- 单币种场景下显示效果与修改前完全一致

## 验证
- 583 测试全绿（+2 新增）
