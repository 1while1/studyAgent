# DevLog — study-web 开发日志与交接上下文

> 用途：跨会话/压缩后恢复上下文。记录当前状态、关键设计决策、已修复 bug 史。
> 最近更新：2026-07-23（**UI v10：笔记/掌握度全屏化重做**——📝 书架三栏 + MD 编辑器，🧠 掌握度面板；另修复 /api/chat 断连丢消息真 bug；211 单测/87 走查全绿）

## 当前运行状态

- **Git**：`study-web/.git`（main）→ GitHub <https://github.com/1while1/studyAgent>。密钥 `.env`/`opencode.txt` 与数据 `runtime/`、`workspaces/` 已 gitignore。提交流程：分支 + 三件套验证（单测/validate/走查）全绿才 commit
- 启动：`cd study-web && python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8765`
- LLM：主渠道 `openai_compat`（OpenCode Go / deepseek-v4-pro，**被上游 401 风控拦截，待解封**）；
  备用 `deepseek_official`（DeepSeek 官方 deepseek-chat，已充值，**当前实际工作渠道**）
- fallback 自动切换已生效（`llm/fallback.py`）
- 工作区：ragent（默认，`../docx`，Day 2 学习中，`materials_dir=../RAgent文档` 68 份资料已解析）/ tinyrag（5 天测试，可删）/ onecoupon（25 天，用户项目，初始化验证通过 25/25）
- 测试：`python -m unittest discover -s tests` → 211 个全绿；UI 走查 87 项全绿
- ⚠️ 走查结束会 `POST /api/session/reset` 清测试消息——**有值得保留的对话时不要跑走查**

## 下一步

v1 时代 Roadmap（P0-P2）已全部收官（桌面打包暂缓）。演进以 `docs/AgentDesign.md` v3 封板版为准：M1 资料库 ✅ → M2 可观测 ✅ → M3 学习者模型 ✅ → M4 笔记管理 ✅（2026-07-23 交付）→ **下一步 = M5a 工具骨架**（tool_registry + 权限分级 + 现有服务工具化包装 + turn_engine 接口抽出，纯重构）。

## M4 笔记管理（2026-07-23 交付）

- **四层体系**（AgentDesign §6）：日志层=StudyMemory（保留 append-only）/ 条目层=`notes.json` / 话术层=InterviewQA.md（收编）/ 蒸馏层=learner_model evidence
- **NotesService**（`services/notes_service.py`，不进 Deps）：CRUD + 状态/类型筛选 + `merge`（多条并一条，残骸 `merged_into` 不写证据）+ `distill_from_text`（StudyMemory 卡壳/疑问行 → 条目，剥「（待解答）」后缀，同 kind 文本相等或互为子串去重）。条目 schema 扩展可选字段（created_day/resolved_day/merged_into），kind 枚举收紧为 stuck/question/mastered/insight
- **条目自动进层**：[同步] 已掌握/卡壳/疑问除写日志外同步 `NotesService.add`（source_ref 带内容 sha1[:6] 幂等；有 current_unit 自动挂接 concept，无则 needs_review 待人工）
- **卡壳销账单一路径**（`engine/note_actions.resolve_note`）：笔记页按钮与未来 AI resolve_note 工具同走——条目 resolved + `note_distilled` 证据（+0.05，source_ref=`note:{id}` 幂等，重复销账不重复加）；未挂接 concept/合并残骸不写证据
- **QaService**（`services/qa_service.py`）：InterviewQA.md parse/render round-trip（`## 标题`+`**产出来源**：` 识别条目；「问题模板」「已累积话术」保留小节与内容里的加粗行均不误切）；add_entry 首次追加剥离骨架占位行（`（待产生）`/`（学习开始后自动累积）`）；`validate_capture` 机械校验（5 字段齐 + 追问 ≥3 组）
- **🎙 拷打反喂**（`engine/qa_capture.py`）：复盘评分落盘 → `session.pending_qa_capture` → chat 路由执行 `run_capture`——转录切片（`session.review_msg_start`，day_review 落点）→ `resources/prompts/qa_capture.md` → 一次非流式 LLM 调用 → 机械校验（失败带原因重试一次）→ **产出来源行服务端强制覆写 `Day N 复盘拷打`**（end_day 统计契约）→ 同名标题跳过。`qa_capture_enabled/qa_capture_max_entries` 可配；任何异常静默不阻断复盘
- **📝 笔记页**：顶栏 📝 → 筛选/新建/就地编辑/删除/合并模式/⇩ 从日志蒸馏/⚠待挂接条目 concept 下拉挂接；**话术 tab 收编**：学习资料弹窗「面试话术库」升级为卡片视图（30s 直显 / 2min 与追问预案 `<details>` 折叠 / 就地编辑 / 删除）+ 原文切换
- **validate_study.py 还 M3 债**：`check_json_schemas`——concepts/learner_model/notes 三文件**存在才校验**（schema_version=1 + 结构形状 + notes 枚举/id 唯一）

## M3 学习者模型（2026-07-23 交付）

- **域层**（`domain/learner.py` 纯函数）：`concept_id()` 代码铸造（Day{N}-{单元id}）、`compute_mastery()`（Σ(delta×0.5^(天数/半衰期))，无 code_verify_pass 封顶 0.6）、`review_interval()`（<0.4→1 / <0.7→3 / 否则 7 天）、`is_due()`（过期累积不消失）
- **LearnerService**：`concepts.json`（确定性先修链：天内链+跨天链）+ `learner_model.json`（evidence 落盘，mastery 读取时按衰减重算，存储值仅冗余）；delta 查 settings `[evidence_delta]` 表写入定死；`source_ref` 幂等（同键重复写不产生重复证据）
- **三路证据写入**（commands 统一入口 `learner_with_concepts`，try/except 不阻断学习流程）：next_content 单元终期评分 → quiz_right/wrong；[同步] 已掌握/卡壳 → sync_mastered/stuck；[验证代码] → code_verify_pass/fail（每日每单元一条）；复盘评分 → 当日每单元 quiz 类一条
- **迁移（草稿+人审）**：历史 rating → quiz_score 证据（delta=rating/5，ts=学习日期，**遗忘衰减照算**——Day1 距今 60 天 mastery≈0.04，属设计意图）；卡壳/疑问 → notes.json 开放条目（needs_review，M4 人工挂接）；learner_model.json 已存在拒绝重复迁移
- **热力图**：顶栏 🧠 → 知识点红黄绿格 + △封顶 + ⏰到期，点格看证据明细；旧评分存在时迁移引导条（预览→确认→应用）
- **材料挂接**：concepts.materials 由 commands 编排（study_plan doc tokens → MaterialsService.resolve_doc）；`extract_doc_paths` 加盘符容忍（旧 CLI 时代 `D:/AI学习/...` 绝对路径），stem 兜底命中

## M2 可观测（2026-07-23 交付）

- **observer**（`services/observer.py`）：`runtime/agent.log` JSONL（v/ts/kind/provider/model/task/latency_ms/in/out_tokens/tokens_est/ok/error）。`factory._build` 包 `ObservedLLM`（每渠道独立记账，fallback 切换 = 主记失败+备记成功两条）。任务标签走 ContextVar `task_scope`（chat/warmup/init）；READ/READ_DOC/prefetch 记 tool 记录。**记账任何异常静默吞掉，绝不阻断主流程**
- **token 三层**：usage 精确（openai_compat 加 `stream_options include_usage`，网关不支持自动降级记忆）→ tiktoken cl100k 估算 → CJK×1.5+其他÷4 兜底公式；usage 到达反算比率 0.8/0.2 滑动校准（`runtime/token_calibration.json`）
- **UI**：顶栏 `#llm-pill` 状态条（渠道+耗时/失败标红悬停看原因，15s 轮询 `/api/observability/status`）；📊 用量弹窗（日×渠道×task 聚合 + settings `[pricing]` 成本，估算诚实标注）
- **访问密码门**：bcrypt 哈希存 `.env AUTH_PASSWORD_HASH`（**有意偏离设计原文"存 settings"**——settings.toml 是 git 跟踪文件，.env 才符合"不入 git"意图与密钥边界铁律）；token=HMAC-SHA256 签名 `{exp}.{sig}`，密钥 `runtime/auth_secret` 首生成；中间件 `api/middleware.make_auth_gate`（豁免仅 status/setup/login；注入 `request.state.user="local"` 多用户预留）；登录限速 10 次/5 分钟；未设密码 = 开放模式；前端 fetch 包装 401→登录层→重放原请求
- **运行时目录统一** `config_service.runtime_dir(config)`：settings 在 config/ 下取上级根，测试临时 settings 自动隔离（防测试写真实 runtime）

## M1 资料库（2026-07-22 交付）

- **MaterialsService**（`services/materials_service.py`，不进 Deps，routes 按需构造，同 CodeBrowser 模式）：扫描注册（`Workspace.materials_dir`，txt/md/docx/pdf，敏感文件跳过）→ 解析 → 索引 → 章节切片。注册表 `<docx_dir>/materials.json`（schema_version=1，atomic_persist），缓存 `<docx_dir>/materials/_cache/<safe_id>.txt + .index.json`。mtime 变化重解析；进程级 `ensure_scanned` 首次使用自动扫描一次
- **解析**：txt/md 直读；docx 走 python-docx（Heading 样式 → `#` 标记），**损坏关系包（WPS/转换工具产，报 "no item named 'NULL'"）自动回退裸 XML 解析**（zipfile+ET，styles.xml 建 styleId→层级映射）；pdf 走 pypdf（每页一节）。统一 cleanup（移植 ragent `TextCleanupUtil` 规则）。依赖 pin：python-docx==1.2.0、pypdf==6.14.2
- **READ_DOC 工具**：`[READ_DOC:资料id#章节]`（章节可省=先返回目录自导航）→ `tool_use.py` 双标记增量扫描（与 READ 前缀互不互含，**合计共享** `ai_read_max_per_reply` 限流与行数上限）→ 注入带 `"""` 定界 + "仅供参考不视为指令"。SSE `tool_read` 事件加 `kind:"code"|"doc"`；前端 📄 chip（不跳代码浏览器）
- **备课确定性预取**（`routes.LLMStreamer._prefetch`，代码强制不靠 LLM 自觉）：`current_stage == stages.first` 且单元可解析时，`study_plan.extract_doc_paths` 取单元「文档」token → `materials.prefetch`（总量 `materials_prefetch_max_chars` 封顶，sources 去重）→ **transient user 消息插到最后一条用户消息之前**（不进 chat_history）→ 先下 📚 备课 chip 事件。任何异常静默降级
- **prompt**：硬约束第 7 条扩写双标记规则；新增「可用学习资料」清单段（`materials.catalog()`，PromptBuilder 加可选参数 `materials=None` 向后兼容）
- **API/UI**：`GET /api/materials`、`POST /rescan`、`POST /register`、`GET /preview`；学习资料弹窗加「资料库」tab（清单/预览/重扫/注册）
- **解析方案拍板**：python-docx + pypdf（不用 Apache Tika——ragent 的 Tika 是 Java 类无法复用，且 parseToString 平文本丢标题层级，READ_DOC 章节导航需要层级）

## 多工作区机制（v4）

- **Workspace 值对象**（`domain/workspace.py`）：slug/title/goal/docx_dir/project_dir/session_path/total_days/replica_name/preset
- settings.toml：`active_workspace` + `[[workspaces]]`；code_roots 带 `workspace` 字段过滤；无 [[workspaces]] 时旧配置自动合成默认工作区（向后兼容）
- 切换：`POST /api/workspaces/switch` → `app.assemble()` 重建 deps；聊天会话按工作区隔离
- **初始化向导**（顶栏工作区下拉 → 新建工作区）：填项目目录/目标/天数 → 扫描预览 → `repo_scanner` 生成画像 → LLM 生成 Project.md + Study.md → **验证管线**（Project.md 结构检查、Study.md 逐天 `parse_day_text` 解析）→ 失败带错重试 1 次不过不写盘 → 骨架模板写 StudyState/ReplicaPlan/DocIndex/InterviewQA → 注册 settings + code_root + 自动切换
- **重新扫描**：下拉里「↻ 重新扫描项目结构」重新生成 Project.md（prompt 防虚构路径的数据源）
- **资源单源**：`resources/sop/`（模板锚点）、`resources/hooks/validate_study.py`（参数化 docx_dir/total_days/replica_name）、`resources/templates/`（初始化骨架）、`resources/prompts/`（LLM 生成提示词）。`docx/SOP` 保留给 CLI 助手，study-web 以 resources 为准
- **零硬编码**：title/goal/total_days/replica_name/project_dir 全走 Workspace；已清除 7 处 Ragent 字面量（prompt 角色行、start_day 仓库路径、study_plan 前缀剥除、total_days、warmup SOP 卡名、应用标题、代码引用示例）

## 功能清单（已实现）

| 模块 | 说明 |
|------|------|
| 学习流程 | 10 指令、五步状态机、2 回合追问、评分标记落盘、FAIL-FAST 双选项、天数递进 |
| 聊天 | SSE 流式、Markdown 渲染（节流 200ms 最新值渲染 + rawText 累积器）、代码高亮+复制、思考中指示、历史回填 |
| 双模式 | **知识学习**（tutor：暖纸书房，米白+赭石+衬线标题）/ **源码学习**（pair：IDE 深色 #1e1e1e + #0e86d8）。顶栏分段控件切换，模式绑定主题（无独立深浅切换） |
| 布局三区 | 侧栏=纯学习仪表盘（进度/今日单元/同步速览/会话状态一行）；顶栏=模式切换+工作区下拉+工具图标；输入框上方=指令胶囊条 |
| 指令唤起 | 胶囊条点击 + 输入框键入 `[` 弹出补全菜单（Enter 选首项，Esc 关闭，防输入法误触发） |
| 多工作区 | 顶栏下拉切换/新建（初始化向导：扫描→LLM 生成→验证管线）/重新扫描 Project.md；会话与代码根随工作区隔离 |
| 增量学习计划 | 初始化=全量粗纲+前 3 天细化；`[结束今日学习]` 滚动细化次日（注入昨日反馈+Project.md，失败保留粗纲告警不阻塞） |
| 间隔复习 | `[开始今日学习]` 按 1/3/7 天间隔采集历史卡壳/待解答疑问/<3 分单元 → Step 1 展示 + 开场前 ≤5 分钟逐条回顾 |
| 编码验证 | 指令 `[验证代码]`：验证根（replica 目录否则 project_dir）跑 Maven/Gradle/npm 编译（含"测试"跑测试），限时 300s/可离线，结果回喂 AI 点评 |
| 学习模式预设 | `resources/presets/{default,reading,bugfix,article}.toml`，工作区 `preset` 覆盖全局 stages；向导下拉选择 |
| 工作区管理 | 下拉菜单：切换/新建/重扫 + 每项 ⬇ 导出 zip / ✕ 删除（默认保留磁盘数据） |
| 代码浏览器 | 源码学习模式内：roots 持久化（settings.toml `[[code_roots]]` 按工作区过滤）、树懒加载、行号+高亮、标签页式文件头、**IDE 状态栏**（路径·语言·行数·UTF-8）、树折叠/换行开关/树宽拖拽记忆 |
| 片段提问 | 选区浮动按钮 → textarea（换行保留）；聊天渲染为展开式片段卡片；**点 📎 引用跳转代码浏览器打开文件 + 滚动定位 + 黄色行高亮** |
| 代码引用芯片 | AI 回答中反引号路径自动转为可点击芯片；`/api/code/resolve` 三级解析（根前缀→直接相对→后缀索引，60s 缓存）；点击 → 源码学习模式打开文件 + 行高亮；完整路径失败时**按文件名回退定位**；找不到弹 toast。prompt 硬约束第 6 条 + system prompt 注入当前工作区 `Project.md` 防虚构路径 |
| AI 读文件 tool-use | 导师输出 `[READ:路径:L起-止]` → `engine/tool_use.ToolUseLoop` 增量扫描截获（反引号包裹/行内出现均容错，标记不进 SSE/历史）→ code_browser 只读注入真实代码（≤200 行）→ 续写；单回复限 3 次（`ai_read_max_per_reply`，超限静默丢弃）；读取失败注入**模糊候选文件**（`code_browser.suggest`）供模型纠正；SSE 事件 `tool_read` → 前端 chip，点击跳转代码浏览器行高亮 |
| **资料库（M1）** | `materials_dir` 扫描注册（txt/md/docx/pdf）→ 解析索引缓存；**备课确定性预取**（讲解回合按单元文档引用 transient 注入教材节选，📚 chip）；`[READ_DOC:资料id#章节]` 与 READ 同管线同限流（📄 chip）；资料库弹窗（清单/预览/重扫/注册） |
| **可观测性（M2）** | agent.log 全量 LLM/工具记账（ObservedLLM 逐渠道包裹）；token 三层统计（usage→tiktoken→公式）+ 滑动校准；顶栏状态 pill；📊 用量页；**访问密码门**（bcrypt@.env + 签名 cookie + 限速 + 开放模式默认） |
| **学习者模型（M3）** | concepts 注册（确定性先修链）+ evidence 三路写入（考核/同步/构建）+ mastery 衰减实时计算（无构建验证封顶 0.6）；🧠 掌握度热力图（着色/△/⏰ + 证据明细）；旧评分一键迁移（草稿人审），卡壳疑问转 notes 开放条目 |
| **笔记管理（M4）** | 四层体系（日志/条目/话术/蒸馏）；[同步] 自动产笔记条目；📝 笔记页（筛选/编辑/合并/蒸馏/挂接/销账）；销账单一路径 note_distilled 证据幂等；话术库卡片化收编；🎙 复盘拷打自动反喂 InterviewQA（机械校验+来源行服务端覆写） |
| Mermaid 图 | vendor mermaid@11；```mermaid 块终渲染为 SVG（流式中不渲染）；主题随布局 pair=dark/tutor=default；`securityLevel: strict`；渲染失败回退代码块 |
| 模型配置页 | 主/备渠道、模型/URL/Key（掩码）、测试连接、保存热生效 |

## 关键设计决策（不要回退）

1. **模板单源** = docx/SOP 锚点；**数据单源** = docx/ 文件；落盘必走规则 14（备份→写→validate→回滚）
2. **sop_card 三态**：纯教学内容生成必须 `sop_card=""`（带卡会让模型复读模板，已踩坑）
3. **start_day 清空 chat_history**：新开始=新对话，防旧进度泄漏（已踩坑）
4. **流式 rawText 累积器**：禁止从 bubble.textContent 回读再渲染（渲染污染→乱码，已踩坑）
5. **静态资源 `Cache-Control: no-cache`**（app.py 中间件）：防新旧 JS/HTML 混搭（已踩坑）
6. **前端交付前必须 Playwright 真实点击验证**（用户定的规矩）：优先跑 `scripts/ui_walkthrough.py`
7. **模式绑定主题**：知识学习=暖纸浅色，源码学习=IDE 深色，无独立深浅切换按钮；主题变量按 `body[data-layout]` 分两套（v3 起，`data-theme` 已废弃）
8. **三区分离**（v3 用户拍板）：状态在侧栏、模式与工具在顶栏、指令贴输入框；模式切换唯一入口 = 顶栏分段控件 `#mode-tutor/#mode-pair`，不再设悬浮胶囊/侧栏按钮
9. **代码面板专属源码学习模式**：tutor 下隐藏；v2 的面板宽屏/拖拽调宽已随旧双布局移除（pair 下面板自适应充满）
10. **tool-use 标记行缓冲截获**：READ 标记必须独立一行；截获后中断当前 LLM 流、注入真实代码后**重新调用**续写；注入内容以 transient user 消息只存在于续写调用，不进 chat_history；超限标记静默丢弃（不注入、不下发）
11. **Mermaid 只终渲染**：流式节流渲染跳过 mermaid（块未闭合无法渲染），done/message/历史回填走 final 渲染；vendor 文件缺失时静默保留代码块原样
12. **增量式 Study.md**：初始化=全量粗纲+前 N 天细化（`init_detail_days`，默认 3）；`[结束今日学习]` 滚动细化次日（与主批次同一原子落盘，失败保留粗纲+告警，不阻塞）；已细化天自动跳过（旧工作区兼容）
13. **间隔复习无回写**：复习项只按 `review_intervals`（1/3/7）到期出现，不记"已复习"——间隔窗口过后自然消失

## Bug 史（重要，防重犯）

| Bug | 根因 | 修复 |
|-----|------|------|
| 聊天全挂 | opencode 流含空 choices 块 | openai_compat 跳过空块 |
| 内容流完即消失 | message 事件误标 firstDelta，清理误删内容泡 | delta 到达总是清 thinking 态 |
| 回复乱码缝合怪 | 节流渲染后从 textContent 回读累积 | rawText 独立累积器 |
| 模型复读 FAIL-FAST | 指令带整卡 + 用户输入命中触发场景 | 纯教学内容 sop_card="" |
| 模型"接着旧课讲" | 重开后历史残留 assistant 消息 | start_day 清空 history + 指令成对写入 |
| 评分卡死 | 正则不认 `分`字/加粗/半角冒号 | SCORE_RE 全变体兼容 |
| 重新开始死路 | 注册表只认 `[...]` | 纯文本别名映射 |
| 侧栏收不回 | 收起按钮随栏消失 | 悬浮 ☰ 展开按钮 |
| 代码浏览点击无反应 | 浏览器新旧缓存混搭 | no-cache 中间件 |
| 宽屏按钮点不动 | layout-toggle 悬浮胶囊遮挡 | tutor 模式隐藏胶囊，侧栏按钮替代 |
| 宽屏还原 NaNpx | `a \|\| b ? c : d` 运算符优先级 | 显式分支 |
| 片段消息全文糊屏 | 旧格式正则过严 | SNIPPET_RE 容错（围栏换行/前缀可缺） |
| 片段代码换行被吞 | 输入框是单行 `<input>`，赋值 `\n` 被 HTML 规范剥掉，历史片段消息全被压成一行 | 输入框改 `<textarea rows=1>` + Enter 发送/Shift+Enter 换行（`isComposing` 防输入法误发）+ 自动增高 ≤160px |
| 流式回复"截断"（句中断） | 节流渲染竞态：done 终渲染后，迟到的 200ms 节流定时器用**调度时旧快照**回退气泡内容；后端其实已完整落盘（刷新即恢复） | 节流触发时渲染挂在 bubble 上的最新文本（`_pendingText`），message/done 事件先 `cancelThrottledRender()` |
| 向导按钮触发空指针 | 「扫描预览」复用了 `.cfg-test` 样式类，被模型配置的全局委托 handler 接住，`data-section` 为空 → `getElementById("test-undefined")` = null | cfg-test 委托加 `#provider-sections` 作用域守卫（样式类与行为钩子分离的教训） |
| 25 天 Study.md 初始化必失败 | LLM 默认 max_tokens=4096，25 天计划需 5-6k token，输出截断在 Day 19 左右 → 校验缺 Day 20-24 | 初始化生成走 `init_max_tokens`（settings 可配，默认 8192 = DeepSeek 输出硬顶） |
| opencode 401 | 账号被上游风控（非程序问题） | fallback 到 DeepSeek 官方 |
| 跨日递进必失败（[开始今日学习] 报 StudyMemory Day_N+1 not found / Study.md 天数不符） | start_day 递进 current_day 后**先单独落盘 JSON**，中间态（StudyMemory/Study.md 仍是旧天）必被 validate 拒绝回滚；另有游离垃圾键 `state["active_day_completed"]`（flag 实为 per-day） | 递进不单独落盘，JSON+StudyMemory+Study.md（update_header）末尾统一原子落盘；删游离键；test_flows 补跨日用例；清理 ragent 真实数据残留键 |
| READ 标记泄漏到聊天（用户看到原始 `[READ:...]` 文本、无 chip 可点） | 模型把标记裹进反引号（`` `[READ:...]` ``）或写在行内，行缓冲正则只认整行 → 不截获；更糟的是模型随后**自己模拟注入**并编造代码 | 改增量扫描解析（任意位置/反引号/跨 delta 残片均截获，未闭合按文本下发）；prompt 规则 7 加固（禁包裹/输出标记后立即停止/禁模拟注入/用户要求读代码时必须 READ）；读取失败注入模糊候选文件 |
| [验证代码] 报"未发现构建文件"（replica 项目） | ragent-replica 按日分模块（day01/day02 各自带 pom），验证根只查根目录；onecoupon 多模块项目根有 pom 却被子目录 pom 干扰判为多候选 | resolve_verify_root 三级解析：args 点名 > 当日 dayNN > 根/唯一候选；多模块根有构建文件时从根构建 |
| M1 预取命中错误资料（注入八阶段问答而非 Prompt 工程教材） | `extract_doc_paths` 按空格切 token，"AI & RAG 基础扫盲/..." 被切碎成 "RAgent文档/AI"，词干 "ai" 模糊命中错误资料 | extract_doc_paths 改为只按 、，,；; 分隔（路径允许空格与 &）；resolve_doc 词干兜底加最短 4 字符防猜 |
| M2 聊天全挂（"LLM 调用失败：<Token var=..."） | task_scope 用 `_task_var.reset(token)` 恢复——SSE 生成器在 anyio 线程池跨上下文关闭时 reset 校验 context 抛 RuntimeError | 恢复旧值改用 `set(old)`（set 不校验 context）；回归测试补齐 |
| M2 测试日志互串（47 条记录混进单测） | runtime 路径取 `settings.parent.parent`，临时 settings 落在共享 Temp 目录，所有测试共写一份 agent.log | `config_service.runtime_dir()`：settings 在 config/ 下才取上级根，否则取同级 runtime 隔离 |
| 走查 strict mode 撞 id（#llm-status ×2） | 新增状态 pill 复用了模型配置弹窗已有的 `#llm-status` id | pill 改名 `#llm-pill`；modal 原引用还原 |
| M4 走查笔记「编辑」步骤假失败（点击后 textarea 不出现） | 走查用 `has_text` 定位 `.note-item`；进入编辑态后 `.note-text` 被换成 `textarea`，其 value **不属于 textContent**，has_text 定位瞬间失效——应用代码无 bug（合成点击/直接调用均正常） | 走查编辑后改用 `#notes-list` 下的新鲜定位器；教训：**has_text 定位的元素内容被编辑控件替换时必须重新定位** |
| M4 测试 settings 的 `qa_capture_enabled=false` 不生效 | EXTRA_SETTINGS 拼在 `[evidence_delta]` 表之后，裸键落进节区变成 delta 表成员 | 测试基座把 EXTRA_SETTINGS 移到所有 `[节区]` 之前（TOML 裸键必须前置的铁律同样适用于测试夹具） |
| 走查「历史回填渲染卡片」超时崩溃（LLM 慢/挂起日必现） | /api/chat 的用户消息在**流式完成后**才随 session 落盘；客户端中途断连/刷新（GeneratorExit 不走 `except Exception`）→ 消息整轮丢失，前后端历史分叉 | 用户消息**先落盘再开流**（routes.py chat gen 一行前移）；回归测试 test_chat_disconnect 用 `body_iterator.aclose()` 模拟断连，未修复时必失败 |

## 缺陷修复批（2026-07-22，双子智能体审查驱动，fix/review-batch）

| 缺陷 | 修复 |
|------|------|
| `.env`/证书类文件可经代码浏览器读取、可经 AI READ 注入外发 LLM | code_browser 敏感文件黑名单（.env*/id_rsa/*.pem/*.key 等）：read_file 拒绝 + 索引排除 |
| LLM 失败时用户消息不落盘（前后端历史分叉）、command 端点阶段已推进但无对话记录 | /api/chat 失败也 save session；/api/command LLM 失败整体回滚到 handler 前快照 |
| atomic_persist 单槽 .bak 并发竞态 | 按备份目录分桶的进程内互斥锁 |
| config_writer / session_store 裸 write_text（崩溃即截断 boot-critical 文件） | atomic_write 统一模式（临时文件 + os.replace）；session 损坏先备份 .corrupt.bak 再重置 |
| 删除工作区 rmtree 守卫相等性漏洞（可误删整个 workspaces/） | 严格限定 study-web/workspaces/<slug> 同名目录，去掉 ignore_errors，越界即报错中止 |
| end_day 零完成单元 FAIL-FAST 死循环 | 零完成分支同样放行「确定/跳过复盘」 |
| jump_day 用全局 total_days、无数字崩溃、写脏键 | 走 workspace.total_days；无数字返回用法提示；删游离键写入 |
| 前端 streamPost 无协议外失败兜底（断网计时器永久泄漏、气泡卡死） | try/catch/finally + res.ok 检查，失败清占位泡 + 可见错误泡 |
| 流式中可重复发送（前后端历史双错乱） | 发送锁：进行中禁提交/禁指令胶囊，toast 提示 |
| add_code_root 丢失 workspace 归属 | 写入时补当前工作区 slug |
| LLM 客户端无超时（上游挂起死占线程） | OpenAI timeout（llm_timeout 默认 300 可配）+ max_retries=1 |
| rescan 覆盖 Project.md 绕过规则 14 | 改走 BackupService.atomic_persist |
| 评分越界（【评分：99】也判过） | extract_score 限定 [1.0, 5.0]，越界视为无标记 |
| 阈值/总天数硬编码（3.0、25） | 统一走 mastery_pass_score / workspace.total_days |
| mermaid.min.js 下载截断（"Unexpected end of input"） | 后台 curl 超时只下了 3MB（整文件 3.56MB），尾部恰好截断在函数体中 | 前台 curl `--retry 3` 重下 + `node --check` 校验语法 + 走查 Mermaid 断言 |

## UI 版本

- **v10（2026-07-23）**：笔记/掌握度全屏化重做 —— 两个模块从 780px modal 升级为 `.page-overlay` 全屏页。📝 笔记页 = 书架三栏（特殊架/知识点成书/类型 chips/全文搜索 + 卡片列表 + MD 编辑器：H1-H3/B/I/S/代码块/引用/列表/任务/链接/表格/分隔线/Mermaid 工具条 + 编辑/分屏/预览三态，预览复用聊天渲染管线）；🧠 掌握度面板 = 统计卡 + 按 Day 分组进度条列表 + 详情（建议行动卡 + 证据构成表·行为中文名·Δ 着色·衰减说明）。后端零改动。
- **v9（2026-07-23）**：M4 笔记管理 —— 顶栏 📝 笔记页（筛选/新建/就地编辑/合并模式/日志蒸馏/concept 挂接下拉/销账）；学习资料弹窗「面试话术库」升级为卡片视图（30s 直显 + 2min/追问预案折叠 + 就地编辑/删除 + 原文切换）。
- **v8（2026-07-23）**：M3 学习者模型 —— 顶栏 🧠 掌握度热力图（红黄绿格 + △封顶 + ⏰到期），点格展开证据明细表；迁移引导条（预览→确认→应用）。
- **v7（2026-07-23）**：M2 可观测 —— 顶栏 LLM 状态 pill（渠道+耗时/失败标红）；📊 用量弹窗（日×渠道×task 聚合表 + 成本 + auth 管理区）；登录 overlay（401 自动唤起 + 登录后重放原请求）；设置/删除访问密码、退出登录入口收在用量弹窗底部。
- **v6（2026-07-22）**：M1 资料库 —— 学习资料弹窗加「资料库」tab（清单/预览/重扫/注册）；📚 备课 chip（讲解回合确定性预取教材节选）与 📄 READ_DOC chip（AI 主动读教材，章节自导航），资料 chip 不跳代码浏览器。
- **v5（2026-07-22）**：P0 教学真实性 —— AI 读文件 tool-use 闭环（`[READ:路径:Lx-y]` 行缓冲截获 → 真实代码注入续写，前端 📖 chip 可点击跳转行高亮，限 3 次/回复）；Mermaid 图渲染（vendor mermaid@11，主题随布局，失败回退代码块）；prompt 硬约束扩到 8 条；走查 49 项全绿（新增 mermaid/tool-use 5 项）。
- **v4（2026-07-22）**：多工作区通用化 —— 顶栏工作区下拉（切换/新建/重新扫描），初始化向导（表单→扫描预览→LLM 生成→验证管线→自动切换），品牌与代码根随工作区隔离。走查 46 项全绿。
- **v3（2026-07-22）**：双模式重构 —— 「知识学习」暖纸书房风（米白 #f5f0e6 + 赭石 #bc6c3b + 衬线标题 + 深棕侧栏）；「源码学习」IDE 风（#1e1e1e 编辑器底 + #0e86d8 状态蓝 + 标签页文件头 + 底部状态栏）。三区分离布局：侧栏纯仪表盘（单元改状态圆点、同步计数并为一行）、顶栏分段模式控件 + 工具图标、输入框上方指令胶囊条 + `[` 补全菜单。移除：深色切换按钮、layout-toggle 悬浮胶囊、面板宽屏/拖拽。
- **v2（2026-07-22）**：整体视觉打磨 —— 靛蓝品牌色系 + 渐变强调、侧栏分区卡片化、聊天气泡居中栏（≤880px）+ 渐变用户泡、悬浮胶囊输入条、全局滚动条/选区/焦点环样式、表格斑马纹、代码复制按钮悬停显现。
- 走查脚本 v2 起**自包含**——真实发送片段提问验证卡片渲染+流式+刷新回填，结束时自动 `POST /api/session/reset` 清理测试消息。

## 待办 / 已知边界

- opencode 解封后自动回主渠道，无需操作
- Study.md 需当日 `## Day N |` 细化小节才能 start_day（Day 3+ 还是路线图格式，需 CLI 助手先细化）
- 复盘题量靠 prompt 约束；编码启动模板由 LLM 填充；仓库校验简化
- v1 未做：模拟面试模式、论文联网检索、多用户、桌面打包

## 上下文恢复指引（新会话）

1. 读本文件 + `AGENTS.md` + `docs/InteractionModel.md`；接开发任务读 `docs/AgentDesign.md`（v3 封板，M1-M7 分期与全部硬规）
2. 跑 `python -m unittest discover -s tests` 与 `python resources/hooks/validate_study.py ../docx 25 ragent-replica` 确认基线
3. 服务若在跑（8765）：`python scripts/ui_walkthrough.py` 全量 UI 走查
4. 前端改动后必须 Playwright 点击走查再交付；提交走分支 + 三件套全绿

