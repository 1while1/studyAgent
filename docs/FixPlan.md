# study-web 全量修复计划（三份审计合并版）

> 来源：① 错误处理与异常管理审查 ② 架构分层与依赖方向审查 ③ 综合技术评审 + ④ orchestrator 策略模式重构提案。
> 每波修复前在 `docs/fixplan/` 落盘详细计划；修复后两个子代理审查，审查问题修复后再进下一波。
> 执行纪律：功能分支 → 三件套全绿（单测 / validate 钩子 / 走查）→ DevLog「最近更新」→ `--no-ff` 合并 → push 重试循环 → 不同步服务器。

## 反驳不行动（误报）

- "30 分钟保险丝注释撒谎"：`process_mgr.py:332` 的 `idle` 是循环计数器（每轮 sleep 0.5s），3600 轮 = 30 分钟，注释正确。
- "提交信息 GBK 乱码"：`fc2aed2` 提交字节为标准 UTF-8，系审查方终端解码问题。
- "pin_today 掩盖衰减 bug"：`tests/test_learner.py:27` `test_mastery_decay_exact` 有衰减专测，三处 pin 用例验证的是上游达标过滤。

## 第一波：P0 快修批 — `fix/audit-p0`

1. `version="0.2.0"` 提取为 `backend/__init__.py` 的 `__version__` 并更新（`api/app.py:113`）
2. 测试数 434 → 528（合并后实际数）：`AGENTS.md`、`README.md:133`、`docs/AcceptanceChecklist.md:5`
3. AGENTS.md 三处措辞：psutil 依赖实话、"pin 版本"改区间约定、playwright 属 dev 工具补说明
4. `/api/command` handler.run 异常分支补 `deps.session_store.save(snapshot)`（`api/routes.py:264-268`）
5. validate_hook validator 包 try/except，自身异常视为校验失败（`engine/hooks/validate_hook.py:17-26`）

测试：扩 `test_command_rollback.py`（handler 异常 → save 恰一次且回快照）；新增 validator 崩溃回滚用例。

## 第二波：错误处理可观测性批 — `fix/error-observability`

1. `learner_service._load_json` / `notes_service`：区分 FileNotFoundError（静默默认）与 JSONDecodeError（备份 `.corrupt.bak` + observer 记账），跟进 `session_store.py:70-74` 模式
2. `auth_service._secret` 写入失败 stderr warning；`verify_password` 异常 observer 记账（fail-closed 不变）
3. 收窄 `except Exception:` → `except (IOError, OSError, json.JSONDecodeError):`：orchestrator 7 处、`qa_capture.py` 顶层 try 拆细、`note_actions.py` 3 处
4. 静默 except 统一 `observer.log_tool("silent_<位置>", False, ...)` 记账；备课预取失败补 `log_prefetch`（`routes.py:86-118`）
5. `observer._write` 首次写失败 stderr warning 一次（后续仍静默，守铁律 13）
6. `config_service.reload_if_changed` 热重载包 try/except（保留旧数据 + 告警；启动期 fail-fast 不动）

铁律 13/15/16 静默语义不变，只补记账与收窄类型。

## 第三波：orchestrator 策略模式重构 — `refactor/orchestrator-phases`

采纳提案方向（与 `engine/commands/` 已验证架构同构），修正其四处盲区：

- **双轴分发**：PREREQ/INTERVIEW/REVIEWING 走 `day_phase`，quiz_r1/quiz_r2 走 `current_stage`，else 为回合计数；registry 按 `matches(session)` 匹配，非单键 map
- REVIEWING 的 atomic_persist + validator（G2c 教训）逐字搬运、语义零改动
- 共享 helper（`_current_unit_title` / `_next_unit_title` / `_interview_title` / `_record_teach_back` / `render_mastery_check`）下沉 `phases/base.py`
- 铁律 15 静默语义、`pending_qa_capture` 标志（chat 路由消费）原样保留

迁移顺序（每步独立绿）：quiz_r1/r2 → INTERVIEW → REVIEWING → PREREQ → 删旧分支。
全程行为保持：不改返回值/状态流转/提示文案，524 个现有测试不改断言。

## 第四波：工程基础设施 — `chore/infra`（可选）

- `requirements-dev.txt`（playwright + psutil）、lock file、`.gitattributes`、GitHub Actions 最低门槛 CI（unittest + validate）

## 留档不做（写入 DevLog「已知边界」）

- API 保留"统一 200 + ok 字段"契约，文档明示，不 RESTful 化
- `routes.py` 拆分（与 API 规范化绑定，单独立项）
- handler 外部落盘不回滚的已知边界（`test_command_rollback.py:147-153` 已锁定），文档明示
- 魔术数字命名、`pid_id` 改名、resources 子目录 README、openai_compat 降级收窄（需真实网关实测）、preset 回退告警、logs_stream 并发限制、错误消息友好化
