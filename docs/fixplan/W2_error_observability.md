# W2 详细修复计划：错误处理可观测性批（fix/error-observability）

> 对应 docs/FixPlan.md 第二波。前提：W1 已合并。**本波要等 W1 合并后从最新 main 切分支。**
> 核心原则：铁律 13/15/16 静默**语义不变**（增强失败不阻断主流程），只补两件事——
> ① 数据损坏可感知（备份 + 记账）；② 静默处有账可查（observer.log_tool）。

## 关键设计决策（与初审计划的偏差及理由）

**不做 `except Exception` 类型收窄**（原计划第 3 项调整）。理由：铁律 15/16 场景里
"合理失败"的异常类型无法穷举（PersistError/IOError/OSError/ValueError/KeyError…），
收窄漏型会直接断主流程，风险大于收益；可观测性目标由统一记账达成——编程错误
（KeyError/TypeError）同样会以 `repr(e)` 落进 agent.log，排查时可见。
例外：`qa_capture.run_capture` 顶层 try 保持宽捕获但补记账。

## 修改清单

### W2-1 损坏 JSON 可感知（跟进 session_store.py:70-74 模式）
- `backend/services/learner_service.py:42-46` `_load_json`：
  - `FileNotFoundError` → 静默返回 default（首启正常，语义不变）
  - `json.JSONDecodeError` → `shutil.copy2` 备份 `<name>.corrupt.bak`
    + `get_observer(self._config).log_tool("silent_learner_load", False, f"{path.name}: {e}")`
    + 返回 default
- `backend/services/notes_service.py:46-53` `_load`：同上；**结构不符**
  （isinstance 校验失败，非异常路径）也走备份 + 记账后返回默认

### W2-2 auth_service 诊断
- `backend/services/auth_service.py:49-54` `verify_password`：
  except 分支补 `log_tool("auth_verify", False, repr(e))`（fail-closed 返回 False 不变；
  bcrypt 未装/hash 损坏从此可查）
- `backend/services/auth_service.py:68-79` `_secret`：
  写入失败补**一次性** stderr warning（实例级 `_secret_warned` 标志防每请求刷屏）——
  secret 无法持久化 = 重启后全员 token 失效，必须留痕

### W2-3 静默 except 统一记账（detail=repr(e)[:200]，名称 `silent_<位置>`）
- `backend/engine/orchestrator.py` 7 处：
  - :121-127 prereq 证据落盘 → `silent_orch_prereq`
  - :179-180 Study.md 头部更新 → `silent_orch_plan`
  - :185-192 复盘 learner 写入 → `silent_orch_review`
  - :237-243 render_mastery_check → `silent_orch_round`
  - :248-254 `_current_unit_title` → `silent_orch_unittitle`
  - :256-266 `_interview_title` → `silent_orch_interviewtitle`
  - :281-294 teach_back 落盘 → `silent_orch_teachback`
- `backend/engine/note_actions.py` 2 处：:60-61 后缀摘除 → `silent_note_suffix`；
  :88-89 销账证据 → `silent_note_evidence`（:74-76 day 读取为纯兜底，不记）
- `backend/engine/qa_capture.py:58-59` 顶层 except → `silent_qa_capture`
- `backend/api/routes.py:117-118` `_prefetch` except → `get_observer(deps.config).log_tool("prefetch", False, repr(e))`
  （与成功路径 log_prefetch 配对，预取失败从此可查）

### W2-4 observer._write 首次失败 stderr
- `backend/services/observer.py:141-159`：except 分支加实例级一次性
  `print(f"[observer] agent.log 写入失败：{e}", file=sys.stderr)`（`_write_warned` 标志；
  后续仍静默，守住铁律 13"日志绝不影响主流程"）

### W2-5 config 热重载保护（启动期 fail-fast 不动）
- `backend/services/config_service.py:57-63` `reload_if_changed`：
  包 `try/except (OSError, tomllib.TOMLDecodeError)` → 保留旧 `_data`、
  同一坏 mtime 只 stderr warning 一次（`_last_bad_mtime`）、返回 False；
  用户修复文件后 mtime 变化自动恢复重载

## 测试（预计 +8~10 用例）

- `tests/test_learner.py` 扩：写坏 learner_model.json → get_model 返回默认
  + `.corrupt.bak` 存在
- `tests/test_notes_service.py`（或就近）同款：坏 notes.json → 默认 + 备份；
  结构不符（合法 JSON 但缺 notes 键）→ 同样备份
- auth：patch atomic_write 抛错 → `_secret()` 仍返回 secret + redirect_stderr 捕获
  一次性 warning（调两次只打一次）
- config：写坏 toml → `reload_if_changed()` False + `get()` 旧值可用 + 不抛；
  重写好 toml → 再调 True
- observer：`log_path` 指向不可写位置 → 首次 stderr 捕获，二次不再打
- 记账代表性验证：qa_capture 构造 transcript 异常 → 返回 [] 且 agent.log
  含 `silent_qa_capture`（observer 目标路径用临时 config 隔离）

## 不做（本波明确排除）
- 不做 except 类型收窄（见上决策）
- 不动 orchestrator 结构（W3 重构范围）
- 不动 API 契约、不动前端
- 走查按惯例跑（187 项基线），仪式同 W1

## 验收
- 全量单测绿（528 + 新增）、validate 钩子 SUCCESS、走查 187 全 PASS
- DevLog「最近更新」→ --no-ff 合并 → push 重试循环 → 不同步服务器
