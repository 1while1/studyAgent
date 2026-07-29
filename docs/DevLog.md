# DevLog — study-web 开发日志与交接上下文

> 用途：跨会话/压缩后恢复上下文。记录当前状态、关键设计决策、已修复 bug 史。
> 最近更新：2026-07-29（**改进3: 跨币种成本聚合修复**（fix/cross-currency）——`backend/services/observer.py` `usage_summary()` 按币种分桶聚合：`_acc()` 增加 currency 参数，`totals`/`kpi`/`today`/`by_ws`/`by_model`/`by_task`/`rows` 均新增 `costs_by_currency: dict[str, float]`，保留 `cost` 字段向后兼容。`frontend/usage.js` `fmtCost(c, costsByCurrency)` 支持多币种显示（CNY→¥/USD→$/EUR→€，多币种 `¥12.3 / $0.1`，单币种保持原样）。`frontend/app.js` usage 弹窗同步适配。测试 +2 用例（跨币种聚合 + 单币种向后兼容，583 全绿））
> 前次：2026-07-29（**改进2: mark_wrong 工具实现**（feat/mark-wrong）——`backend/engine/tool_registry.py` 新增 `_mark_wrong` handler + ToolSpec 注册（permission=WRITE）。防幻觉闭环关键工具：用户标记讲解有误，自动写入纠正证据（delta=-0.05）到学习者模型，source_ref 同日幂等，fail-closed 天数解析。injection 文本供 LLM 感知纠正历史。测试 +4 用例（581 全绿））
> 前次：2026-07-29（**改进1: FastAPI API 文档启用**（feat/api-docs）——`backend/api/middleware.py` auth_gate 豁免路径显式添加 `/docs`、`/openapi.json`、`/redoc`。FastAPI Swagger UI 现可通过 `/docs` 直接访问。测试 577 全绿）
> 前次：2026-07-29（**W4 工程基础设施改进**（chore/infra）——① `requirements-dev.txt`：playwright 开发依赖分离（psutil 保留 `requirements.txt` 运行时依赖）；② `.gitattributes`：统一换行符（`* text=auto`）+ gradle 构建产物 `linguist-generated` 标记；③ `.github/workflows/ci.yml`：GitHub Actions 最低 CI（unittest + validate hook）。测试基线 577 全绿）
> 前次：2026-07-29（**W3 orchestrator 策略模式重构**（refactor/orchestrator-phases）——ChatOrchestrator 324 行 if/elif 拆为 `phases/` 目录 9 个策略文件，PhaseRegistry 按 `matches(session)` 双轴分发（day_phase + current_stage），与 `engine/commands/` 架构同构。4 个共享 helper 下沉 `phases/base.py`（current_unit_title / next_unit_title / interview_title / record_teach_back）。REVIEWING 的 atomic_persist+validator 逐字搬运（G2c 教训）。pending_qa_capture 标志原样保留。审查修复：PrereqPhase 多余 session_store.save 移除、注册优先级对齐计划、StudyingPhase 死导入清理、memory 死参数移除。测试 +41 用例（577 全绿）| validate SUCCESS | 走查 187 全 PASS。外部调用者零改动（routes.py/app.py/测试文件构造签名不变））
> 前次：2026-07-29（**W2 错误可观测性修复批**（fix/error-observability）——W2-1 损坏 JSON 备份+记账（learner_service/notes_service）；W2-2 auth 诊断（verify_password 记账 + _secret stderr）；W2-3 静默 except 统一记账（orchestrator 7处/note_actions 2处/qa_capture 1处/routes prefetch 1处）；W2-4 observer._write 首次失败 stderr；W2-5 config 热重载保护。测试 +8 用例（536 全绿）。三件套：536 单测绿 + validate SUCCESS + 走查 187 全 PASS。铁律 13/15/16 静默语义不变）
> 前次：2026-07-29（**W1 审计 P0 快修批**（fix/audit-p0）——三份外部审计（错误处理/架构分层/综合评审）+ orchestrator 重构提案的落地第一波，总纲 `docs/FixPlan.md`、计划 `docs/fixplan/W1_audit_p0.md`。①版本号提取：`app.py` 字面量 0.2.0 → `backend/__init__.py` `__version__ = "1.0.0"`；②`/api/command` 的 handler.run 异常分支补 `save(snapshot)`——原缺口：handler 崩溃时 session 可能已部分推进落盘却不回滚，与 LLM 失败分支不对称；③validate_hook validator 包 try/except——脚本损坏/运行期崩溃原穿透 `atomic_persist` 令已写入文件不回滚，现转 (False, ...) 走既有 not-ok 回滚 + PersistError；④文档与实现同步：测试数 434→528（AGENTS/README/AcceptanceChecklist 四处）、走查 152→187（含 AGENTS.md:16/README.md:134 两处残留）、「测试不依赖第三方包」改「不引入 requirements.txt 之外」（psutil 实为 pin 的运行时依赖，test_arch_fixes_b 在用）、AgentDesign「pin 版本」改「核心框架 >= 区间 + 其余 == pin」、Playwright 补注 dev 工具不随 requirements 安装。审计误报三条留档（30min 保险丝 idle 是循环计数器非秒数、fc2aed2 提交信息实为正常 UTF-8、pin_today 有 test_mastery_decay_exact 专测）。双子代理审查：代码零 major（采纳 1 条 minor——handler 异常用例改「脏写入+抛错」，磁盘断言可独立变红）；文档抓 524→528 偏差与 152 残留，已修。回归 test_validate_hook×3 + test_command_rollback+1，全量 528 绿 + 走查 187 项全绿。**修复循环流程确立：每波先落盘 `docs/fixplan/W<n>_*.md` 详细计划 → 修复 → 双子代理审查 → 修审查发现 → 三件套 → 合并**）
> 前次：2026-07-29（**Slash 扩展 /clear /model /usage + 测试时间炸弹修复批**（feat/slash-ext + fix/test-time-bombs）——①slash v2：handler 签名加 args 并返回 {"report","clear_screen"}；/clear 清空历史+归档层（同 /api/session/reset 语义），路由发 clear 事件前端整屏清空（含指令泡）再给报告；/model 裸跑报告当前/备用/可用渠道，`/model <渠道>` 直接切换（只重写 [llm] 节不动子节区与 .env，构建失败落 warning 运行态保留旧渠道，与配置弹窗同口径）；/usage 为首个**客户端指令**（registry client=True，前端本地打开用量面板不发请求不留气泡）。execute 返回类型 str→dict，旧用例全改。②修复批（真实日期已走到 07-29，四连假红与本次改动无关——stash 验证 ca60a8a 同样红）：掌握度按真实当天衰减（半衰期 14 天），2026-07-23 证据夹具 6 天后 0.8→0.59 跌破 0.7 达标线，learner_graph×2/prereq/relevance_review 四处假红——新增 tests/datefix.py `pin_today`（patch learner_service.date 对齐夹具时间戳）三处 setUp 钉住；_copy_scaffold 曾被模板内 .gradle/build 二进制缓存 UTF-8 读炸——跳过构建/缓存产物目录 + 非 UTF-8 按字节原样拷贝，清理混入模板的产物（未入库）。回归：slash 14 项 + TestCopyScaffold，全量 524 绿 + 走查 187 项全绿）
> 前次：2026-07-25（**顶栏布局四修复**（fix/ui-topbar-notes）——用户截图反馈四个 UI 问题：①侧栏收起后悬浮 ☰ 盖住顶栏左侧（`body.sidebar-collapsed` 顶栏让位 64px）；②知识/源码切换按钮两种布局位置跳变——**最终方案：模式切换挪为顶栏最右元素**（右缘=顶栏右缘，两布局右缘都是窗口右缘 → 位置零漂移；中途两版「右锚定左邻按钮」都被 pair 400px 窄栏换行击败：右组 580px 注定两行、换行使锚定失效），pair 下左组（工作区+胶囊）一行、右组（图标+切换）一行，图标 30px/隐「笔记」文字/切换按钮紧 padding/顶栏 padding 10 挤出 372px 单行，实测 tutor=16 pair=10 差 6px；③清空历史从顶栏搬到指令胶囊行右端（聊天域操作贴近输入区，红色悬停警示，顶栏只留面板入口）；④笔记入口图标-only 太隐蔽→顶栏按钮加「笔记」文字标签+accent 底色高亮，笔记页加「← 返回学习」大按钮（与 × 同 handler）。顶栏 DOM 重构三区：左组（ws+llm/ctx 胶囊）/actions/模式切换。走查 9m 节 6 项断言锁定（含 rect 不相交、右缘偏移差 ≤24px），全量 517 绿 + 走查 180 项全绿。**注意：本轮起不再同步服务器实例（用户指示），改动仅本地+GitHub**）
> 前次：2026-07-25（**M11 Slash 指令系统 v1：框架 + /compact**（feat/slash-commands）——与 `[指令]` 并存的 `/` 系统指令命名空间，即发即执行不走教学回合。后端 `engine/commands/slash.py` 注册表（handler(deps,session)→Markdown 报告）+ `POST /api/slash`（全程流程锁，会话有变化才落盘）+ `GET /api/slash/commands`；/compact 复用 `ContextManager._compress` 手动构造 plan（保留最近 4 条原文、窗口首条对齐 user 不拆问答对），继承全部护栏（概念 ID/问题数机械校验、失败原文全保留、失败写冷却），手动触发绕过冷却检查；指令与报告**不写入 chat_history**（系统操作不污染教学上下文）。前端：loadCommands 并联拉 slash 列表（旧后端静默降级），updateCmdMenu 双模式（`/`→系统指令组 / `[`→学习指令组，加分组标题 div，键盘导航天然跳过），submit 分流 `^\/\S`→/api/slash。MockLLM 补压缩分支（回显概念 id + 0 未决问题必过校验），Mock 渠道下压缩链路（自动+手动）首次可走通。回归 test_slash_commands 8 项（正常路径/不足保留线/校验失败保留/user 对齐/续压/路由隔离/未知指令/info 形状），走查 9l 节 9 项（菜单/分组标题×2/回填/报告/压缩成功/归档生效 0→21），全量 517 绿 + 走查 174 项全绿）
> 前次：2026-07-25（**压缩决策实测校准 + ratio 小样本剔除**（fix/ctx-compression-calib）——用户追问「上下文来回跳太大是否有毛病」排出来的真问题：Agnes 网关每请求有固定计数开销（"Say OK"报 254 prompt），小样本把 observer.ratio EWMA 拉到 6.47，**assemble 用失真估算做压缩决策 → 真实 ~50K 就会过早压缩丢历史**（256K×0.8 触发线被虚高 4 倍）。双修：①log_llm 学习加样本下限（in est<400 / out est<100 不参与，warmup out=1 这类也不再污染）；②assemble 全部估算乘 session.ctx_calib（M8 已落盘的实测/估算系数），压缩触发回到真实水位，无 calib 会话保守走原口径。已清空被污染的 agnes ratio 条目（DS 0.77 健康保留）。回归 test_observer+2（小样本拒学/大样本照学）、test_context_manager+2（cal=0.25 不早压/cal=1 旧行为），全量 509 绿）
> 前次：2026-07-25（**M8 上下文仪表改校准系数制**（fix/ctx-calibrated-display）——用户反馈刷新页面胶囊数值乱跳（11.9K↔70K+）：旧口径锚定「最后一轮 LLM 调用的实测 prompt」，而指令轮（SOP 卡+教材注入）与日常轮 prompt 差 10 倍（日志实测有 282K 的 tool-use 轮），锚它必跳。新口径：**calib = 实测 prompt / 本地估算 prompt**（随每次实测轮自动修正、持久化 session.ctx_calib），显示 = 当前会话装配估算 × calib——只随会话内容（新消息/压缩/清空）变化，刷新/重启完全稳定（有稳定性契约测试）。前端 tag 改「实测校准」，tooltip 透出 last_measured 参考值。排查顺带发现：agnes 网关小请求也报 254 prompt（固定开销/计数口径差异），observer.ratio 被 282K 离群轮拉大到 ~4.2——calib 层与 ratio 层在显示上自抵消（display≈实测），但 **留档🟡**：ratio 失真会影响 assemble 压缩决策（高估上下文→过早压缩），后续考虑 ratio 学习加离群剔除或按 prompt 规模分段）
> 前次：2026-07-25（**M10 查看器时序图 0×0 修复**（fix/viewer-svg-size）——用户点开 sequenceDiagram 只显示一小块：Mermaid svg 是 width="100%"+style max-width，克隆后清掉宽高落入缩容容器 .viewer-content 算成 0×0（此前自测只覆盖 graph LR 未暴露）。修：克隆钉真实尺寸——优先 viewBox 设计尺寸（矢量 1:1 基准），无 viewBox 回退原图 getBoundingClientRect 上屏像素；img 同步钉 naturalWidth/Height。走查 9e3 补「克隆图非零尺寸」断言防回归。截图目验时序图完整渲染，三件套全绿）
> 前次：2026-07-25（**Agnes 免费渠道接入**（feat/agnes-provider）——DS 太贵切 Agnes AI：OpenAI 兼容复用 OpenAICompatClient，factory 注册 "agnes" + _PROVIDER_META 元信息，settings.toml 加 [llm.agnes]（agnes-2.0-flash，apihub.agnes-ai.com/v1，key 走 LLM_API_KEY_AGNES 入 .env）+ [model_context] 512K（**点号键必须加引号防 TOML 拆嵌套表**，有回归测试）+ [pricing] $0 USD，provider 切 agnes 无 fallback（用户明确嫌 DS 贵，防静默烧额度）。双子审查收编：走查「配置弹窗-渠道数」硬编码 ==2 改动态 len(sections)；**预存缺陷修复**——save_llm_config 热重建 create_llm 缺 key 抛 500（配置已落盘但报保存失败），改 try/except 落 warning 返回 + 前端 status 显示不自动关窗；.gitignore 补 `.env.*`+`!.env.example`（.env.authbak 类密钥备份差点入库）；.env.example 补三渠道示例；测试虚账清理（同义反复断言改 _section_view 真实调用、补 save 往返+缺 key warning 测试、env 对称保存恢复）。回归 test_agnes_provider 11 项，全量 504 绿。**留档🟡**：agnes 是仓内首个 USD 渠道——observer.totals 跨币种直接加总 + usage.js fmtCost 硬编码 ¥，当前 $0 定价无实际影响；恢复收费改价时 test_pricing_free_zero 必红当提醒，届时需同步处理币别聚合/显示）
> 前次：2026-07-25（**M10 内容放大查看器**（feat/content-viewer）——AI 气泡里的 Mermaid 图/图片/代码段全屏查看：frontend/viewer.js 一次性建 #viewer-overlay（z300）；图表=滚轮锚点缩放（0.05~8)+拖拽平移+适应/1:1（克隆 svg 清 width/height 靠 viewBox 自适应，SVG 放大不糊），代码=clone pre 全宽+换行开关+复制；injectZoomButtons 给 pre 加「放大」按钮（与复制并排）；bindContentViewer(document.body) 事件委托+幂等，覆盖消息流/文档/话术库/笔记预览所有 markdown 面（modal z100<300 层级安全）。双子审查收编 7 项：复制改 clone 剔除 button 取文本（原 innerText 带「复制放大」尾巴）、拖拽松手>5px 抑制 click 误关闭、img 未加载完 load 后重 fit、stage mousedown preventDefault 防原生拖拽打断、close() 重置换行态、绑定幂等防重复委托。走查 9e3 段+自测 12 项（含三回归断言）全绿，全量 493 绿）
> 前次：2026-07-25（**M9 Token 用量模块优化**（feat/usage-module）——五合一：①成本算准：采集 cache_hit_tokens（DeepSeek 顶层/OpenAI details 两形态，续写累加），[pricing] 补 v4-flash(1/2/0.02)/v4-pro(3/6/0.025) 官方刊例 + [pricing.peak] 峰谷 ×2（9-12/14-18 按记录 ts 套倍率），成本=未命中×input+命中×cache_hit+输出×output；②按项目统计：ObservedLLM 构造钉入 workspace slug（_rebind 重建保证新鲜），记录加 ws 字段，旧记录归「（旧记录）」桶，接口 ws 过滤 + by_workspace 汇总；③独立统计页 /usage.html：KPI×6（总调用/输入/输出/成本/缓存命中率/失败率）+ CSS 日趋势堆叠柱 + 按项目/模型/任务三栏 + 全维度明细（口径列 实测X/估算Y）+ 天数(1/7/30/全部)×项目筛选，401 提示回主页不毁容器，主题跟随 localStorage.layout；小弹窗瘦身为今日+近7天速览+跳转链接；④今日速览：Observer._seed_today 启动回填（重启不归零），context-status 加 today，ctx 胶囊 tooltip 带今日消耗（口径：顶栏=全局合计，统计页过滤视图=该项目今日）；⑤日志滚动：>10MB 轮转 agent.log.1 一档（轮转失败不丢记录，聚合窗口≤当前卷）。双子审查收编：负成本 clamp、401 后筛选不炸、chart-day textContent 防注入、走查 9e2 改 new_context+请求监听。回归 TestUsageM9 7 项+缓存采集 2 项+context-status today/usage 路由 2 项，全量 493 绿）
> 前次：2026-07-24（**M8 上下文占用仪表**（feat/context-meter）——账本式：每轮 SSE done 后把 API 实测 prompt/completion 落 session（ctx_prompt_tokens/ctx_completion_tokens/ctx_measured），降级轮（网关不认 stream_options/mock）标 measured=False 保留旧实测值；GET /api/context-status 实测锚定：total=实测总量，三层（钉住/归档/窗口）本地估算按占比等比缩放；顶栏 #ctx-pill 水位条（绿/amber/红，悬停看三层分解+压缩阈值），pair 布局保持可见，SSE done + 15s 轮询双刷新。**连带修出预存 bug**：DeepSeek 把 usage 挂在带 finish_reason 的内容块上（choices 非空），openai_compat 原只在空 choices 块读 usage → 官方渠道全程漏记账；改为与 choices 无关先查 chunk.usage（OpenAI 独立末块/DeepSeek finish 块两形态均覆盖）。双子审查收编：ObservedLLM/FallbackClient 每轮重置+镜像 last_usage（否则主渠道降级轮会锚定 fallback 陈旧值永不自愈）、extract_usage 改实例级权威判定、command 流账本补测试、前端 404 垃圾值防御。回归 test_context_meter 9 + TestUsageCapture 2，全量 483 绿）
> 前次：2026-07-24（**LLM 输出截断修复**（fix/llm-length-continue）——用户反馈长回复「讲着讲着断了」：openai_compat 流式循环从未读 finish_reason，输出撞 max_tokens=4096 时流干净结束、半截回答被当成完整回复渲染（v4-pro 思考链也吃输出预算，更容易撞）。修：拆 _stream_once 捕获 finish_reason，length 时携带已生成内容自动续写（1+4 轮，SSE 无缝拼接）；显式小预算调用（warmup=1/压缩摘要）不续写；仍超限末尾明示可手动「继续」；多轮 usage 累加记账。回归 test_openai_compat_continue 4 测试（自动续写/不续写/显式预算豁免/超限明示）。另：DeepSeek 官方渠道模型名 deepseek-chat 已下线，配置页改为 deepseek-v4-pro 后真实渠道恢复）
> 前次：2026-07-24（**面试相位出口提示修复**（fix/interview-exit-hint）——用户反馈「卡在模拟面试」：相位锁是有意设计（防状态分裂），[恢复学习] 本就可放弃面试，但 9 处拦截文案从不告知出口，清空历史后产生「卡死」感。修：base.py 统一 INTERVIEW_EXIT_HINT 常量，9 处 fail_fast 拦截文案全部追加「（想放弃本场面试可 [恢复学习] 退出，不留成绩）」；回归 test_interview.TestInterviewExitHint（9 handler 逐一断言文案含出口））
> 前次：2026-07-24（**完成度验收 G12 交付——工程质量 5 项 ✅ 含修复批**：command 回滚快照补测试引出的 [超前学习] 死胡同修复（幂等续学+分裂态护栏）+ 测试变异防护/动态 Day；详见「G12 验收修复批」）
> 前次：2026-07-24（**完成度验收 G11 交付**——UI/UX 8 项 ✅ 无修复批：_accept_g11.py 截图复核双主题无串色（tutor 暖纸/pair 深色）+ 五弹窗主按钮钉底视口内 + toast 位置 CSS 校验；11.1/11.3/11.5/11.6/11.7 走查引用打勾）
> 前次：2026-07-24（**完成度验收 G10 交付**——可观测与安全 6 项 ✅ 无修复批：_accept_g10.py e2e 验证双客户端并发（流程锁串行化、历史不丢不串、前端渲染一致）；10.1 agent.log 手动核查 + plan/prefetch 记账单测打勾、10.5 三道拒读单测打勾）
> 前次：2026-07-24（**完成度验收 G9 交付**——上下文与模型渠道 6 项 ✅ 无修复批：_accept_g9.py e2e 验证 fallback（openai_compat 401→mock 接管）与 warmup 开关（false 无预热/true 重启出现 task=warmup 行）；9.1/9.2 test_context_manager、9.3/9.4 走查 6 打勾；留档：mock 按设计不记账，fallback 双记录仅真实备用渠道成立）

## 当前运行状态

- **Git**：`study-web/.git`（main）→ GitHub <https://github.com/1while1/studyAgent>。密钥 `.env`/`opencode.txt` 与数据 `runtime/`、`workspaces/` 已 gitignore。提交流程：分支 + 三件套验证（单测/validate/走查）全绿才 commit
- 启动：`cd study-web && python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8765`
- LLM：主渠道 `agnes`（Agnes AI agnes-2.0-flash，当前免费，**当前实际工作渠道**，无 fallback——防静默烧 DS 额度）；
  备用 `deepseek_official`（DeepSeek 官方 deepseek-v4-flash，已充值）/ `openai_compat`（OpenCode Go，被上游 401 风控拦截，待解封）
- fallback 自动切换已生效（`llm/fallback.py`）
- 工作区：ragent（默认，`../docx`，Day 2 学习中，`materials_dir=../RAgent文档` 68 份资料已解析）/ tinyrag（5 天测试，可删）/ onecoupon（25 天，用户项目，初始化验证通过 25/25）
- 测试：`python -m unittest discover -s tests` → 583 个全绿；UI 走查 187 项全绿
- ⚠️ 走查结束会 `POST /api/session/reset` 清测试消息——**有值得保留的对话时不要跑走查**
- ⚠️ 服务器实例（111.229.31.41:8765，systemd study-web）：**用户要求 2026-07-25 起不再自动同步**——代码改动只本地验证 + 推 GitHub，除非用户明确要求否则不要动服务器

## 下一步

v1 Roadmap 与 v3 分期（M1 资料库 → M2 可观测 → M3 学习者模型 → M4 笔记管理 → M5a 工具骨架 → M5b 上下文+路由 → M5c planner → M6 实战工坊 → **M7 课程本体 ✅**）全部收官；架构审计修复批 ✅、UI 全面优化 ✅、全功能浏览器测试（152 项）✅。

**当前阶段 = 完成度验收**：G1-G12 全部 ✅（G2/G3/G6/G12 含修复批）。收尾：清理 scripts/_accept_*.py 临时验收脚本 + 验收记录节填写 + 最终三件套。按 `docs/AcceptanceChecklist.md` 逐项检查（实测打勾，发现问题开修复批：分支 + 三件套全绿 + 双子审查 + 合并 push）。mark_wrong 工具（§9）与「command 失败外部落盘不回滚」修复批仍留档另立。

## G12 验收修复批（2026-07-24，fix/g12-command-rollback-test，双子审查收编）

验收 G12（工程质量 12.5）发现 command 回滚快照（routes.py:257）无单测 → 补测试 + 双子审查，连带修出预存缺陷：

| 发现 | 修复 |
|------|------|
| 🔴（审查 B）[超前学习] 死胡同（预存缺陷）：超前单元落盘后 LLM 失败回滚 session → 重发 [超前学习] 被「还有 1 个未完成」拦截、[下一内容] 把 completed 改回 in_progress 撞 validator 报「指令执行失败」，唯一出口 [恢复学习] 但用户无从得知 | next_content ahead 分支幂等续学（remaining 仅剩超前单元时定位续学而非拦截）；常规分支分裂态护栏（session 定位不在超前单元时引导 [恢复学习]/[超前学习]，session 定位在超前单元的正常流程不误伤）。回归 test_arch_fixes 三新测试 |
| 🔴（审查 A）新回滚测试变异杀不死：[同步] 不改 session，删掉 save(snapshot) 测试照样绿 | spy SessionStore.save：断言失败路径恰好 save 一次且内容=指令前快照；补中途断流变体（部分输出同样回滚） |
| 🔴（审查 A）Day_02.md 硬编码，真实进度推进后假性变红 | 从复制的 StudyState.json 动态读 current_day |

留档（🟡 不阻塞）：handler.run 异常路径无回滚（routes.py:242，铁律 10 仅覆盖 LLM 失败）；重复 [同步] 无去重（append_sync 幂等缺失，notes 层 source_ref 已去重）；refresh_project_md 直写无备份；LLM 失败后前端已显示 sync 汇总但 chat_history 无痕迹（上下文轻微失真）。

## G3 验收修复批（2026-07-24，fix/g3-relevance-first-start，双子审查收编）

验收 G3（AI 导学质量）实测发现：

| 发现 | 修复 |
|------|------|
| 🔴 跨日首次 [开始今日学习]【上游感召】静默为空：感召计算在当日 units 落盘前执行，而 learner_with_concepts 从磁盘 load StudyState——跨日首次时当日 units 尚未落盘（末尾才统一原子落盘），当日 concept 注册不上 → 先修闭包为空（F1 同款缺口在 start_day 的残留；同一天内 restart 因磁盘已有 units 而不显，正好掩盖了它） | start_day 把 today/day_data/units 填充块上移到感召计算之前；base.py 拆出 `ensure_concepts_for(deps, svc, state)` 支持内存态 state，感召块改走内存态 ensure；其他调用方仍走 learner_with_concepts 磁盘路径（语义不变） |
| 🔴（审查）新回归测试空心：真实 docx 副本自带 Day2 concepts 条目，不剥离则旧代码下闭包也非空、测试修复前后都绿 | fixture 补剥离 concepts.json 非 Day1- 条目（仿 test_f1）；修复前实测变红=真回归门 |
| 🟡（审查）Day2-A 跨天边断言写死 Day1-E，依赖真实数据 Day1 单元数 | 放宽为 `len==1 且 startswith("Day1-")` |
| 🟡（审查）ensure_concepts 立即落盘 concepts.json 与末尾 atomic_persist 回滚存在不一致窗口 | 注释钉住：派生数据幂等 upsert、可自愈，有意为之 |

G3 手动项 e2e（scripts/_accept_g3.py，tinyrag+Mock）5/5：3.1 📚 备课 chip / 3.4 感召 / 3.5 回合复习 / 3.6 间隔复习（感召占满 6 封顶时日历项让位=设计，故 3.6 在无感召场景验证）；3.2/3.7 走查 9c/7c、3.3 test_tool_use 打勾。460 单测/155 走查全绿。

## G2 复盘修复批（2026-07-24，fix/g2-review-persist，双子审查收编）

验收 G2c（复盘/结束日流程）实测发现：

| 发现 | 修复 |
|------|------|
| 🔴 复盘评分落盘不同步 overall：REVIEWING 分支评分写 StudyMemory/StudyState 但不重算 overall_percentage，Study.md 表头不更新——复盘全流程"全废"（数据落但汇总错位） | orchestrator REVIEWING 分支复用 `recompute_percentage` 同步 overall + Study.md update_header 同原子落盘；plan.read() 异常降级只落 StudyState |
| 🔴 REVIEWING 状态下 next_content/day_review/jump_day/code_mode 未被拦截（阶段矩阵缺口） | 四指令 REVIEWING 拦截补齐 |
| 🟡 jump_day 跳回已结束天无法重学：`active_day_completed` 标记未清 | jump_day 重置时清 `active_day_completed`（审查 🔴-1 收编） |
| 🟡 backup_service.atomic_persist 写入期失败不回滚 | 写入 try/except 失败即回滚备份 |

测试：test_flows.py TestReviewScore（7 用例）+ test_review_batch.py TestAtomicPersistRollback；459 单测/validate/155 走查全绿。G2c 实测：复盘五项 ✅ + end_day ✅（StudyReview 生成/次日滚动/阶段复位）；真实 LLM 内容质量（题量/字数/反喂质量）标环境阻塞（DeepSeek 402 + opencode 401）。

## G2 验收修复批（2026-07-24，fix/g2-extras-overwrite，双子审查驱动）

验收 G2a（学习流程手动项）实测发现：

| 发现 | 修复 |
|------|------|
| 🔴 快流下 extras 覆盖 LLM 泡：SSE `message` 事件用 `bubble.textContent` 判空决定是否新建气泡——Mock/快流渠道 LLM 文本已累积 `rawText` 但 200ms 节流渲染未触发（textContent 仍空）→ 不新建泡 → extra（next_preview/复盘落盘消息等模板）直接覆盖 LLM 泡，评分/点评本轮从 DOM 丢失（落盘与历史回填不受影响；真实慢流渠道难触发，G2a Mock 验收当场抓住） | message 事件先把 `rawText` 终渲染落泡再开新泡放模板（`renderMarkdownInto(bubble, rawText)` + 判据加 rawText）；五态组合（FAIL-FAST 纯模板/LLM+extra/连续多 message/LLM 无 extra/tool_read 交错）经双子审查逐一验证无裂缝 |
| 🟡 走查缺口：extras 场景无 DOM 级断言 | +2 断言：9c+ 面试终评「快流下 LLM 评分泡不被 extra 覆盖」；9j 段「command 多 message 后 LLM 泡完整」（③ 回归锁，增量判定） |

🔴 留档（既有问题，本批不修，另立）：**command 流 LLM 失败的回滚只回滚 session 对象，handler `run()` 内的外部落盘（atomic_persist StudyState/StudyMemory）不回滚**（routes.py:257 vs next_content.py:43-46 等）——与铁律 10「整体回滚」文本有出入，修复涉及失败语义重设计（快照重放 vs 延迟持久化），连同 🟡「result.messages 先于 LLM 成功下发，回滚后屏幕文案与状态矛盾」「chat/command 失败语义分叉（chat 保留用户消息 vs command 回滚指令）」一并另立批次评估。

G2a 复验 20/20 全过；走查 155 项全绿（+2 断言）。

## G1 验收修复批（2026-07-24，fix/g1-doc-prefix，双子审查驱动）

验收 G1（工作区与初始化）实测发现，三路问题一批修：

| 发现 | 修复 |
|------|------|
| 🔴 新建工作区初始化必失败：LLM 生成 Study.md「文档」字段带项目目录名前缀（`temp_tinyrag/pom.xml`），`check_unit_docs` 以 project_dir 为根校验必报「文档路径不存在」（画像树根行带项目名，LLM 照抄；tinyrag 重建真实命中） | `study_plan.strip_project_doc_prefix`：只动「文档：」行，token 统一分隔符/剥反引号/反斜杠归一后循环剥前缀；**exists 谓词条件剥离**（原 token 在 project_dir 内存在则保原样——双子审查 🔴：同名包布局 `foo/foo/core.py` 防误剥）；doc_initializer._generate 加 normalize 钩子（剥围栏后校验前）+ end_day._detail_next_day 同款接线；prompt×2 契约加固（内部相对路径禁前缀/项目外资料用绝对路径） |
| 🟡 validator 误报全新工作区：骨架 `days:{}`（单元由 start_day 注册）撞「Day N data not found」，初始化完成态自检不过 | `check_day_consistency`：days 整体为空（合法初始态）跳过；非空但缺当天仍报错；+2 用例 |
| 🔴 rescan/create 裸 500：LLM 调用异常（402 余额/401 风控/网络）不在路由 except（WorkspaceError/InitError/FileNotFoundError）内（1.4 重扫真实命中 DeepSeek 402 → HTTP 500） | `_generate` LLM 调用包装 InitError「{label} LLM 调用失败：{e}」→ 路由契约 ok=False 友好错误（实测 HTTP 200 + 原因文本）；零文件落盘 |
| 🟡 走查依赖真实 LLM：9 聊天/7b 片段段用当前渠道，DeepSeek 402 后 150/153（3 项连带失败） | 走查开头渠道归一 Mock + 结尾还原（原 9c/9i 段内切换保持幂等）；走查不再依赖渠道可用性 |

测试 +17（test_doc_prefix 15：纯函数 9 含同名包回归锁/反斜杠/多文档行/分隔符锁定 + 初始化集成 2 含反向锁定 + LLM 异常包装 + end_day 接线；validate_schemas +2 空 days/缺当天）；**451 单测全绿**；validate 双工作区绿；走查全绿（Mock 归一）。

⚠️ 环境备注：验收期间 DeepSeek 402 余额不足 + opencode 401 风控双渠道全灭——真实 LLM 依赖项（1.4 生成路径、G2/G3 内容质量项）标「环境阻塞待充值」，流程项以 Mock 渠道驱动验收。

## 架构审计修复批 · A 包（2026-07-24，engine/api/resources 族，fix/arch-review）

| 发现 | 修复 |
|------|------|
| 🟡 Y1 用户面模板/预设写死项目字面量（ragent / 25 天） | SOP_开始今日学习 step1 `Day <N> / <总天数>`、step3 `<复现名> 完成 <模块>`；SOP_结束今日学习 study_review_doc `## 6. <复现名> 编码进度`；SOP_开始写代码 卡体 4 处 `<复现名>`；presets×3 + settings [[stages]] instruction 改 `<复现名>`/`<项目名>` 占位。**替换只在消费处**（模板单源与锚点不动）：start_day `_render_step1/_render_step3`、end_day study_review_doc 注入处、`CommandHandler.read_sop_card`（唯一读卡点）、prompt_builder 阶段指令注入处（唯一 instruction 注入路径，`<项目名>` 取 `project_dir.name`） |
| 🟡 Y2 end_step1_sync 占位符泄漏 + 「已解决」恒 0 | end_day Step 1：有待解答 → 警告行替换 `<Y>` 真实计数，无则整行移除；「已解决 `<X>` 项」接 NotesService 当日 resolved 卡壳只读计数（铁律 16 语义不变） |
| 🟡-1 销账后 StudyMemory「（待解答）」残留 | `note_actions.resolve_note`（铁律 16 单一路径）销账 question 条目时摘除当日疑问行对应后缀（分隔符保界防子串误摘，规则 14 落盘，异常静默不阻断） |
| 🟡-2 end_day 后阶段残留 / 相位未短路 | end_day 落盘处 `session.current_stage` 置 `""`；orchestrator `instruction_for/post_process` 顶部 ENDED/NOT_STARTED 短路（`""`/`[]`）；next_content fail_fast 拦 ENDED + 常规分支前「今日单元已全部完成」护栏（防 completed 单元被改回 in_progress） |
| 🟡-5 手改 TOML 非法值炸装配/视图 | context_manager 新增 `_safe_float`（trigger_ratio，同 `_safe_int` 模式）；routes `_context_view` int/float 同款防御；orchestrator `round_review_interval` 解包防御（非二元组/非数值回退 [5,6]） |
| 🟡-7 两个 500 端点 | /api/doc?name=memory 在 StudyState 缺失/损坏时改 `ok=False` 契约；notes_distill 天数解析挪进 try（非法 days 键/非法 body day → `ok=False`） |
| 🟡-8 [同步] 多行内容被正则截断 | sync 子类型正则 `(.+)$` → `([\s\S]+)$`（fail_fast 与 run 两处），多行卡壳/疑问可提交落盘 |
| 🟡-4 persist_state 可绕过评分置 completed | set_unit_status 白名单去 completed（completed 必须走 [下一内容] 正轨带评分，本工具不设 rating 必撞 validator）；schema enum 与描述同步注明原因；既有 `test_persist_state_set_unit_status` 改用 postponed（该夹具 status_enum 补 postponed 对齐真实配置） |
| 🟡 Y11 UI 保存覆盖外部修改 | `workshop_service.file_mtime`（代码根内 stat，失败 None）；/api/code/file 响应加 `mtime`；/api/code/save 接受可选 `mtime`——与当前文件值容差 1e-3 比对，不一致/不可比 → `{ok:False, conflict:True}` 拒写提示刷新；未提供保持现状兼容 |

测试 +23（`tests/test_arch_fixes_a.py`，ArchFixBase 同款夹具）；**428 单测全绿**（含 B 包并行 +12）；validate_study 真实 docx 通过。

## 架构审计修复批（2026-07-23，三路审查驱动，fix/arch-review）

审查输入：架构审计（设计符合性）+ engine/api bug 扫荡 + services/domain/llm/前端 bug 扫荡（详见文末「审计留档」）。结论：架构健康（分层/铁律/§14 不做清单全部成立，无 🔴 违规）；bug 集中在「代码路径 vs validator/确认协议」契约断裂与「done 之后/请求间并发」两个测试盲区。

| 发现 | 修复 |
|------|------|
| 🔴 [超前学习] 100% PersistError（插入行 `单元AA（超前）：` 中缀断链 validator/memory_store 正则族；完成时 set_unit_score 无行可填再撞） | 插入行改 `- [ ] 单元AA：{title}（超前）`（id 紧跟冒号）；set_unit_score 评分区缺行时**补行**（契约级）；超前全流程回归（插入→完成→validate） |
| 🔴 [跳转天数] 三方向全死（目标天无 StudyMemory 时序死锁/确认形态 `"2 是"` 永不命中死循环/`[否]` 未注册死端） | 确认形态改「Day X 是」endswith 判定 + 提示可操作化；目标天无 md 时**补建骨架**（render_new 空单元）；三路径回归 |
| 🔴 /api/command 无 llm_instruction 必抛 UnboundLocalError（纯消息指令每次一条 ASGI traceback，[结束今日学习] 每天命中） | streamer=None 初始化 + 压缩传空计划；路由级回归（fail_fast 纯消息 + handler 纯消息各一） |
| 🔴 session 写路径并发（chat 流多次 save 覆盖 mode/reset、双标签 lost-update、tmp 互踩写坏） | **两级锁**：短 RLock（load/save 原子）+ 流程 threading.Lock（chat/command 流全程 + mode/reset 端点；**非线程绑定**支持 SSE 生成器 anyio 跨线程释放）；前端流式禁切模式/清历史 |
| 🔴 XSS 三处（escapeHtml 不转义引号用于属性 / 代码根名无校验 + insertAdjacentHTML / loadTreeLevel 错误文本 innerHTML） | escapeHtml 补引号转义；代码根名 `[A-Za-z0-9_-]{1,40}` 白名单；两处改 DOM 构建 |
| 🔴 TOML 写入可写坏 settings（model/base_url 引号换行未转义致全站 500；未提交节区被 env 解析值/meta 固化覆写） | _esc 统一（补换行转义）；llm-config **只写提交的 provider 节区**；写路径改 `_deps.config.path`（可注入）；往返/保留双测试 |
| 🟡 Y1 资源去项目化（step1 `/ 25`、step3 ragent-replica、study_review_doc、SOP_开始写代码×4、presets/stages instruction） | 模板改 `<总天数>/<复现名>/<项目名>` 占位，消费处（start_day/end_day/read_sop_card/prompt_builder）统一替换 |
| 🟡 Y2 end_step1_sync `<Y>` 泄漏 + 已解决计数恒 0 | 有/无疑问两态渲染（行删除）；已解决接 notes.json 当日 resolved |
| 🟡 待解答无移除路径 | note_actions.resolve_note 同步移除 StudyMemory「（待解答）」后缀（规则 14，静默兜底） |
| 🟡 end_day 后 stage 空转 | end_day 复位 stage；orchestrator ENDED/NOT_STARTED 短路；next_content ENDED 拦截 + 全完成护栏 |
| 🟡 配置非法值绕过（trigger_ratio/interval 解包） | _safe_float/解包回退三处 |
| 🟡 两个 500 端点（/api/doc memory、notes_distill int） | ok/error 契约统一 |
| 🟡 sync 拒绝多行 | 子类型正则 `[\s\S]+` |
| 🟡 persist_state 与 validator 互斥（completed 必失败） | 白名单去掉 completed（注明须走 [下一内容] 正轨） |
| 🟡 run_build 超时只杀直接子进程（java 孙进程存活） | Popen + 超时内联杀树（process_mgr 同款，services 不互引） |
| 🟡 GBK 回退整体乱码 | utf-8 严格 → GBK 严格 → utf-8 replace 三分支 |
| 🟡 Study.md 文档错位认领 | 解析窗口限定到下一单元/标题前 |
| 🟡 InterviewQA 坏块连坐降级 | 坏块仅自身进 tail |
| 🟡 openCodeFile 慢响应覆盖新选择 | 递增序号三处过期校验 |
| 🟡 resolve_doc 后缀无边界 | endswith 改 `t == il`（词干兜底保留 ≥4 字符） |
| 🟡 Monaco model 泄漏（hint/legacy 路径） | mcModel 句柄 + disposeMonaco 统一销毁 |
| 🟡 笔记合并 keep 与文案不符 | 点击序记录替代 DOM 序 |
| 🟡 UI 保存无冲突检测（AI/外部改动被静默覆盖） | /api/code/file 返回 mtime；save 带 mtime 比对（不一致 conflict 拒写 + 保留脏标记）；save 响应回新 mtime |
| 🟡 mode 切换相位护栏 | INTERVIEW/PREREQ/REVIEWING 中切模式 → 清相位字段 + note 明示 |
| 🟡 Y3 InteractionModel §3 决策 2 名存实亡（5-6 轮只提示不渲染） | render_mastery_check 下沉 commands/base.py 两触发源共用；orchestrator 自动触发**真渲染**（选项原样） |

🔵 留档见文末「审计留档」节。测试 +50 → **432 全绿**；走查 139 项全绿。

## M7 审查修复批（2026-07-23，双子 agent 审查驱动，fix/m7-review）

| 发现 | 修复 |
|------|------|
| 🔴 F1 图谱消费方读前未 ensure_concepts——跨天先修边写在**后一天**节点上，新日窗口（当日单元未注册）感召静默为空 + [先修诊断] 假阴性「无需诊断」（interview.py 有 M5c 存量同款缺口） | prereq/start_day/interview 三处改走 `CommandHandler.learner_with_concepts` 统一入口（sync/next_content/verify_code 同款）；F1 回归测试（concepts 无当日条目感召仍出现）；test_interview.test_pick_empty_model 按 ensure 语义更新（两分支各断言） |
| 🟡 F2 extract_scores_by_cid 无前缀边界——短 cid「Day5-A」可窃取「Day5-AA」评分行（恰好漏行场景跳过缺分重试直接污染证据） | cid 后加 `(?![A-Za-z0-9_])` 边界；前缀对回归测试 |
| 🟡 F3 行为矩阵缺口——next_content/sync/verify_code/code_mode/jump_day 无 phase 检查（INTERVIEW 期即存在的系统性形态，PREREQ 使暴露面 +1） | 5 指令 fail_fast 补 INTERVIEW+PREREQ 双拦截（getattr 防御 None session）；矩阵测试（双相位 × 5 handler） |
| 🟡-1 test_relevance_review 硬依赖真实数据三假红路径（用户推进天数/mastery 演进/日历项出现） | 夹具三处钉住（current_day=2 单元重置 + 删 learner_model + 清 Day_01/02）；"无感召"用例改全达标证据夹具（F1 后 ensure 必重建 concepts，空文件路径不再存在） |
| 🟡-2/🟡-3 文档漂移：「逐字节一致（测试锁）」名不副实；README「11 个触发指令」未随 13 同步 | README/DevLog 措辞诚实化（diff 保证 + 回归测试锁无感召字样）；README 改 13 |
| 🟡-4 走查 9f 徽标/hover 弱断言（存在性即过 + 无清除断言） | +徽标语义 title 断言 + 移开后高亮清除断言 |
| F6 interview labels 缺 PREREQ 专属文案 | 补「先修诊断进行中，请先完成本场诊断」 |
| 🔵-2 时间轴 querySelector 未 CSS.escape（与战术板不一致） | 改 CSS.escape |

🔵 留档（不阻塞）：prereq_of「最近目标」名实偏差（现役单目标无消费者）；出题解析不耐受换行题面（fail-closed 方向安全）；jump_day 不清 prereq 字段（惰性无害，start_day 兜底）；etype 未配置误报幂等跳过（配置齐全前提）；感召/日历语义重复项不去重；前端上游闭包为近邻序（仅计数/高亮用途）；mock.py `system` 变量命名；「恰好一题」契约实为「至少一题」（重复静默取最后）；9i 幂等段依赖 mastery 基线 <0.3。测试 +3 → **382 全绿**；走查 139 项全绿。

## M7 课程本体（2026-07-23 交付）

- **图谱纯函数**（`domain/learner.py`，零 IO）：`upstream_closure(cid, prereq_map)`（DFS 后序=根基在前，**环守卫**（成环跳过回边）+ 缺失节点容忍）、`topo_order(cids, prereq_map)`（闭包深度升序=上游先补，id 稳定序 tiebreak——初版按深度降序写反被单测当场抓住）
- **LearnerService 图查询**：`upstream_chain(cid)` / `unmastered_upstream(cids, day, threshold=0.7)`（**含零证据节点**——先修诊断"已会节点置初始 mastery"核心场景；prereq_of 记录最近目标）/ `remediation_order(day, threshold)`（仅**有证据**未达标，零证据标「未学」不计入——M5b R4 先例）
- **感召式复习**（§13 验收形态，start_day 集成）：今日首单元 concept 上游未达标闭包（拓扑序）打【上游感召】标签注入 step1「将优先安排」与 review_prefix 分组（**感召优先 + 日历补充 + 总量封顶 review_max_items**）；collect_due 日历通道保留为补充；**无感召时输出与 M7 前形态一致**（diff 保证 + 回归测试锁无感召字样）；plan 解析上移至 RESUME 分支之后（保 resume 不解析大纲的原行为）
- **拓扑计划 v1**：`remediation_order` 进 /api/learner/model（图谱异常静默降级 []）；战术板「需要行动」桶改拓扑补弱序（不在序列的达标到期项沉底）；**Study.md 动态重排/LLM 建议边 = 留档**
- **先修诊断**（`[先修诊断]`，行为矩阵与面试对称）：
  - **代码强制选题**：当前单元上游未达标闭包拓扑序前 5（含零证据）；无目标→明确提示不开空头诊断
  - **出题**：一次非流式 LLM（新策略卡 `resources/pedagogy/prereq_quiz.md`）→ **机械校验每 cid 恰好一题**（缺一带原因重试一次，再不齐 fail-closed 不开场；缺卡 fail-closed 同面试 R7）
  - **评分**（orchestrator PREREQ 分支 + `DayPhase.PREREQ`）：逐 cid 提取 `DayN-X：【评分：X.X】`（`quiz_engine.extract_scores_by_cid`，分隔容忍 `**：` 等形态，1.0-5.0 契约）→ **机械校验全覆盖**（缺一提示重试一次，retry 用尽→取消诊断**不写证据**）→ ≥及格写 `prereq_pass`（+0.40，爬升档不超 0.7）否则 `prereq_fail`（−0.10），source_ref=`prereq:{cid}:{date}` **同日幂等**（幂等命中与真失败文案区分）→ phase 还原 + 汇总（✅/❌ + 已置初始掌握度/幂等跳过/落盘失败）
  - **矩阵对称**：day_review/end_day fail_fast 拦截；start_day/resume 清 prereq 字段；prompt_builder 在 PREREQ 期跳过阶段指令（同 INTERVIEW）；`SessionContext + prereq_targets/prereq_retry`（from_dict 天然兼容旧数据）
  - 排坑：orchestrator 内 `cid, score = q["cid"], scores[cid]` 触发 Python 函数级遮蔽 UnboundLocalError（面试分支下文有同名赋值，改名 tcid）；`from datetime import date` 局部补导
- **UI**：雷达时间轴上游未达标徽标 `▲N`（hover 显示含义）+ **hover 高亮上游链**（点击已占用为跳战术板，高亮走 mouseenter/leave，客户端由 prerequisites 递归环守卫）
- **测试**：+24（test_learner_graph 7：闭包/环/缺节点/拓扑序/未达标过滤/补弱序；test_relevance_review 5：感召标签/排序/分组/封顶/无感召一致/异常降级/start_day 清字段；test_prereq 12：选题/无目标/重试/fail-closed×2/证据 pass+fail/幂等/缺分重试/取消/矩阵/提取器）→ **379 全绿**；走查 137 项全绿（+9i 先修诊断全流程（Mock 渠道双分支+存在性备份还原）+徽标/hover 断言）

## M6 审查修复批（2026-07-23，双子 agent 审查驱动，fix/m6-review）

| 发现 | 修复 |
|------|------|
| 🔴 R1 settings.toml 静默丢 2 条 code_roots（tinyrag/onecoupon）——根因：`_ensure_demo_code_root` 与 add/delete_code_root 路由拿**按当前工作区过滤**的 `config.code_roots` 当全量清单重写 `[[code_roots]]`（walkthrough 8b 建删 demo 根时触发，真实配置损失） | 恢复 4 根（onecoupon 路径改 TOML 字面字符串防反斜杠转义）；三处写路径改基于 `config.data` **全量未过滤**清单；config_writer 四函数共用进程内 RLock（E1 并发覆盖）；路由两处误用全局 `SETTINGS_PATH` 改 `_deps.config.path`（**该 bug 让修复批测试一度覆写真实配置**，已复原）；`update_code_roots` docstring 加全量清单警示 + 回归测试×2 |
| 🔴 B1 进程注册表并发读改写互踩（两请求同时 start → 后写覆盖先写 → 孤儿进程；atomic_write 固定 tmp 名交错 → 「启动失败」但进程已拉起） | `ProcessManager.list/start/stop` 公开入口全程持 `_REG_LOCK`（RLock 可重入，stop_all 嵌套安全）；并发 4 线程 start 回归测试（条目全保留） |
| 🟡 A1 scaffold_create 失败不可重入（注册代码根失败时 demo 目录已非空 → 同名永久被拒） | 先注册后复制 + 复制失败 rmtree 回滚；flaky 注册回归测试 |
| 🟡 Y3 单模型 setValue 跨文件 undo 污染（Ctrl+Z 回到上一文件内容再保存 = 数据损坏路径） | 每文件 `createModel` + `setModel` + 旧 model `dispose()`；走查 8b 补 undo 不跨文件断言 |
| 🟡 Y1/B1 legacy 降级：保存按钮可见但点了无效；create 半途抛错留悬空 editor | openLegacy 隐藏保存钮 + dispose 悬空实例 |
| 🟡 Y2 monacoReady 缓存 rejected Promise → 一次失败终身降级 | catch 中置 null，下次打开可重试 |
| 🟡 Y4 process_stop/logs 缺 generic 兜底（unhashable id 冒 500）；code_save 非字符串 root/path AttributeError | 统一 ok/error 契约 + str() 归一；回归测试 |
| 🟡 B2 logs_tail 全量读入内存（1GB 日志内存尖峰） | 尾部 seek 读最后 256KB；5000 行大日志回归测试 |
| 🟡 C1/E1 威胁模型未明示 + settings 写并发 | process_start 描述改「命令以当前用户权限执行，cwd 白名单非沙箱」；AGENTS.md 铁律 17 补威胁模型定案与 settings 锁/全量清单规约 |

🔵 留档（不阻塞，已记）：SSE 断连后生成器线程驻留（≤30min 保险丝，单用户有界）；stop 哈希校验与 terminate 间毫秒级 TOCTOU；进程自改 cmdline 误报 stopped；split_cmd 单引号路径不剥；update_code_roots 搬节丢注释（一致性）；code_save content 无大小限制；进程注册表/日志只增不减；模式初始化闪烁与竞态窗口；抽屉隐藏后轮询不止；demo 弹窗 auto-close 极端边界；走查 processes.json 停止条目累积；TOCTOU（resolve→write 窗口）；`_copy_scaffold` 全文本假设（二进制脚手架资源不支持）；`save_via_root rel="."` 错误信息含糊；scaffold_create 返回 abs_path。测试 +7 → **355 全绿**；走查 132 项全绿（+Y3 undo 断言）。

## M6 实战工坊（2026-07-23 交付）

- **正规工程脚手架**（`resources/scaffolds/{npm,maven-module,gradle}`）：标准布局 + 构建文件齐全 + **零外部依赖可离线构建**（npm 套 build=复制 src→dist、start=零依赖静态服务器、test=自断言——验收主路径；maven/gradle 仅模板）。`{{name}}` token 替换；npm test.js 内令牌字面量必须动态拼接（`"{{"+"name"+"}}"`）防替换误改逻辑（冒烟抓到的真 bug）
- **workshop_service**（`services/workshop_service.py`，不进 Deps）：写白名单 `{demo: Workspace.demo_dir, replica: WEB_ROOT.parent/<replica_name>（存在时）}`——**原项目永远只读**；`scaffold_create`（名称清洗/重名拒绝/复制+替换/自动注册 demo 代码根带 workspace 归属）；`write_alias`（AI edit_file 入口）与 `save_via_root`（UI 保存入口，代码根须与白名单根重合或位于其内部——反向祖先包含不允许，防写范围放大）；`editable()` 供 /api/code/file 标记
- **Workspace.demo_dir** 新字段：默认 `workspaces/<slug>/demo`（gitignored、删除守卫兼容、零硬编码可覆盖）
- **Monaco 0.52.2**（`frontend/vendor/monaco/`，12MB 95 文件，jsdelivr 字节数+node --check 双校验，版本登记 vendor/README.md）：**仅 pair 布局首次打开文件时动态加载**（loader.js → require editor.main，zh-cn nls）；**替换整个 viewer**（非白名单 readOnly），行高亮=deltaDecorations、片段选区=onDidChangeCursorSelection、换行=wordWrap、状态栏照旧；workers 经 data-URL 包装**按 moduleId 各指真实文件**（css/html/json/ts worker 全 vendor——初版未 vendor language/ 导致打开 html/js 时 AMD 404 loadError，走查"全程零 JS 错误"当场抓住）；加载失败静默降级旧 gutter+hljs 渲染；`window.__codeEditor` 暴露供走查 evaluate
- **edit_file 白名单落盘**：代码文件走 `atomic_write`（tmp+os.replace）——validate_study 是 docx 专用校验器无 validator 可挂，**有意偏离**规则 14 的 atomic_persist 形态（原子替换保崩溃安全）
- **process_mgr**（`services/process_mgr.py`）：psutil 驱动。注册表 `runtime/processes.json`（schema_version + atomic_write + 损坏留 .corrupt.bak）；启动 `CREATE_NEW_PROCESS_GROUP`（nt）/ `start_new_session`（posix）；**cmdline 哈希基准取启动时 psutil 规范化值**（python→C:\Python314\python.exe 差异会让输入 argv 永远对不上——首版 bug，改启动时抓取）；**PID 复用守卫**：list/stop 前哈希再校验，失配报 stopped 绝不动 kill；**真实杀树**（children(recursive=True)+self terminate→3s 宽限→kill 残余）；端口快探 2.5s（慢服务由 list() 每次实时探测兜底，不阻塞 start）；**stdout 直接重定向日志文件**（有意偏离设计"独立线程读 stdout"——抗服务重启、无管道断裂风险；SSE 仍只转 tail）；cwd 白名单=demo/replica/project_dir/当前工作区代码根（"启动原项目看效果"合法；写白名单不放宽）
- **study/code 模式双轴钉死**：`/api/session/mode` GET/POST（非法值拒）；`session.mode` 是会话级 agent 状态（服务端落盘），layout(tutor/pair) 是展示层配对；顶栏模式按钮 = POST mode + setLayout 默认配对（study→tutor/code→pair）；**code 模式布局覆盖**=代码面板可收起（面板头 » + 悬浮重开钮，localStorage 记忆——吸取"侧栏收不回"教训）；页面加载以服务端 mode 定初始布局；**`agent_mode_enabled` 默认改 true**（mode 默认 study，存量零影响——M5a 审查已证）
- **前端**：Monaco 保存（文件头按钮仅 editable 显示 + Ctrl+S + 脏标记 ●）/ demo 弹窗（类型+名称 → 创建成功自动刷新选中 demo 根，900ms 自关——走查初版点关闭撞 auto-close 不可见）/ 进程抽屉（cwd 白名单下拉 + cmd 启动 + 行内停止 + SSE 日志 tail + 端口链接新窗口看效果，进程行 textContent 构建防 XSS）
- **API**：/api/code/save、/api/code/file+editable、/api/demo/scaffold(s)、/api/processes(+allowed_cwds)/start/stop/logs/logs/stream(SSE)、/api/session/mode
- **新工具 5 个**：scaffold_create/edit_file（WRITE）+ process_start/process_stop/process_logs（SANDBOX）；ToolContext + workshop/process_mgr 字段；planner 工具清单自动收录（schemas 遍历零改动）
- **测试**：+28（test_workshop 12：白名单/脚手架/保存/editable/路由；test_process_mgr 9：真实杀树父子双亡+端口释放/PID 复用守卫/损坏恢复/SSE 流/路由起停；test_tool_registry +4：16 工具权限/工坊工具成败/planner 清单；test_turn_engine +3：mode 端点/非法拒/引擎路由）→ **348 全绿**；走查 131 项全绿（+8b code 模式段 23 项，Monaco 适配改造 + 存在性感知清理：进程/模式/demo 目录/demo 代码根 finally 还原）

## M5c planner（2026-07-23 交付）

- **ACTION 契约 + plan-act-observe**（`tool_use.py` 第三标记）：`[ACTION:{"action","args","reason"}]` 复用增量扫描管线——截获 → 契约校验（JSON dict + action str + args dict；不符注入错误教纠正，与非法 READ 标记同策略的无法解析按文本透传）→ `registry.invoke` 任意注册工具 → 注入结果（data 截断 2000）→ 续写。JSON 按**逐 ] 尝试解析**提取（容忍 args 内嵌 ]）；单回复上限 `[context].planner_max_actions_per_reply=4`（独立于 READ 3 次）；plan 决策记 agent.log（`observer.log_plan`，§10）
- **PlannerEngine 真身**（`engine/planner.py`）：instruction_for 注入 ACTION 契约 + registry marker schema 工具清单；post_process 空转（动作已在流内执行，阶段机不介入 agent 会话）。turn_engine 删 stub 改懒加载接线（防循环导入）；routes/test 改从 planner 导入。`agent_mode_enabled` 默认仍 false（仅 flag+测试可达，agent UI 入口属 M6）
- **SOP 策略化**：`resources/pedagogy/` 教学策略库（retell_guide 口述引导/retell_assess 四档 rubric/probe_followup 追问策略三卡）+ `render_pedagogy` 渲染器（PEDAGOGY_DIR），**面试指令与 quiz_generate/retell_assess 工具共用同卡**
- **🎤 模拟面试**（study 模式确定性状态机，§8.1 永不过 planner）：DayPhase.INTERVIEW + session.interview_cid/interview_round；`[模拟面试]` handler **代码确定性选题**（args 精确 > 当前单元 > 有证据最弱）；orchestrator 分支：round 0 四档评估（收评分进 pending_score）→ round 1/2 追问 → 终评 **teach_back 证据落盘**（≥及格 teach_back_pass +0.25 / fail −0.20，`interview:{cid}:{date}` 同日幂等）→ phase 还原；无评分标记不推进（铁律 6）；中断按 session 字段恢复
- **新 LLM 档工具**：quiz_generate（concept+证据摘要 → 渲染追问卡出题）/ retell_assess（rubric 卡评口述）；ToolContext + llm 字段（缺失 ok=False）
- **ScriptableLLM**（`tests/scriptable_llm.py`，§10 谓词脚本：match 正则 → respond 文本，记录 calls）
- **测试**：+31（test_planner 15：ACTION 截获执行注入/契约不符/未知工具/非法透传/嵌套 ]/plan 记账/[导学] 跑通/上限/LLM 工具×4；test_interview 16：选题×5/fail_fast/全流程 pass+fail/幂等/中断恢复/无评分不推进）→ 306 全绿；走查 108 项全绿（+模拟面试全流程——teach_back 写真实库，走查**先备份 session+learner_model 事后还原**防污染；胶囊 11→12）

## M5c 审查修复批（2026-07-23，双子 agent 审查驱动，fix/m5c-review）

| 发现 | 修复 |
|------|------|
| 🔴 生产 ToolContext 缺 llm 接线 → quiz_generate/retell_assess 线上恒失败 | routes 抽 `_build_tool_context(deps)`（含 llm=deps.llm）+ 回归测试 |
| 🔴 tutor 模式 ACTION 同样武装 → 写/沙箱工具攻击面前移（违反"同一 session 不混跑"） | ToolUseLoop `allow_actions` 开关（**默认 False 安全缺省**），routes 仅 planner 引擎会话开启；command 路径恒 False |
| 🔴 ACTION 调 read_code/read_doc 注入空结果（内容在 result.injection 而非 data） | `_do_action` 优先复用 result.injection |
| R3 ACTION 载荷 2000 cap 太小（write_note 长文/transcript 合法超限，且截获与否随 SSE 分块漂移） | ACTION 独立 `_ACTION_BUF_CAP=16384` |
| R4 final 排水丢 `_rest`：无法解析的 ACTION 吞掉后续文本 | final 循环 `_rest` 续排（断言"之后文字"不丢） |
| R3' 面试行为矩阵：ENDED/NOT_STARTED 可开面试（完成后 phase 被"复活"STUDYING）；day_review/end_day 不拦 INTERVIEW（不对称）；start_day/resume 覆盖 phase 不清面试字段 | interview.fail_fast 仅 STUDYING 放行（各态中文提示）；day_review/end_day fail_fast 拦 INTERVIEW；start_day/resume 清 interview 三字段 |
| R4' pending_score 复用冲突（quiz scored 待确认时被面试分覆盖/清空） | 独立字段 `session.interview_score`（quiz pending_score 零接触，测试锁 4.0 不被 2.5 覆盖） |
| R5 "落盘失败"文案混淆幂等命中与真失败 | 区分"今日已记录过（幂等跳过）"与"落盘失败" |
| R6 walkthrough 备份缺存在性（面试新建文件还原时残留）+ 无 try/finally | 存在性感知还原（新建则删）+ finally 保还原（含渠道还原） |
| R7 缺策略卡 fail-open 开空头面试（永远卡 round 0） | interview.run 缺卡 fail-closed（不改 phase，明示资源缺失） |
| R8 面试期 system 双指令矛盾（"最高优先级带读" + 面试 rubric） | prompt_builder 在 INTERVIEW 期跳过阶段指令块 |
| R6' data 截断无标注 / ACTION 只记 plan 不记 tool / JSON 失败分支死代码 | 截断加"…（已截断）"；补 log_tool（单流分析）；死分支注释"防御性" |

🔵 留档（不阻塞）：标记后尾随文本丢弃（与 READ 一致）、hold-back 致纯文本单 delta 的存量体验问题（另行立项）、PlannerEngine._deps 占位未用、log_plan/log_tool 双流已对齐。测试 +14 → **320 全绿**。

## M5b 上下文+路由（2026-07-23 交付）

- **context_manager**（`engine/context_manager.py`，AgentDesign §8.5）会话级三层：
  - **钉住层**：学习者模型摘要确定性渲染（top-K 薄弱按 mastery 升序 + 当前单元必含，分档 薄弱<0.4/爬升<0.7/达标），经 `prompt_builder.build(learner_summary=)` 可选参数注入（旧调用零变化）；任何异常静默 `""`
  - **窗口层**：est_tokens × 渠道校准比率（observer.ratio 公开化）按生效预算伸缩，条数硬兜底 `[context].max_messages=200`（**取代旧 chat_history_max_turns 用途**，旧键保留仅失效）
  - **归档层**：`SessionContext.archive_summary/archive_upto`；摘要独立 system 消息注入（降级点已注释）
- **压缩（回合边界）**：chat/command 流成功后 `maybe_compress`——结构化模板 `resources/prompts/context_compress.md` → **机械校验**（concept id 集合 ⊆ + 未决问题计数 = 旧声明 + 新增疑问数）→ 带原因重试一次 → 再不齐**原样保留降级不丢数据**（§8.4）；超 `archive_max_chars` 前部逐出（`…（更早内容已逐出）`）
- **预算钳制（用户反馈硬规）**：`effective_budget = max(1024, min([context].budget_tokens, [model_context] 模型上限 − 当前渠道 max_tokens 输出预留))`；上限表 deepseek-chat=65536/deepseek-v4-pro=256000/default=32768（标称值可自调）；**默认预算 256000**
- **UI 可调**：模型配置弹窗「上下文窗口」区（预算+触发比例输入、≈K 提示、模型上限与生效预算预览）；保存走 update_toml_sections 写 `[context]` 节区（**先读合并再整体重写防丢键**；节区行必须含 `[context]` 头——漏头会让键沉入顶层，已被测试当场抓住修复）+ reload 热生效
- **两档路由**：`[llm] cheap_provider`（空=复用 strong）；Deps + `llm_cheap`（构造点 6 处全改：app.build_deps + 5 处测试夹具）；压缩走 cheap，**cheap 异常 → strong 重试一次**（fallback 链）；v1 cheap 仅用于压缩（qa_capture/end_day 保持 strong）；task_scope("compress") 自动记账
- **清历史同步重置归档**：start_day 新开始 + /api/session/reset 两处（防 archive_upto 越界；assemble 另有防御钳 0）
- **测试**：+24（装配等价/收缩/钳制三分支/钉住渲染/机械校验/压缩降级/逐出/50+ 轮不断片/fallback/create_llm_cheap/session reset/llm-config context 保存合并热生效）→ 268 全绿；走查 105 项（+3 上下文窗口区）全绿

## M5b 审查修复批（2026-07-23，双子 agent 审查驱动，fix/m5b-review）

| 发现 | 修复 |
|------|------|
| 🔴 R1 expected_q 启发式 + 精确相等校验 → 常态校验失败或伪造未决问题（经旧摘要复利放大） | 校验放宽为**防增不防减**（声明 ≤ 上界即过，允许判定"已解决"，只防伪造）；prompt 契约同步改"宁少勿多" |
| R2 饱和期每回合都压缩（无滞回）+ 失败重试风暴 + 压缩阻塞 done | 窗口收缩改**低水位**（可用预算×0.5）；失败写 `session.compress_cooldown`（默认 3 回合，清历史两处同步重置）；压缩挪到 **done 事件之后**（断连则顺延下回合，数据无损） |
| R3 钉住层/归档层不计预算，小上下文模型可被打挂 | 装配时预扣 system+归档摘要 est（可用预算下限 512） |
| R4 零证据 concept（未学单元）淹没钉住层 top-K | 排序键零证据沉底 + 标「未学」不标「薄弱」 |
| R5 每条消息一次校准文件读盘（200 条≈400 次/回合） | 校准比率实例级缓存 + est 求和超上限早退 |
| UI 保存吞节区内注释（点"测试连接"即丢） | `update_toml_sections` 保留被替换节区的独立注释行（挪到新区块末尾） |
| 前端非法输入静默丢弃却显示成功 | 非法输入跳过该项并在状态行明示"该项未保存"；空 = 未改动 |
| 🔵 _Q_RE 不容错换行 / _ID_RE 幻象 id（Day2-3）/ int() 非法值 500 | 正则允许空白/id 段须含字母/_safe_int 落默认 |

证伪项（无需修）：LLM 失败路径 archive 污染（snapshot 在压缩前、失败分支先 return）、walkthrough 污染真实 settings（fill 后无保存动作、9c POST 不含 context 键）——已补路由级测试锁定失败纯净性。测试 +7 → **275 全绿**（冷却/滞回/预扣/零证据沉底/放宽校验/失败纯净/注释保留）。

## M5a 工具骨架（2026-07-23 交付，纯重构）

- **turn_engine**（`engine/turn_engine.py`，AgentDesign §8.2）：`TurnEngine` ABC（`instruction_for` + `post_process` 两方法）；ChatOrchestrator 加继承为第一实现（签名逻辑零变化，测试直接构造点全部不动）；`PlannerEngine` 占位 stub（M5c 填充）；`build_turn_engine(session, deps, tutor)` 按 `session.mode` × `agent_mode_enabled`（settings 新裸键，默认 false=零行为变化）二选一，同一 session 不混跑。SessionContext 加 `mode: str = "study"`（from_dict 过滤未知键天然兼容旧数据）。command 路由加 guard：agent 会话返回固定提示「该指令请在导学模式使用」（v1 不可达，骨架就位）
- **tool_registry**（`engine/tool_registry.py`，§8.3/§9/§12）：权限四级常量（readonly/write/sandbox_exec/llm）+ ToolSpec（name/permission/description/params JSON-schema/handler）+ ToolResult（ok/data/event/injection/error）+ ToolContext（config 必有，browser/materials/state_store/validator 按需，缺依赖 ok=False 不抛异常）。`schemas(transport)` 对 marker/native 两种传输暴露同一份 schema（native 接线 LLM 属 M5c）
- **9 个现有能力工具化**：read_code/read_doc（tool_use 的 _do_read/_do_read_doc **逐字迁入**，event/injection 文本零变化）/ search_notes / read_model / run_build（镜像 verify_code 解析，不含点评与 evidence）/ write_note / resolve_note（走 M4 单一路径 note_actions）/ update_model（etype 限定 [evidence_delta] 表内，铁律 15）/ persist_state（**白名单操作集** v1 仅 set_unit_status，status 限 status_enum，规则 14 落盘——planner 未来只能经此间接写 StudyState）
- **ToolUseLoop 改注册表分发**：构造加可选 `registry`/`tool_context`（缺省内部自建，签名向后兼容）；READ/READ_DOC 标记截获后 `registry.invoke` 取 (event,injection)；observer.log_tool 留在 Loop。chat 路径 LLMStreamer 建完整 ToolContext（含 state_store/validator）
- **测试**：+24（test_turn_engine 7：接口实例/三路路由/stub 可调用/mode 兼容；test_tool_registry 17：9 工具权限/双传输 schema 一致/read_code 成败/update_model 拒绝+幂等/persist_state 白名单/write_note 边界/缺依赖不抛异常）→ 235 全绿；走查 102 项全绿（服务重启为新代码后跑）

## M5a 审查修复批（2026-07-23，双子 agent 审查驱动，fix/m5a-review）

审查结论：无 🔴；逐字对比通过；flag off 零行为变化成立。修复全部 🟡：

| 发现 | 修复 |
|------|------|
| update_model 写路径 day 静默兜底 Day 1（证据错归因无告警） | 改 fail-closed：天数不可解析 → ok=False 拒绝写入（read_model 只读回退保留） |
| command guard 分支零测试 | routes 级用例：flag on + mode=code 会话发指令 → 固定提示 + handler 未执行（阶段/历史不变） |
| invoke 异常吞噬分支零测试 | handler 抛异常 → ok=False「执行异常」契约用例 |
| _run_build 整体零测试 | 5 用例：缺 state_store/无构建文件/多候选/参数传递（mock run_build 断言 kind/timeout/offline）/target 选择 + 退出码非 0 → ok=False |
| 路由缺第四象限 (study, flag on) | 补用例：flag 打开后旧 study 会话仍走 tutor（不混跑关键保证） |
| SimpleNamespace 假 deps 脆弱 | test_turn_engine 全部换 make_deps 真实 deps |

测试 +9 → **244 全绿**。🔵 可选项（防御分支 error 事件/write_note dedup 语义/persist_state 缺 validator fail-open/limit 下界/code·agent 命名）留待 M5c 接线时定夺。

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
| 掌握度面板 v2 排版全乱（说明条/统计卡挤成竖条） | `.page-body { display: flex }` 默认 **row** 方向，`.mastery-layout` 三个子块被横排挤压 | v11 直接改抽屉布局规避整类问题；教训：**复用父级 flex 容器时必须显式声明 flex-direction** |
| 抽屉 tab 文字被压成 30px 竖排圆点（战术板/战略雷达不可读） | `.drawer-head button` 关闭按钮样式（30px 圆形）**命中了抽屉内所有 button**（含 tab）——与 cfg-test 委托同型的"样式选择器误伤" | 改 `.drawer-head > button` 只命中直接子代关闭钮；教训：**容器内样式一律用子选择器或专用类，禁止裸后代选择器** |
| 雷达 tab 切换后战术板仍可见、「其余知识点」默认折叠失效 | 项目**没有全局 `.hidden` 规则**（各组件各自 scoped），新元素 `#mastery-tactical/#mastery-radar/#ms-rest-body/#urgent-widget` 的 hidden 类无效果 | 加全局 `.hidden { display: none !important; }`（与所有现有 scoped 定义同语义，无冲突） |

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

- **v13（2026-07-23）**：掌握度行动化收官（Gemini 二轮评审）——战术板：算法说明收纳 ℹ️ 弹层、三统计卡改双行动计数（紧急薄弱/待复习）、△ 改 `≤0.6` 胶囊、状态标记挪行首/百分比守行尾、底部 3px 细进度线、详情去重复标题、**行动按钮**（👉 丢给 AI 重新讲=回填聊天框关抽屉 / 📖 查看关联资料=直达预览）、证据明细默认折叠「查看评估明细 ▾」。雷达：**SVG Donut**（圆心总数+平均掌握度，零依赖）替代四横条、热力图格子自适应撑满、**垂直时间轴**替代 mermaid 香肠图（全标题可读、状态色点连线、点击节点跳战术板展开详情、当前天自动定位）、**左右 1:2 不对称双列**。
- **v12（2026-07-23）**：掌握度改「战术板 + 战略雷达」——战术板**状态驱动分桶**（🚨 需要行动：全历史到期+薄弱混排置顶 / 📍 今日学习 / ✅ 其余知识点默认折叠，行带 Day 标签），告别按天流水账（Gemini 评审建议）；战略雷达 tab：掌握度四档分布条 + GitHub 式**学习活动热力图**（近 12 周证据产出）+ **知识点先修拓扑图**（mermaid，按档位着色）；主侧栏新增**复习预警 widget**（跨周期紧急项伴随式暴露，点击直达抽屉展开详情）。修复两个选择器 bug（见 bug 史）。
- **v11（2026-07-23）**：掌握度面板抽屉化 + 全局图标/按钮打磨 —— 修 `.page-body` flex 默认 row 导致的面板挤扁 bug；掌握度从全屏页改为**右侧滑出抽屉**（聊天区保持可见，可对照学习），详情改为**行内手风琴展开**（同时只展开一条）；统计卡加阴影浮起；标题/百分比字重分层；顶栏与两页图标从 Emoji 换为**内联 SVG 线条图标**（Lucide 风格，零依赖）；指令胶囊增强按钮感（圆角/阴影/hover 浮起）。双主题下抽屉均正常（pair 深色即用户要的暗色体验）。
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


## 审计留档（2026-07-23 架构审计 🔵 归集，不阻塞）

- **设计侧**：§10 ReplayLLM 未建（ScriptableLLM/MockLLM 已覆盖现状）；§8.6 quirk 层仅两类（空 choices/stream_options，reasoning 字段/温度降级遇厂商怪癖再补）；服务互引例外未全登记（config_service/config_writer/memory_store/study_plan 方向均向下无环）；index.html 静态标题运行时覆盖；B5 llm-config 已修（见上表）；阶段字面量散落 engine（InteractionModel 已钉为契约）；DayPhase.PLANNING 死枚举；unit_open 模板头恒「单元 1」；token_calibration.json 无 schema_version；review_due 恒单元素 vs §3.1 示例形状。
- **engine/api 侧**：quiz_engine.ask_and_score 死代码；stage_machine.advance/next_of 无消费者（source_review/paper 阶段配置可达性属预设编排缺口）；SessionContext.force_skip 只写不读；start_day 不清 pending_score/review_msg_start（惰性无害）；tool_use 多标记续写重复注入（token 浪费）；command LLM 失败 docx/session 分叉（[恢复学习] 自愈）；/api/config/reload 不重建 StageMachine/QuizEngine 快照（改这两类配置需重启）；/api/auth/logout 未豁免（过期会话无法登出，清 cookie 可绕）。
- **services/前端侧**：mastery 半衰期 0/损坏 evidence 数值边界；StudyState 非数字 day 键；.bak 同名冲突（现调用方文件名均不同）；.tmp 残留进导出 zip；split_cmd 单引号路径；token 与密码解耦（改密不踢旧 token）；进程运行中 chdir 致哈希失配误报 stopped（fail-safe 代价）；learner/notes JSON 读改写短锁外（session 已治，余者串行场景）；fallback 半流缝合（前端 rawText 直拼，设计内有意识）；update_env_file docstring「空值跳过」与实现不符（clear_password 依赖写空）；InterviewQA 坏块重渲染后移尾部（round-trip 二次稳定已锁定）。
