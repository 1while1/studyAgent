# studyAgent（study-web）—— 通用 AI 学习助手

把 prompt-as-code 学习辅助系统做成通用的 Web 应用：**规则执行由代码强制，内容生成由 LLM 负责**。多工作区设计——任意代码项目都能一键初始化为自己的面试导向学习助手。

- 确定性（代码）：模板渲染、FAIL-FAST、阶段流转、状态枚举、回合计数、评分标记提取、备份→落盘→validate→回滚、阈值检查
- 内容（LLM）：讲解、连环追问、点评、复盘拷打、StudyReview 正文、初始化文档生成

设计基准见 `docs/InteractionModel.md`，开发规范见 `AGENTS.md`，**演进蓝图（v3 封板）见 `docs/AgentDesign.md`**。

## 快速开始

```bash
cd study-web
pip install -r requirements.txt
cp .env.example .env        # 填入 LLM_API_KEY 等（也可启动后在「模型配置」页面填）
python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

不配 key 也能跑：`config/settings.toml` 把 `provider` 改为 `"mock"` 即进入离线假模型模式。

## 多工作区（任意项目一键初始化）

顶栏「工作区下拉 → ＋ 新建工作区」：

1. 填目标项目目录、名称、学习目标、总天数（复现项目名可选）
2. 「扫描预览」确认项目画像（目录树 + 构建文件 + README）
3. 「开始初始化」：LLM 自动生成 `Project.md`（架构文档）与 `Study.md`（N 天学习计划），**程序验证管线**逐天解析校验，失败带错重试；其余文档（StudyState/ReplicaPlan/DocIndex/InterviewQA）用骨架模板
4. 自动注册并切换到新工作区，即可开始 `[开始今日学习]`

- 每个工作区独立：学习数据（`workspaces/<slug>/docx/`）、聊天会话、代码根
- 切换即热重载（deps 重建 + 页面刷新）；「↻ 重新扫描项目结构」手动刷新 Project.md
- 菜单每项带 ⬇ 导出学习数据 zip / ✕ 删除工作区（默认保留磁盘数据，激活中的工作区不可删）
- 新建时可选「学习模式预设」（标准 / 阅读实验 / 改 bug / 技术文章，对应 `resources/presets/*.toml`）
- 行为资源单源：`resources/sop/`（SOP 卡）、`resources/templates/`（初始化骨架）、`resources/prompts/`（生成提示词）——改行为改文件，不改代码

## 功能一览

**学习流程**（与 SOP 体系完全一致）
- 11 个触发指令：输入框上方胶囊条点击 / 输入 `[` 唤起补全菜单 / 直接输入
- 五步导学循环状态机（文档带读 → Replica 编码 → 源码对照 → 论文带读 → 掌握度考核），可按工作区选学习模式预设（阅读实验/改 bug/技术文章）
- 掌握度 2 回合连环追问 → `【评分：X.X】` 自动提取落盘；不及格拒绝推进
- FAIL-FAST 双选项、「重新开始」保留 [同步] 记录、天数自动递进
- 增量式学习计划：初始化生成全量粗纲 + 前 3 天细化，每天结束时 AI 结合当日反馈自动细化次日
- 间隔复习：按 1/3/7 天间隔自动把历史卡壳/待解答疑问/低分单元插入当日开头快速回顾
- **`[验证代码]`**：一键在 replica/项目目录跑 Maven/Gradle/npm 编译或测试，AI 基于真实输出点评
- 所有进度实时写入当前工作区并过 `validate_study.py` 校验

**双模式 UI（M6 双轴钉死）**
- **知识学习**（study/tutor）：暖纸书房风（米白 + 赭石 + 衬线标题），侧栏纯学习仪表盘
- **源码学习**（code/pair）：IDE 深色风（左目录树 + 中 Monaco 编辑器 + 右 AI 工具窗口），标签页文件头 + 底部状态栏（路径·语言·行数·UTF-8·可编辑/只读）
- 顶栏分段控件切换的是 **agent 模式**（`session.mode` 服务端落盘）：code → planner 引擎 + 写/沙箱工具武装，study → 导学引擎；布局（tutor/pair）只是展示层配对，code 模式下代码面板可收起（悬浮钮随时重开）
- 旧导学指令在 code 会话返回固定提示「该指令请在导学模式使用」（确定性不过 planner）

**页面体验**
- AI 回复 Markdown 渲染（标题/加粗/表格/引用），代码块语法高亮 + 一键复制
- SSE 流式输出 + "思考中… Ns" 等待指示（长提示词首包约 20s 属正常）
- 多行输入框（Enter 发送 / Shift+Enter 换行 / 自动增高）、回到底部按钮、聊天历史刷新回填
- 学习资料弹窗：当日 StudyMemory / 面试话术库 / **资料库** 在线查看（阅读版式）

**资料库（M1）**
- 工作区配置 `materials_dir` 后自动扫描注册（txt/md/docx/pdf），注册表 + 解析缓存落工作区数据目录
- docx 按标题样式切段（python-docx，损坏关系包自动回退裸 XML 解析）、pdf 按页切段（pypdf），统一文本清理（移植 ragent TextCleanupUtil 规则）
- **备课确定性预取**：讲解回合开始前，后端自动按当前单元的「文档」引用把教材真实节选注入 LLM 上下文（transient，不进聊天历史），前端显示 📚 备课 chip——讲解有根据，不靠 LLM 自觉
- **AI 读教材 tool-use**：导师可输出 `[READ_DOC:资料id#章节]` 主动读取教材（与 READ 同一管线同一限流），省略章节先返回章节目录自导航，前端显示 📄 chip
- 资料库弹窗：清单（类型/章节数/状态）+ 预览（目录+开头节选）+ 重新扫描 + 手工注册外部文件/视频链接
- 敏感文件（.env/证书类）不注册不解析

**可观测性（M2）**
- `runtime/agent.log`（JSONL）：每次 LLM 调用记录渠道/模型/任务/耗时/token/成败与失败原因，READ/READ_DOC/备课预取记 tool 记录——任何"没反应"可定位
- **token 三层统计**：API usage 精确 → tiktoken cl100k 通用估算 → CJK×1.5 公式兜底；usage 到达自动滑动校准估算比率
- 顶栏状态条：当前渠道 + 最近调用耗时（失败标红，悬停看错误原因）
- 「📊 用量」页：近 7 天 渠道×任务×日 的调用量/token/估算成本（定价表可在 settings 配）
- **访问密码门**：「📊 用量」页设置密码后全 API 锁定（bcrypt 哈希存 .env，签名 cookie 7 天，失败限速）；未设置 = 开放模式

**学习者模型（M3）**
- 每个学习单元自动铸造知识点（concept）：`concepts.json` 注册表 + 确定性先修链（天内 A→B→C、跨天衔接）
- **evidence 三路写入**：单元考核评分 / [同步] 已掌握·卡壳 / [验证代码] 构建结果，全部落为带权证据（delta 表在 settings，LLM 只选类型）
- **mastery 证据驱动**：衰减公式（14 天半衰期）实时计算，不再只靠 LLM 自评；**无构建验证通过记录封顶 0.6**（防"看懂"幻觉）
- **🧠 掌握度面板**：全屏三栏——统计卡（平均掌握度/薄弱数/待复习数）+ 按 Day 分组的进度条列表 + 详情页（建议行动卡、证据构成表·行为中文名·Δ 正负着色、衰减说明）；证据透明可解释，不再只是"一个分数"
- 旧数据一键迁移：历史单元评分 → quiz_score 证据（rating/5 映射），卡壳/疑问 → 开放笔记条目（草稿预览→人审确认→应用）

**笔记管理（M4）**
- **四层笔记体系**：日志层（StudyMemory append-only）→ 条目层（notes.json）→ 话术层（InterviewQA.md）→ 蒸馏层（掌握度证据）
- **条目自动进层**：[同步] 已掌握/卡壳/疑问除写日志外同步产生笔记条目（内容哈希幂等，自动挂接当前单元知识点）
- **📝 笔记页（书架三栏）**：全屏页面——左栏书架（全部/待解决/已解决/⚠待整理 + 按知识点成"书" + 类型 chips + 全文搜索），中栏笔记卡片，右栏 **Markdown 编辑器**（H1-H3/加粗/斜体/删除线/代码块/引用/列表/任务/链接/表格/分隔线/Mermaid 图工具条 + 编辑/分屏/预览三态，预览与聊天同一渲染管线含 mermaid SVG）
- **卡壳销账**：「标记解决」单一代码路径——条目 resolved + 沉淀 note_distilled 证据（+0.05，source_ref 幂等，重复销账不重复加）；迁移/蒸馏条目先「挂接知识点」再销账
- **话术库收编**：面试话术库升级为卡片视图（30 秒直显 / 2 分钟与追问预案折叠，就地编辑/删除，可切回原文视图）
- **🎙 拷打反喂**：每日复盘评分落盘后，自动从拷问转录提炼 ≤2 条最有面试价值的话术写入 InterviewQA.md（LLM 只填内容，格式机械校验 + 产出来源行服务端强制覆写；`qa_capture_enabled` 可关）

**代码浏览器与联动提问**
- 目录树懒加载 + 行号 gutter + 语法高亮（只读，路径穿越防护）；树折叠、长行换行、树宽拖拽记忆
- **片段提问**：选中代码 → 浮动按钮 → 自动填入「`路径:L行号` + 代码块」到输入框；聊天中渲染为片段卡片，点 📎 跳回代码浏览器定位 + 行高亮
- **代码引用芯片**：AI 回答中的反引号路径（如 `` `项目/路径/File.java:L4-L11` ``）自动变可点击芯片，点击跳转打开 + 行高亮；路径写错时按文件名回退定位，找不到明确提示
- **AI 读文件 tool-use**：导师讲解中可输出 `[READ:路径:L起-止]` 主动读取真实代码（后端截获注入后续写，单回复限 3 次），前端显示 📖 chip 可点击跳转定位——讲解基于真实代码，杜绝虚构
- **Mermaid 图**：AI 回答中的 ```mermaid 代码块渲染为架构图/时序图，主题随模式（源码学习=深色）

**上下文三层控制（M5b）**
- **钉住层**：system prompt + 学习者模型摘要（确定性渲染 top-K 薄弱 + 当前单元，永不压缩）
- **窗口层**：按 token 预算伸缩（est × 渠道校准比率），条数硬兜底 200
- **归档层**：超长历史在回合边界由 cheap 档 LLM 压缩成结构化摘要（概念 id/未决问题机械校验，失败重试一次再不齐原样保留不丢数据）；摘要独立 system 消息注入，上限 4000 字符前部逐出
- **预算用户可调**：模型配置页「上下文窗口」区（默认 256K），**生效预算 = min(用户预算, 模型上限 − 输出预留)**；模型上限表 `[model_context]` 驱动不同模型差异
- **cheap/strong 两档路由**：压缩走 cheap 档（`[llm] cheap_provider` 可配，空 = 复用 strong），cheap 失败自动 strong 重试一次

**planner 与模拟面试（M5c）**
- **🎤 模拟面试**：`[模拟面试]`（可带知识点）确定性选题（指定 > 当前单元 > 最弱有证据）→ 口述 → 四档评估（结构/准确/源码定位/追问应对）→ 两轮追问 → 终评 **teach_back 证据落盘**（pass +0.25 / fail −0.20，同日幂等）；中断可续
- **planner（agent 引擎）**：`[ACTION:{"action","args","reason"}]` 标记——流式回合内 plan-act-observe 循环（截获 → 工具执行 → 注入结果 → 续写），单回复限 4 次；契约不符/未知工具注入错误教纠正；plan 决策记 agent.log
- **教学策略库**：`resources/pedagogy/` 策略卡（口述引导/四档评估/追问策略），面试指令与 quiz_generate/retell_assess 工具共用同源
- 新 LLM 档工具：quiz_generate（基于知识点+薄弱证据出题）/ retell_assess（四档评估口述）

**实战工坊（M6）**
- **正规工程脚手架**：`resources/scaffolds/{npm,maven-module,gradle}`（标准布局 + 构建文件齐全 + **零外部依赖可离线构建**）；「+ 新建 demo」弹窗或 AI `scaffold_create` 工具一键生成到 demo 根，自动注册代码根
- **平台内编码（Monaco 0.52.2，vendor 本地）**：源码学习布局内查看/编辑一体——原项目只读，`demo/`、`replica/` 白名单内可编辑（保存按钮 + Ctrl+S，atomic_write 落盘、脏标记、敏感文件拒写）；Monaco 加载失败静默降级旧 gutter 渲染
- **写白名单铁律**：仅 `demo/`、`replica/` 别名可写；原项目（project_dir / 代码根）永远只读；AI `edit_file` 工具与 UI 保存共用同一份白名单校验
- **进程管理**：进程面板启动/停止/日志（SSE tail）/端口链接——`python -m http.server`、demo `npm start` 均可；**真实杀树**（psutil children+self terminate→kill 残余）、**cmdline 哈希 PID 复用守卫**（失配报 stopped 绝不误杀）、端口快探 + 列表实时兜底；启动 cwd 白名单（demo/replica/项目目录/代码根，支持"启动原项目看效果"）
- **新工具 5 个**：scaffold_create / edit_file（写·白名单）+ process_start / process_stop / process_logs（沙箱执行），planner 清单自动收录

**模型管理**
- 「模型配置」页面：主/备渠道切换、模型 ID、Base URL、API Key（掩码显示）、测试连接、保存热生效
- 主备自动 fallback：主渠道失败自动切备用（中途断流会标注重新生成）
- 启动预热：后台线程预热上下文缓存，降低首包延迟（`warmup_on_start` 开关）
- 清空对话历史：一键清除上下文污染（学习数据不受影响）

## 运行测试

```bash
cd study-web
python -m unittest discover -s tests    # 348 个后端测试，stdlib，无需真实 LLM
python scripts/ui_walkthrough.py        # UI 真实点击走查 108 项（需服务运行中）
python resources/hooks/validate_study.py <docx_dir> [total_days] [replica_name]
```

`test_flows.py` 在 docx 临时副本上跑完整一天流程（开始 → 下一内容 2 回合 → 同步 → 结束），每步落盘后运行 `validate_study.py` 断言全绿；`test_workspace.py` 覆盖工作区配置/扫描/初始化全流程（MockLLM）。

## 配置

| 改什么 | 在哪里 |
|--------|--------|
| 模型/渠道/密钥 | 页面「模型配置」（推荐）或 `config/settings.toml` + `.env` |
| 工作区（新增/切换/参数） | 页面顶栏下拉（推荐）或 `settings.toml` 的 `[[workspaces]]` |
| 阈值（20 行代码限制/及格分/题量/回合间隔/状态枚举） | `config/settings.toml` |
| 单元阶段机与各阶段给 LLM 的指令 | `config/settings.toml` 的 `[[stages]]` |
| 新增触发指令 | `settings.toml` 的 `[commands.*]`（简单指令 `handler = "declarative"` 零代码） |
| 模板措辞 | 直接改 `resources/sop/*.md` 卡内 `<!-- template:* -->` 锚点块（模板唯一事实源） |
| 初始化生成风格 | 改 `resources/prompts/init_*.md`，零代码 |

运行时改完配置后自动按 mtime 热重载；模型配置页面保存即热生效。

## 架构

```
api/        FastAPI 路由 + SSE（chat/command/state/workspaces/code/llm-config 等）
engine/     stage_machine（配置驱动）/ orchestrator（聊天阶段驱动）/ quiz_engine（评分提取）
            / turn_engine（双引擎接口 + mode/flag 路由）/ planner（ACTION 契约 + plan-act-observe）
            / tool_registry（工具注册表+权限四级）
            / context_manager（上下文三层 + 预算钳制 + 压缩机械校验）
            / commands（每 SOP 卡一个 handler，互不 import）/ hooks（注册式钩子链）
services/   state_store / memory_store / study_plan / template_service（SOP 锚点解析）
            / backup_service（规则 14 落盘编排）/ config_service / config_writer
            / code_browser（代码浏览+路径解析）/ repo_scanner（项目画像）
            / doc_initializer（初始化生成+验证管线）/ workspace_service（工作区编排）
            / workshop_service（M6 实战工坊：写白名单+脚手架）/ process_mgr（M6 进程管理）
domain/     纯模型零 IO（SessionContext / Workspace / paths 常量）
llm/        LLMClient 接口 + openai_compat / mock / fallback + factory 注册表
resources/  sop/（模板锚点）/ hooks/（校验脚本）/ templates/（初始化骨架）/ prompts/（生成提示词）
            / scaffolds/（M6 工程脚手架 npm/maven-module/gradle）
```
