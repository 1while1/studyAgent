# W1 详细修复计划：P0 快修批（fix/audit-p0）

> 对应 docs/FixPlan.md 第一波。修复后交两个子代理审查，审查问题修完再走三件套 + 合并。

## 修改清单

### 1. 版本号提取（app.py:113）
- `backend/__init__.py`（当前空文件）加 `__version__ = "1.0.0"`（M1-M7 收官 + M11 slash，0.2.0 严重失真）
- `backend/api/app.py:113`：`from .. import __version__`，`version=__version__`

### 2. 测试数文档同步（修复后实测 528 绿 / 走查 187 项）
- `AGENTS.md:14`：`434 个` → `524 个`
- `README.md:133`：`434 个后端测试` → `524 个后端测试`
- `docs/AcceptanceChecklist.md:5`：`434 单测 / 152 走查` → `524 单测 / 187 走查`
- `docs/AcceptanceChecklist.md:150`：`单测 434 全绿；走查 152 全绿` → `单测 524 全绿；走查 187 全绿`

### 3. AGENTS.md / AgentDesign.md 措辞修正（以实现为准）
- `AGENTS.md:20`「测试不依赖第三方包」→ 实测 `tests/test_arch_fixes_b.py:23` 引 psutil，且 psutil==7.2.2 本就是 requirements.txt 内 pin 的运行时依赖（process_mgr 用）。改为「测试不引入 requirements.txt 之外的第三方包、不调真实 LLM（MockLLM）」
- `AGENTS.md:21` Playwright 句末补注：playwright 为开发环境工具（走查脚本 `scripts/ui_walkthrough.py` 专用），不随 requirements.txt 安装
- `docs/AgentDesign.md:119`「进 requirements.txt pin 版本」→ 实测核心四包（fastapi/uvicorn/openai/pydantic-settings）用 `>=` 区间，其余 `==` pin。改为「进 requirements.txt 声明版本约束（核心框架用 >= 区间，其余 == pin）」

### 4. /api/command handler.run 异常补回滚（routes.py:264-268）
- 现状：`handler.run` 抛异常直接 return，session 可能已被 handler 部分推进并 save，与 LLM 失败分支（save(snapshot)）不对称
- 修复：except 分支补 `deps.session_store.save(snapshot)`，注释说明对称语义
- 测试：扩 `tests/test_command_rollback.py`，新增 `test_handler_exception_rolls_back_session_snapshot`——patch 同步 handler 的 `run` 抛 RuntimeError，spy save 断言恰好一次且内容为指令前快照

### 5. validate_hook validator 异常保护（validate_hook.py:17-26）
- 现状：`spec.loader.exec_module` 若抛 SyntaxError/ImportError，异常穿透 `atomic_persist` 的 validator 调用，已写入文件不回滚
- 修复：validator 整体包 try/except，自身异常返回 `(False, f"validator 自身异常：{e}")`，走既有 not-ok 回滚路径
- 测试：新建 `tests/test_validate_hook.py`——patch HOOKS_DIR 指向含坏脚本的临时目录（① exec 期 SyntaxError ② main 运行期抛错），断言返回 (False, ...) 而非抛出；再断言接进 `BackupService.atomic_persist` 后抛 PersistError 且文件回滚

## 不做（本波明确排除）
- 不改任何 API 契约、不动前端、不动 orchestrator（属 W3）
- 走查仍按惯例跑（187 项基线），仪式：备份 runtime/session.json + .env → 确认服务在跑 → sed 清 AUTH_PASSWORD_HASH → 重启 → 走查 → 恢复 → 重启

## 验收
- 全量单测绿（528 = 524 基线 + 新增 4：validator 异常保护 ×3 + handler 异常回滚 ×1）、validate 钩子 SUCCESS、走查 187 项全 PASS
- DevLog「最近更新」补条目 → --no-ff 合并 → push 重试循环 → 不同步服务器
