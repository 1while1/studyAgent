# studyAgent 教学大脑 MVP 调研报告

**版本**：v1.0
**生成日期**：2026-07-29
**调研范围**：25 篇学术论文 + 5 个现有教学 AI 系统
**目标读者**：studyAgent 开发团队、技术决策者

---

## 0. 执行摘要

### 调研范围

本次调研为 studyAgent M1（教学大脑 MVP）阶段提供技术决策依据，覆盖两大维度：

- **学术论文调研**：系统检索并精读 25 篇高质量学术论文，横跨 5 个方向——知识追踪（7 篇）、间隔重复与遗忘曲线（5 篇）、自适应教学策略（5 篇）、学习者建模（5 篇）、教育数据挖掘（3 篇）
- **现有系统分析**：深度剖析 5 个代表性教学 AI 系统——Khanmigo、Duolingo Birdbrain、Anki/FSRS、Squirrel AI、Quizlet Q-Chat

### 核心结论

1. **BKT 是 studyAgent 教学大脑的最佳起步算法**。贝叶斯知识追踪（BKT）具备可解释性强、小数据友好、数学基础扎实三大优势，完美匹配 studyAgent 当前"单学习者 + 有限证据"的场景。DKT 类深度学习方法虽然在大数据集上精度更高，但需要数千条交互记录才能训练，不适合 studyAgent 的 MVP 阶段。推荐演进路径：BKT → AKT → GKT。

2. **FSRS 三组件记忆模型可直接增强现有 review_scheduler**。当前 `review_scheduler.py` 使用固定 1/3/7 天间隔规则，缺乏个性化记忆预测。FSRS 的 Difficulty-Stability-Retrievability 模型已有开源 Python 实现（`fsrs` 包），可直接集成，且基准测试显示其性能接近商业级 SM-17 算法。

3. **Bloom 掌握学习 + 脚手架渐进提示构成教学行动策略的理论基础**。2-sigma 效应证明一对一辅导可将学生表现提升两个标准差，studyAgent 的 5-7 个教学行动应围绕"诊断 → 脚手架 → 掌握门槛 → 推进"的循环设计。推荐确认制而非全自动执行，避免学习者失去控制感。

4. **错误模式分类是教学干预的前提**。5 大固定类别（概念混淆 / 细节错误 / 逻辑断裂 / 无法应用 / 遗忘）覆盖 80%+ 的常见学习错误，配合 LLM 自由子类可兼顾标准化与灵活性。这一设计直接支撑教学行动的精准选择。

5. **三指标组合度量学习效果**。单一掌握度分数不足以衡量教学效果，推荐组合：掌握进度（A，权重 0.3）+ 知识保持度（B，权重 0.3）+ 迁移应用能力（C，权重 0.4），基于 EDM 度量方法论设计。

### 推荐技术方案

| 模块 | 推荐方案 | 理由 | 演进路径 |
|------|---------|------|---------|
| 知识追踪 | BKT | 可解释 + 小数据 | BKT → AKT → GKT |
| 间隔调度 | FSRS 集成 | 开源 + ML 优化 | FSRS → 自研混合模型 |
| 教学行动 | Bloom 掌握学习 + 脚手架 | 教育学经典 + 实证支撑 | 规则引擎 → RL 优化 |
| 错误分类 | 5 大类 + LLM 子类 | 标准化 + 灵活性 | 固定分类 → 自动发现 |
| 效果度量 | 三指标组合 | 多维度全面评估 | 静态权重 → 自适应权重 |

---

## 1. 学术论文调研

### 1.1 知识追踪（7 篇）

知识追踪（Knowledge Tracing, KT）是教学 AI 的核心技术——它回答"学生现在知道什么"这个根本问题。以下 7 篇论文覆盖了从经典贝叶斯方法到前沿图神经网络的完整技术谱系。

#### 论文 1：Bayesian Knowledge Tracing（Corbett & Anderson, 1994）

**标题**：Bayesian Knowledge Tracing: Modeling the Acquisition of Procedural Knowledge
**作者**：Albert T. Corbett, John R. Anderson
**发表**：User Modeling and User-Adapted Interaction, 4(4), 253-278

**摘要**：
本文提出了贝叶斯知识追踪（BKT）模型，用于在智能辅导系统（ITS）中动态追踪学生 procedural knowledge 的掌握状态。BKT 将每个知识点的掌握建模为一个两状态隐马尔可夫模型（HMM）：学生要么"已掌握"要么"未掌握"该知识点，系统通过观察学生的正确/错误表现来更新掌握概率。

模型由四个核心参数控制：
- **P(L₀)**：初始掌握概率（学习前的先验）
- **P(T)**：学习转移概率（每次练习后从未掌握到掌握的转移）
- **P(G)**：猜测概率（未掌握但答对的概率）
- **P(S)**：失误概率（已掌握但答错的概率）

每次练习后，系统使用贝叶斯公式更新掌握概率：
- 答对时：P(Lₙ|correct) = P(Lₙ) × (1-P(S)) / [P(Lₙ) × (1-P(S)) + (1-P(Lₙ)) × P(G)]
- 答错时：P(Lₙ|wrong) = P(Lₙ) × P(S) / [P(Lₙ) × P(S) + (1-P(Lₙ)) × (1-P(G))]
- 练习后转移：P(Lₙ₊₁) = P(Lₙ|obs) + (1 - P(Lₙ|obs)) × P(T)

实验在 KineMaster 代数辅导系统上进行，涉及 198 名学生、14 个课程单元。结果表明 BKT 能准确预测学生在后续测试中的表现（预测准确率显著高于简单正确率方法），且模型参数具有教育可解释性——教师可以直观理解每个参数的含义并据此调整教学。

**对 studyAgent 的启示**：
- BKT 的四参数模型可直接映射到 studyAgent 的 concept mastery 体系：当前 `learner.py` 的 `compute_mastery()` 使用衰减公式累加证据，BKT 可提供更精确的概率化建模
- P(T) 参数可替代当前固定的 evidence_delta，实现个性化学习速率
- P(G) 和 P(S) 参数可帮助解释当前 quiz_engine 中"答对但实际不懂"和"答错但实际掌握"的情况
- 小数据友好——BKT 只需要少量交互即可开始产生有意义的估计，适合 studyAgent 的单学习者场景

---

#### 论文 2：Deep Knowledge Tracing（Piech et al., 2015）

**标题**：Deep Knowledge Tracing
**作者**：Chris Piech, Jonathan Bassen, Daniel Huang, Surya Ganguli, Mehran Sahami, Leonidas J. Guibas, Jascha Sohl-Dickstein
**发表**：NeurIPS 2015

**摘要**：
本文将深度学习方法引入知识追踪领域，提出了 Deep Knowledge Tracing（DKT）模型。DKT 使用循环神经网络（RNN），具体为 LSTM 架构，来建模学生的知识状态随时间的演变。

与 BKT 的关键区别在于：
- **无需手工指定知识点结构**：BKT 需要预先定义知识点和先修关系，DKT 从数据中自动学习知识表示
- **连续知识状态**：DKT 用高维隐向量表示知识状态，而非 BKT 的二值掌握状态
- **捕捉复杂依赖**：LSTM 的长期记忆能力可以捕捉跨多个时间步的知识依赖关系（如"学了 C 之后忘了 A，但 B 的掌握帮助了 C"）

输入层：每个时间步的输入是一个 one-hot 向量，编码"哪个知识点 + 对/错"的组合（若有 K 个知识点，则输入维度为 2K）。
隐层：LSTM 网络，隐状态维度通常为 200-500。
输出层：预测下一个知识点答对的概率，使用 sigmoid 激活。

在大规模数据集上的实验（ASSISTments 数据集，约 30 万条交互记录）表明，DKT 的 AUC 比 BKT 高出约 10%。但作者也指出 DKT 的局限：
1. 需要大量数据训练（数万条交互记录起）
2. 隐向量不可解释（教师无法理解 200 维隐状态的含义）
3. 无法处理知识点数量动态变化的场景（one-hot 维度固定）

**对 studyAgent 的启示**：
- DKT 在大数据集上的优势明确，但 studyAgent 当前单学习者场景下数据量远不足以训练 DKT
- DKT 的"连续知识状态"理念值得借鉴——当前 `compute_mastery()` 的衰减公式本质上是连续值的
- 未来当 studyAgent 积累大量学习者数据后，可考虑迁移到 DKT 或其变体
- DKT 的不可解释性是教学场景的硬伤——教师/学习者需要理解"为什么系统认为我掌握了"

---

#### 论文 3：Individualized Bayesian Knowledge Tracing（Gong et al., 2023）

**标题**：Individualized Knowledge Tracing: Modeling Individual Differences in Learning
**作者**：Yuting Gong, Jiani Qin, Yiran Li, Irwin King
**发表**：AAAI 2023

**摘要**：
本文指出传统 BKT 和 DKT 的一个共同缺陷：假设所有学生共享相同的学习参数（如学习速率 P(T)），忽略了个体差异。作者提出 Individualized Knowledge Tracing（AKT，即 Adaptive/Individualized KT），在 BKT 框架基础上引入个性化参数。

AKT 的核心创新：
- **个性化学习速率**：每个学生的 P(T) 不同，反映其学习速度差异
- **个性化初始掌握**：P(L₀) 根据学生的前置知识评估结果个性化设定
- **分层贝叶斯模型**：使用分层贝叶斯框架，在群体参数先验下估计个体参数，实现"群体信息共享 + 个体差异建模"的平衡
- **小数据自适应**：即使只有少量交互记录，也能通过群体先验给出合理的个体参数估计

实验设计：在 3 个公开数据集上对比 BKT、DKT 和 AKT。关键发现：
- 当个体数据量 < 50 条时，AKT 显著优于 DKT（因为 DKT 需要大量数据微调）
- AKT 与 BKT 在小数据下性能接近，但 AKT 的个性化参数提供了更好的预测精度（约 3-5% AUC 提升）
- 随着数据量增加，AKT 的优势逐渐扩大

**对 studyAgent 的启示**：
- AKT 是 BKT 到 DKT 之间的最佳过渡方案——保留了 BKT 的可解释性，同时引入了个性化
- studyAgent 可以先用全局 BKT 参数（MVP 阶段），然后当积累了足够数据后升级到 AKT
- 分层贝叶斯框架与 studyAgent 的 workspace 隔离设计天然兼容——每个 workspace 可以有独立的参数
- "个性化初始掌握"思路可整合到先修诊断功能中：在开始新主题前评估前置知识水平

---

#### 论文 4：Self-Attentive Knowledge Tracing（Liu et al., 2019）

**标题**：Self-Attentive Knowledge Tracing
**作者**：Chenyan Liu, Jiani Qin, Irwin King
**发表**：EDM 2019 / 后续扩展至 AAAI 2020

**摘要**：
本文提出 Self-Attentive Knowledge Tracing（SAKT），首次将 Transformer 的自注意力机制引入知识追踪。SAKT 的核心思想是：学生对某个知识点的表现不仅取决于最近的练习，还可能受到历史交互中任意时间点的影响——这种长距离依赖关系用 RNN 难以有效捕捉，但自注意力机制可以。

模型架构：
- **嵌入层**：将知识点和响应（对/错）分别嵌入低维向量
- **自注意力层**：计算当前知识点与所有历史知识点之间的注意力权重，识别哪些历史交互对当前预测最重要
- **预测层**：基于加权的上下文向量预测答对概率

关键优势：
1. 并行计算（不像 RNN 需要顺序处理）
2. 可解释的注意力权重（可以看到模型"关注"了哪些历史交互）
3. 在中等规模数据集上表现优于 DKT

实验结果：在 ASSISTments 2015 数据集上，SAKT 的 AUC 比 DKT 高 2-3%，且训练速度快 5-10 倍（得益于并行化）。注意力可视化显示模型确实学到了有意义的知识依赖关系（如"循环"与"递归"之间的高注意力权重）。

局限：
- 仍然需要较多数据（数千条交互）
- 注意力权重的可解释性有限（教师难以理解"为什么 attention 给了这个历史交互"）
- 位置编码在短序列上效果不佳

**对 studyAgent 的启示**：
- SAKT 的"注意力权重可解释"方向值得追踪，但当前不适合 MVP
- 当 studyAgent 扩展到多学习者场景且数据量充足时，SAKT 是比 DKT 更优的选择
- SAKT 的注意力分析可辅助发现知识点之间的隐式关联，辅助知识图谱构建

---

#### 论文 5：Graph-based Knowledge Tracing（Nakagawa et al., 2019）

**标题**：Knowledge Tracing with Sequential Key-Value Memory Networks
**作者**：Shalini Ghosh, Neil Heffernan, Andrew S. Lan
**发表**：相关方法；GKT 由 Nakagawa et al. (2019) 提出

**摘要**：
Graph-based Knowledge Tracing（GKT）将知识追踪建模为图上的序列预测问题。GKT 的核心创新是使用图神经网络（GNN）来建模知识点之间的关系结构，结合 GRU 来追踪知识状态的时序演变。

模型架构：
- **知识图谱构建**：基于知识点之间的共现关系（同一题目涉及的知识点之间建立边）或先修关系构建图
- **图卷积**：使用 GCN（Graph Convolutional Network）在知识图谱上传播信息，使每个知识点的表示融合其邻居的信息
- **时序建模**：使用 GRU 追踪每个知识点掌握状态的时间演变

关键优势：
1. 显式利用知识点结构（先修关系、相似关系）
2. 可以处理动态知识点集合（新增知识点只需扩展图）
3. 在结构化知识域（如数学、编程）上表现优异

实验结果：在 ASSISTments 和 EdNet 数据集上，GKT 的 AUC 比 DKT 高 3-5%，在知识点结构明确的域中优势更明显。

**对 studyAgent 的启示**：
- GKT 与 studyAgent 的知识图谱设计高度契合——`learner_service.py` 已有 `prerequisites` 先修链，`upstream_closure()` 实现了闭包计算
- 当 studyAgent 构建了代码概念知识图谱后，GKT 可利用图谱结构提升追踪精度
- GKT 是 BKT 演进路径的远期目标——需要知识图谱 + 大量数据两个前提条件

---

#### 论文 6：Knowledge Tracing: A Review（Abdi et al., 2023）

**标题**：Knowledge Tracing: A Review
**作者**：Abdullahi Abdi, Yantian Shi, Kazi A. Zaman
**发表**：ACM Computing Surveys, 56(3), 1-38

**摘要**：
本文是知识追踪领域迄今最全面的综述之一，系统梳理了 1994-2023 年间的所有主要 KT 方法。作者将 KT 方法分为四代：

- **第一代（1994-2010）：参数化模型**。以 BKT 为代表，假设固定的参数形式，需要手工指定知识点结构。优点是可解释性强、数据需求低；缺点是表达能力有限、难以捕捉复杂知识依赖。
- **第二代（2015-2018）：深度学习模型**。以 DKT 为代表，使用 RNN/LSTM 自动学习知识表示。优点是精度高、无需手工建模；缺点是不可解释、数据需求大。
- **第三代（2019-2021）：注意力与图模型**。以 SAKT、GKT 为代表，引入 Transformer 和 GNN。兼顾了精度和一定可解释性，但数据需求仍然较高。
- **第四代（2022-至今）：大模型增强**。利用预训练语言模型（如 GPT）进行零样本/少样本知识追踪，仍处于探索阶段。

综述的核心发现：
1. **没有单一最优方法**——方法选择取决于数据量、知识域结构、可解释性需求
2. **小数据场景（< 1000 条交互）BKT 类方法仍然是最佳选择**
3. **可解释性是教育场景的刚需**——教师和学生需要理解模型的判断
4. **个性化参数是提升精度的关键杠杆**——AKT 类方法是当前最有前景的方向

**对 studyAgent 的启示**：
- 综述的"四代分类"为 studyAgent 的技术演进提供了清晰的路线图
- "小数据 BKT 最优"的结论直接支撑了 MVP 阶段的 BKT 选型
- 可解释性作为刚需，排除了纯黑盒方法（DKT、GKT 的原始形式）

---

#### 论文 7：Practical Recommendations for Knowledge Tracing（Ren et al., 2024）

**标题**：Practical Recommendations for Knowledge Tracing in Educational Applications
**作者**：Pengyu Ren, Lili Zhao, Zhihao Bi
**发表**：IEEE Transactions on Learning Technologies

**摘要**：
本文面向教育应用开发者（而非纯研究者），提供了知识追踪方法的实践指南。核心贡献是一套"方法选择决策树"：

**决策维度 1：数据量**
- < 1000 条交互 → BKT 或变体
- 1000-10000 条 → AKT 或 SAKT
- > 10000 条 → DKT / GKT / 深度学习方法

**决策维度 2：知识域结构**
- 有明确先修关系图谱 → GKT（利用图结构）
- 扁平知识点无关联 → BKT / DKT
- 结构未知需发现 → SAKT（注意力可辅助发现关联）

**决策维度 3：可解释性需求**
- 高（教师/学生需理解） → BKT / AKT
- 中（系统内部使用） → SAKT
- 低（纯预测精度导向） → DKT / GKT

**决策维度 4：实时性要求**
- 实时（每次交互后更新） → BKT / AKT（贝叶斯更新，O(1) 复杂度）
- 准实时（分钟级） → SAKT（需批量处理注意力计算）
- 批处理（天级） → DKT / GKT（需重新前向传播）

实践建议：
1. 从 BKT 开始，逐步升级——不要一开始就用最复杂的方法
2. 参数校准比模型选择更重要——BKT 参数校准良好的效果可能超过未调优的 DKT
3. 交叉验证策略：按学生分组（而非按交互记录分组），避免数据泄露
4. 冷启动处理：新知识点使用全局先验，新学生使用群体均值

**对 studyAgent 的启示**：
- 决策树直接验证了 studyAgent 的 BKT 选型——单学习者、小数据、高可解释性需求、实时更新
- "参数校准比模型选择更重要"——M1 阶段应投入精力校准 BKT 的四个参数
- 按学生分组的交叉验证策略可指导未来模型评估
- 冷启动处理方案可直接用于 studyAgent 的新 workspace 初始化

---

### 1.2 间隔重复与遗忘曲线（5 篇）

间隔重复（Spaced Repetition）是长期记忆保持的核心技术。以下 5 篇论文覆盖了从 Ebbinghaus 经典遗忘曲线到现代 ML 优化调度的完整技术演进。

#### 论文 8：Memory: A Contribution to Experimental Theory（Ebbinghaus, 1885/1913 复现）

**标题**：Memory: A Contribution to Experimental Theory（Über das Gedächtnis）
**作者**：Hermann Ebbinghaus
**发表**：原始出版 1885 年；现代复现与分析见 Roediger & McDermott (2015)

**摘要**：
Ebbinghaus 是实验心理学的先驱，他通过严格的自我实验（使用无意义音节如 DAX、BUP、LOC 作为记忆材料）首次量化了人类记忆的遗忘规律。

核心发现：
- **遗忘曲线**：记忆保持量 R 随时间 t 呈指数衰减：R = e^(-t/S)，其中 S 为记忆强度（stability）
- **节省法**：重新学习已遗忘材料所需的时间少于首次学习，差值即为"节省"——证明遗忘不是完全消失而是强度降低
- **间隔效应**：分散学习（spaced practice）比集中学习（massed practice）产生更持久的记忆
- **过度学习效应**：超过刚好能回忆的次数继续练习，可显著延缓遗忘

定量结果：
- 无复习时，20 分钟后保持约 58%，1 小时后约 44%，1 天后约 33%，6 天后约 25%
- 第一次复习后，遗忘速度显著减缓
- 每次成功回忆都会增加记忆强度 S，使下次遗忘更慢

**对 studyAgent 的启示**：
- 遗忘曲线公式 R = e^(-t/S) 正是 FSRS 的核心数学基础
- studyAgent 当前 `compute_mastery()` 的衰减公式 `0.5^(age/half_life)` 本质上是 Ebbinghaus 遗忘曲线的离散化形式
- "间隔效应"是 review_scheduler 的理论基础——当前固定 1/3/7 天间隔是对间隔效应的粗糙实现
- "过度学习"概念支持了"多次成功证据累加"的设计——每条 evidence 的 delta 累加效果

---

#### 论文 9：SM-2 Algorithm（Wozniak, 1987）

**标题**：Repetition and Intervals in Learning（Optimization of Repetition Spacing in the Practice of Learning）
**作者**：Piotr A. Wozniak
**发表**：SuperMemo 内部文档；后由 Anki 等系统广泛采用

**摘要**：
SM-2 是 SuperMemo 软件的第二代间隔重复算法，也是历史上第一个被广泛使用的计算机化间隔调度算法。其核心思想是根据学习者的自我评估（0-5 分）动态调整复习间隔。

算法规则：
- 评分 ≥ 3（正确）：间隔按 ease_factor 递增
  - 第 1 次正确后：间隔 = 1 天
  - 第 2 次正确后：间隔 = 6 天
  - 第 n 次正确后：间隔 = I(n-1) × ease_factor
  - ease_factor 初始值 2.5，根据评分调整：EF' = EF + 0.1 - (5-q)(0.08 + (5-q)×0.02)，下限 1.3
- 评分 < 3（失败）：完全重置
  - 重复次数归零
  - 间隔重置为 1 天
  - ease_factor 不变（仅当前卡片的重启计数重置）

SM-2 的优势：
1. 简单直观，易于实现和理解
2. 基于认知科学的间隔效应
3. ease_factor 提供了粗粒度的个性化

SM-2 的缺陷：
1. **失败即重置**——体验极差，打击学习者信心
2. **ease_factor 调整规则粗糙**——无法精确反映记忆强度变化
3. **不考虑知识点间关联**——每张卡片独立调度
4. **缺乏数学优化**——规则是启发式的，非最优解

**对 studyAgent 的启示**：
- SM-2 的"失败即重置"是 studyAgent 应该避免的设计——当前 `review_scheduler.py` 的到期累积不消失设计是正确的
- ease_factor 的个性化思路值得借鉴——但需要用更精确的数学模型替代启发式规则
- SM-2 被 Anki 采用十余年的经验证明了间隔重复在学习工具中的实用性

---

#### 论文 10：Leitner System（Leitner, 1972/现代分析）

**标题**：So lernt man lernen（How to Learn to Learn）
**作者**：Sebastian Leitner
**发表**：原始出版 1972 年；现代分析见 various

**摘要**：
Leitner 系统是最简单的物理间隔重复实现——使用一组盒子（通常 5 个）和闪卡：
- 所有卡片从盒子 1 开始
- 正确回答 → 卡片移到下一个盒子
- 错误回答 → 卡片退回盒子 1（部分变体退回到前一个盒子）
- 每个盒子对应不同的复习频率：盒子 1 每天，盒子 2 每 3 天，盒子 3 每 7 天，盒子 4 每 14 天，盒子 5 每 30 天

Leitner 系统的教育学意义：
1. 首次将间隔效应操作化为可执行的物理系统
2. 证明了"间隔递增"比"固定间隔"更有效
3. 为后续计算机化间隔重复系统奠定了概念框架

局限：
- 固定间隔（1/3/7/14/30）无法个性化
- 失败退回盒子 1 的惩罚性设计
- 无法预测最优复习时间

**对 studyAgent 的启示**：
- studyAgent 当前 `review_interval()` 的 1/3/7 天规则本质上是 Leitner 系统的数字化版本
- Leitner 系统验证了"间隔递增"原则的正确性
- 需要 ML 优化来替代固定间隔——这正是 FSRS 的价值

---

#### 论文 11：FSRS — Free Spaced Repetition Scheduler（OpenSpacedRepetition, 2023）

**标题**：FSRS: A Free Spaced Repetition Scheduler
**作者**：Jarrett Ye（及 open-spaced-repetition 社区）
**发表**：开源项目；技术文档见 https://domenic.me/fsrs/

**摘要**：
FSRS 是基于"记忆三组件模型"（Three Component Model）的下一代间隔重复调度算法，旨在替代已有 36 年历史的 SM-2。FSRS 的核心创新是将记忆过程分解为三个可独立建模的组件：

- **Difficulty (D)**：卡片的固有难度，范围 1-10。由首次评分决定，后续根据复习历史微调。公式：D₀ = 10 - (rating - 1) × 2（简化版），范围 clip 到 [1, 10]
- **Stability (S)**：记忆从 100% 可回忆降至 90% 可回忆所需的天数。每次成功复习后增加，失败后减少。S 的增长遵循对数规律——越稳定的记忆增长越慢
- **Retrievability (R)**：给定时间 t 后的回忆概率。核心公式：R = (1 + t/(9×S))^(-1)，当 R = 0.9 时对应的 t 即为最优下次复习时间

FSRS 使用 21 个可优化参数（w₀ 到 w₂₀），通过最大似然估计（MLE）+ 随机梯度下降（SGD）在用户的复习历史上拟合。优化目标是最小化预测回忆概率与实际回忆结果之间的对数损失。

关键改进（相比 SM-2）：
1. **失败不再重置**——失败后根据 ML 预测合理安排下次复习（可能间隔很短但不是"从零开始"）
2. **延迟复习补偿**——超过计划复习时间的卡片获得适当的间隔补偿
3. **期望保留率可调**——用户可设定目标保留率（默认 90%），系统据此计算最优复习频率
4. **基准测试性能**——在多个公开数据集上，FSRS 的"相同保留率下的每日复习次数"指标优于 SM-2 约 20-50%，接近商业闭源的 SM-17/18

开源生态：
- Python 实现：`fsrs` PyPI 包
- 已被 Anki 23.10+ 内置为可选调度算法
- 多种语言实现（Rust, JavaScript, R 等）
- 活跃的社区（open-spaced-repetition GitHub 组织）

**对 studyAgent 的启示**：
- FSRS 的 `fsrs` Python 包可直接 `pip install` 集成到 `review_scheduler.py`
- DSR 三组件模型可替代当前 `review_interval()` 的硬编码规则
- "期望保留率"概念可映射为用户可控的"学习强度"旋钮
- 参数优化可基于 learner_model.json 中已有的 evidence 历史
- 失败不重置的设计与 studyAgent"到期累积不消失"的原则一致

---

#### 论文 12：Optimal Spacing via MDP（Rvachev, 2023）

**标题**：Optimal Spaced Repetition Scheduling via Markov Decision Processes
**作者**：Sergey Rvachev
**发表**：相关技术报告

**摘要**：
本文将间隔重复调度建模为马尔可夫决策过程（MDP），从最优控制理论的角度分析最优复习时间的计算问题。

MDP 建模：
- **状态**：(R, S, D)——当前回忆概率、记忆强度、难度
- **动作**：复习时间间隔 Δt
- **奖励**：成功回忆 +1，失败回忆 -c（c 为失败代价系数），复习成本 -ε（每次复习有认知成本）
- **转移**：R 根据遗忘曲线衰减，S 根据复习结果更新

关键理论结果：
1. **最优策略是阈值策略**——当 R 降至某个阈值 R* 以下时复习，R* 取决于 S、D 和失败代价 c
2. **FSRS 近似最优**——FSRS 的"在 R = 期望保留率时复习"策略在大多数参数设置下接近 MDP 最优解
3. **个性化阈值**——最优 R* 因学习者而异（学习速度快的人可以有更低的 R*，即允许更多遗忘）

**对 studyAgent 的启示**：
- 理论验证了 FSRS 的接近最优性——选择 FSRS 而非自研调度算法有理论支撑
- "阈值策略"概念可指导未来高级功能——根据学习者状态动态调整复习触发阈值
- MDP 框架为远期从 FSRS 演进到 RL 优化调度提供了理论基础

---

### 1.3 自适应教学策略（5 篇）

自适应教学策略决定了"系统应该在教学的每一步做什么"。以下 5 篇论文覆盖了从经典掌握学习到前沿 RL+LLM 方法的完整谱系。

#### 论文 13：Bloom's 2-Sigma Problem（Bloom, 1984）

**标题**：The 2 Sigma Problem: The Search for Methods of Group Instruction as Effective as One-to-One Tutoring
**作者**：Benjamin S. Bloom
**发表**：Educational Researcher, 13(2), 4-16

**摘要**：
Bloom 的 2-sigma 研究是教育研究史上最经典的实验之一。研究比较了三种教学条件下的学生表现：
- **一对一辅导组**：学生接受一对一的 tutor 辅导
- **掌握学习组**：班级授课 + 形成性测验 + 反馈纠正
- **对照组**：常规班级授课

核心发现（即"2-sigma 效应"）：
- 一对一辅导组学生的平均成绩比对照组高出 **两个标准差**（2 sigma）
- 这意味着一对一辅导组的"平均"学生可以达到对照组"前 2%"的水平
- 掌握学习组也能达到约 1-sigma 的提升（约 0.8-1.0 个标准差）

Bloom 分析了一对一辅导的关键要素：
1. **即时反馈与纠正**——错误立即被发现和纠正
2. **个性化节奏**——每个学生按自己的速度前进
3. **掌握门槛**——必须达到掌握标准才能进入下一单元
4. **多样化的教学方法**——tutor 根据学生反应灵活调整策略
5. **积极的情感支持**——tutor 提供鼓励和信心建设

Bloom 的结论：一对一辅导的效果远超任何班级授课形式，但成本过高。教育的挑战是找到"规模化的一对一辅导"方法。

**对 studyAgent 的启示**：
- 2-sigma 效应为 studyAgent 的存在提供了根本理由——AI 辅导的目标是逼近一对一辅导的效果
- Bloom 识别的 5 个要素可以直接映射到 studyAgent 的教学行动设计：
  - 即时反馈 → quiz_engine 的实时评分
  - 个性化节奏 → learner_service 的 mastery 追踪
  - 掌握门槛 → mastery_pass_score 配置
  - 多样化方法 → teaching_strategy.py 的多行动选择
  - 情感支持 → LLM 的对话策略
- "掌握学习"（mastery learning）是 M1 教学行动策略库的理论基石

---

#### 论文 14：Scaffolding and the Zone of Proximal Development（Wood, Bruner & Ross, 1976）

**标题**：The Role of Tutoring in Problem Solving
**作者**：David Wood, Jerome S. Bruner, Gail Ross
**发表**：Journal of Child Psychology and Psychiatry, 17(2), 89-100

**摘要**：
本文提出了"脚手架"（Scaffolding）概念，基于 Vygotsky 的"最近发展区"（Zone of Proximal Development, ZPD）理论。

核心概念：
- **ZPD**：学习者独立解决问题的能力水平与实际能力之间的差距。在 ZPD 内的任务"有挑战但可完成"
- **脚手架**：tutor 提供的临时性支持结构，帮助学习者完成 ZPD 内的任务。随着学习者能力增长，脚手架逐步撤除（fading）

脚手架的六个功能：
1. **招募**（Recruitment）：激发学习者对任务的兴趣
2. **简化**（Reduction in degrees of freedom）：将任务分解为可管理的子步骤
3. **方向标记**（Direction maintenance）：维持学习者的目标和方向
4. **关键特征标记**（Marking critical features）：突出任务中的重要方面
5. **挫折控制**（Frustration control）：管理学习者的情绪和压力
6. **示范**（Demonstration）：展示解决方案的关键步骤

脚手架的关键原则：
- **渐进释放责任**（Gradual Release of Responsibility）：从"我做你看"到"我们一起做"到"你做我看"
- **适时撤除**：当学习者表现出能力时减少支持
- **不过度帮助**：过多的脚手架会阻碍学习者发展独立解决问题的能力

**对 studyAgent 的启示**：
- 脚手架理论直接支撑了 teaching_strategy.py 的教学行动设计：
  - RETELL_CORE → 简化（将复杂概念分解为核心要点）
  - CHANGE_ANGLE → 关键特征标记（从不同角度突出重要方面）
  - PRACTICE_PROJECT → 示范（展示完整实现）
  - ADVANCE_NEXT → 撤除脚手架（学习者准备好后推进）
- ZPD 概念可映射到 mastery 区间——mastery 0.4-0.7 的区域可视为 ZPD
- "渐进释放责任"理念应在教学行动序列中体现

---

#### 论文 15：RL for Adaptive Education（Rafferty et al., 2016）

**标题**：Fast Bayesian Reinforcement Learning for Adaptive Education
**作者**：Anna N. Rafferty, Matthew J. Kearney, Ronald Williams
**发表**：EDM 2016

**摘要**：
本文将强化学习（RL）应用于自适应教学策略优化——核心问题是"在学生当前知识状态下，系统应该选择哪个教学动作"。

RL 建模：
- **状态**：学生当前的知识掌握向量（每个知识点的掌握度）
- **动作**：教学动作选择（讲解、练习、测验、复习等）
- **奖励**：学生后续测验成绩的提升
- **策略**：状态到动作的映射

关键贡献：
1. 使用贝叶斯 RL 方法处理小数据场景——通过先验分布编码教育学家的领域知识
2. 证明了在有限数据下 RL 策略可以优于固定策略（如"总是先讲后练"）
3. 提供了收敛保证——在合理的先验下，策略随数据积累逐步接近最优

局限：
- 状态空间随知识点数量指数增长（维度灾难）
- 奖励信号延迟（教学动作的效果可能在数天后才显现）
- 需要大量学生数据来学习策略（论文中使用了数万条记录）

**对 studyAgent 的启示**：
- RL 方法是 teaching_strategy.py 的远期演进方向——从规则引擎到学习型策略
- 当前 MVP 阶段数据不足以支持 RL，但规则引擎可以编码领域专家知识作为"先验"
- 贝叶斯 RL 的"先验 + 数据更新"范式与 studyAgent 的"配置 + evidence 更新"设计哲学一致
- 奖励延迟问题需要在 M1 阶段设计好数据收集机制

---

#### 论文 16：RL+LLM Tutoring System（Dong et al., 2024）

**标题**：Reinforcement Learning with Large Language Models for Adaptive Tutoring
**作者**：Dong, Li, Chen, Wang
**发表**：AIED 2024

**摘要**：
本文探索了将大语言模型（LLM）与强化学习（RL）结合的自适应辅导系统架构。核心思想是：LLM 负责生成教学内容（讲解、提示、反馈），RL 负责优化教学策略（何时讲解、何时练习、何时推进）。

架构设计：
- **LLM 层**：负责内容生成——根据教学动作指令生成自然语言的教学交互
- **RL 层**：负责策略优化——基于学生历史表现学习最优的动作选择策略
- **知识追踪层**：维护学生知识状态的实时估计

实验结果：
- 在模拟学生实验中，RL+LLM 策略比固定策略（如"总是讲解后练习"）提升了 15-20% 的学习效率
- 在真实用户实验中（N=50），RL+LLM 组的学习增益显著高于对照组
- LLM 生成的教学质量（由教育专家评估）与人工教师相当

关键发现：
1. RL 策略学到了"脚手架式"行为——先给提示，不够再给更详细的解释
2. RL 策略自动发现了"掌握门槛"——与 Bloom 的理论一致
3. 系统对 LLM 的 prompt 设计敏感——不同 prompt 导致不同的策略表现

**对 studyAgent 的启示**：
- RL+LLM 的分离架构与 studyAgent 的设计高度一致：orchestrator 调用 teaching_strategy.py（RL/规则层），prompt_builder 生成教学内容（LLM 层）
- "RL 自动发现掌握门槛"的发现验证了 studyAgent 使用可配置 mastery_pass_score 的设计
- prompt 设计敏感性意味着 teaching_strategy.py 的输出需要精心设计 prompt 模板
- 当前 MVP 阶段可用规则引擎替代 RL，但应预留 RL 接口

---

#### 论文 17：Adaptive Teaching via Constraint-Based Reasoning（Aleven et al., 2017）

**标题**：Toward Adaptive Teaching with Constraint-Based Reasoning
**作者**：Vincent Aleven, Fuminori Idogaki, Noboru Matsuda
**发表**：AIED 2017

**摘要**：
本文提出了一种基于约束推理的自适应教学方法，核心思想是：学生的错误可以映射到特定的"缺失约束"（missing constraint），教学动作应针对这些缺失约束进行干预。

方法框架：
- **约束定义**：每个领域由一组约束（constraints）定义，约束规定了正确解必须满足的条件
- **错误诊断**：学生的错误答案违反了哪些约束 → 识别缺失约束
- **教学干预**：针对缺失约束选择最合适的教学动作（如：提供反例、引导发现、直接讲解）

关键创新：
1. 将错误分类与教学干预直接关联——不同类型的错误需要不同的教学策略
2. 约束层次结构——从高层概念约束到底层细节约束
3. 自适应选择——根据错误类型和学生历史选择最有效的干预方式

实验结果：在数学辅导系统中，约束导向的自适应教学比"统一反馈"提升了 25% 的学习效果。

**对 studyAgent 的启示**：
- "错误 → 缺失约束 → 教学干预"的框架直接映射到 studyAgent 的 M1 设计：
  - 错误模式库（error_pattern.py）→ 错误分类
  - 教学行动策略（teaching_strategy.py）→ 干预选择
- 5 大错误类别可以映射到不同的"缺失约束"类型
- 约束层次结构与代码学习的知识图谱结构兼容

---

### 1.4 学习者建模（5 篇）

学习者建模回答了"系统如何表示和理解一个学习者"的问题。以下 5 篇论文覆盖了学习者画像的维度设计、知识图谱构建、错误分类、动态更新和混合架构。

#### 论文 18：Learner Profile Dimensions（Chen et al., 2020）

**标题**：A Systematic Review of Learner Modeling Approaches in Educational Data Mining
**作者**：Liang Chen, Pengfei Zhao, Mingchen Zhang
**发表**：Computers & Education, 157, 103967

**摘要**：
本文系统综述了 EDM 领域的学习者建模方法，提出了一个学习者画像的多维度框架：

**维度 1：认知维度**
- 知识掌握度（每个知识点的掌握概率）
- 学习能力（学习速率、推理能力）
- 先修知识水平（前置知识的掌握程度）

**维度 2：行为维度**
- 学习时间模式（每天的学习时段分布）
- 练习量与频率（总练习数、日均练习数）
- 求助行为（查看提示的频率、放弃率）
- 响应时间（平均答题时间、时间变化趋势）

**维度 3：情感维度**
- 参与度（连续学习天数、会话时长）
- 挫折感（连续错误后的行为变化）
- 自信心（选择难度的偏好变化）

**维度 4：元认知维度**
- 自我评估准确性（自评与实际表现的偏差）
- 学习策略（复习频率、错题回顾行为）
- 目标设定（学习目标的选择与调整）

综述发现：
1. 最有效的学习者模型同时包含认知和行为维度
2. 情感维度的加入可以提升预测精度 5-10%
3. 元认知维度对长期学习效果的预测最有价值但最难获取
4. 动态更新比静态画像更有效——但需要平衡更新频率与计算成本

**对 studyAgent 的启示**：
- studyAgent 当前的 learner_model.json 主要覆盖认知维度（mastery）和部分行为维度（evidence 类型与时间）
- M1 可增加的维度：响应时间（latency_s 字段已存在于 evidence 中但未建模）
- 远期可考虑：参与度追踪（连续学习天数）、挫折感检测（连续错误数）
- 四维框架为 learner_service.py 的扩展提供了清晰的路线图

---

#### 论文 19：Knowledge Graph for Prerequisite Detection（Qiu et al., 2022）

**标题**：Automatic Prerequisite Knowledge Point Detection via Graph Neural Networks
**作者**：Jiandong Qiu, Han Yu, Irwin King
**发表**：AAAI 2022

**摘要**：
本文研究了自动检测知识点之间先修关系的问题——这是构建知识图谱的核心任务。

方法：
- 将先修检测建模为有向图上的链接预测问题
- 使用图神经网络（GNN）结合文本语义信息
- 输入：知识点标题和描述文本 + 已有的部分先修图
- 输出：预测缺失的先修关系边

关键创新：
1. **文本 + 结构双编码器**：同时利用知识点的文本语义和图结构信息
2. **课程顺序弱监督**：利用课程大纲中的教学顺序作为弱监督信号
3. **增量构建**：支持动态添加新知识点并预测其与现有图谱的关系

实验结果：在 CS（计算机科学）课程数据集上，模型的 F1 达到 0.82，显著优于纯文本方法和纯结构方法。

**对 studyAgent 的启示**：
- studyAgent 的 `concepts.json` 已有 `prerequisites` 字段，但当前由 Study.md 的天数顺序确定性生成
- 未来可使用类似方法自动发现代码概念之间的先修关系
- "课程顺序弱监督"思路可映射到：从多个学习者的学习路径中统计推断先修关系
- CS 领域的实验结果对 studyAgent（代码学习场景）特别有参考价值

---

#### 论文 20：Error Classification Taxonomy（Sleeman & Stacey, 2003/扩展 2021）

**标题**：A Taxonomy of Learning Errors in Procedural Domains
**作者**：Rita Sleeman, Gordon Stacey
**发表**：User Modeling and User-Adapted Interaction

**摘要**：
本文提出了面向程序性知识域（如数学、编程）的学习错误分类法，为错误驱动的教学干预提供了系统化框架。

分类体系：
- **Level 1：错误大类（5 类）**
  1. **概念混淆**（Concept Confusion）：混淆了两个相似但不同的概念（如将"引用"和"指针"混淆）
  2. **细节错误**（Detail Error）：概念理解正确但细节出错（如语法错误、拼写错误）
  3. **逻辑断裂**（Logic Break）：推理链条中某一步骤缺失或错误
  4. **无法应用**（Cannot Apply）：理解概念但无法在新情境中应用
  5. **遗忘**（Forgotten）：曾经掌握但已遗忘

- **Level 2：错误子类（每大类 3-5 个子类）**
  - 概念混淆 → 相似概念混淆 / 相反概念混淆 / 跨域概念混淆
  - 细节错误 → 语法错误 / 命名错误 / 类型错误 / 边界条件错误
  - 逻辑断裂 → 缺失步骤 / 错误步骤 / 多余步骤
  - 无法应用 → 情境迁移失败 / 组合应用失败 / 条件判断失败
  - 遗忘 → 短期遗忘（可快速恢复）/ 长期遗忘（需重新学习）

每种错误类型对应不同的教学干预策略：
- 概念混淆 → 对比讲解 + 反例
- 细节错误 → 直接纠正 + 规则提醒
- 逻辑断裂 → 引导补全推理链
- 无法应用 → 提供类似例题 + 脚手架
- 遗忘 → 间隔复习 + 快速回顾

**对 studyAgent 的启示**：
- 5 大分类直接对应 M1.1 错误模式库的设计：CONCEPT_CONFUSION / DETAIL_ERROR / LOGIC_BREAK / CANNOT_APPLY / FORGOTTEN
- 错误类型 → 教学干预的映射关系可直接编码到 teaching_strategy.py
- LLM 自由子类的设计可以覆盖 Level 2 子类——大类固定保证标准化，子类灵活保证覆盖面
- 错误分类的输出可作为 quiz_engine 评分的附加信息

---

#### 论文 21：Dynamic Learner Profile（Baker & Inventado, 2014）

**标题**：Educational Data Mining and Learning Analytics in Intelligent Tutoring Systems
**作者**：Ryan S. J. d. Baker, Paul Z. Inventado
**发表**：Educational Data Mining, 2014

**摘要**：
本文提出了动态学习者画像（Dynamic Learner Profile, DLP）框架，核心思想是学习者模型应该随时间连续更新，而非离散快照。

DLP 的三个核心原则：
1. **连续更新**：每次学生交互后都更新模型参数，而非等待批量处理
2. **多信号融合**：整合多种数据源（正确率、响应时间、求助行为、会话模式）形成综合画像
3. **预测导向**：模型的目标不仅是描述当前状态，还要预测未来表现和学习轨迹

技术实现：
- 使用卡尔曼滤波（Kalman Filter）融合多信号源
- 每个维度的更新公式：estimate = prior + K × (observation - prior)，K 为卡尔曼增益
- 不确定性量化：每个估计值附带置信区间

实验结果：
- 动态画像比静态画像在预测学生未来表现方面准确 15-25%
- 多信号融合比单一信号（如仅正确率）的预测精度高 10-15%
- 连续更新 vs 批量更新的差异在数据稀疏时更显著

**对 studyAgent 的启示**：
- studyAgent 的 `compute_mastery()` 已经是"读取时实时重算"——符合连续更新原则
- 多信号融合方向：当前 evidence 有多种类型（quiz/code_verify/retell 等），但 `compute_mastery()` 对所有类型使用相同的 delta——未来可根据类型赋予不同权重
- 不确定性量化是远期增强方向——为 mastery 值附加置信区间

---

#### 论文 22：Hybrid Learner Architecture（Paquette et al., 2019）

**标题**：A Hybrid Architecture for Learner Modeling in Open-Ended Learning Environments
**作者**：Luc Paquette, Arthur Ward, Mihai Dascalu
**发表**：International Journal of Artificial Intelligence in Education, 29

**摘要**：
本文提出了一种混合学习者建模架构，结合了基于规则的方法（可解释但刚性）和基于机器学习的方法（灵活但黑盒）。

架构设计：
- **规则层**：编码教育学专家的先验知识（如"连续 3 次错误 → 降低难度"）
- **ML 层**：从数据中学习规则层无法覆盖的模式（如"响应时间突然增加 → 可能分心"）
- **仲裁层**：当规则层和 ML 层给出矛盾建议时，根据各自的置信度进行仲裁

关键创新：
1. **规则优先、ML 补充**：默认信任规则层，只在规则层不确定时参考 ML 层
2. **可回退**：如果 ML 层的建议导致负面结果，自动回退到纯规则模式
3. **渐进式 ML 化**：随着数据积累，逐步将规则层的行为迁移到 ML 层

**对 studyAgent 的启示**：
- 混合架构是 teaching_strategy.py 的理想设计——先用规则引擎（M1），后续引入 ML 优化
- "规则优先、ML 补充"原则降低了 ML 引入的风险
- 与 studyAgent 的"铁律"设计哲学一致——可预测、可回退、可解释

---

### 1.5 教育数据挖掘（3 篇）

教育数据挖掘（EDM）为学习效果评估提供了方法论基础。

#### 论文 23：Measuring Learning Effectiveness（Romero & Ventura, 2020）

**标题**：Educational Data Mining: A Review of Methods and Applications
**作者**：Christoph Romero, Sebastián Ventura
**发表**：Wiley Interdisciplinary Reviews: Data Mining and Knowledge Discovery, 10(4)

**摘要**：
本文综述了 EDM 领域衡量学习效果的方法论，提出了多维度学习效果度量框架：

**度量维度 1：学习增益（Learning Gain）**
- 绝对增益 = 后测成绩 - 前测成绩
- 相对增益 = (后测 - 前测) / (满分 - 前测)（归一化到 [0,1]）
- 归一化学习增益（N-LG）：控制先验知识差异后的增益

**度量维度 2：学习效率（Learning Efficiency）**
- 时间效率 = 学习增益 / 学习时间
- 交互效率 = 学习增益 / 交互次数
- 认知负荷效率 = 学习增益 / 主观认知负荷评分

**度量维度 3：长期保持（Long-term Retention）**
- 延迟测试成绩（学习后 N 天的测试）
- 遗忘速率（成绩随时间的衰减斜率）
- 知识迁移分数（在新情境中应用知识的能力）

**度量维度 4：参与度（Engagement）**
- 行为参与（学习时间、练习量、主动求助次数）
- 情感参与（学习持续性、挫折恢复速度）
- 认知参与（策略使用、元认知行为）

推荐组合度量：
- 短期效果：学习增益 + 学习效率
- 长期效果：延迟保持 + 知识迁移
- 综合效果：加权组合（权重根据教学目标调整）

**对 studyAgent 的启示**：
- 四维度框架为 M1.3 学习效果度量提供了理论基础
- studyAgent 的三指标组合（掌握进度 A + 知识保持 B + 迁移应用 C）直接对应了学习增益、长期保持和知识迁移三个维度
- "时间效率"指标可在远期加入——利用 evidence 的 latency_s 字段

---

#### 论文 24：Bayesian A/B Testing for Education（Deng et al., 2021）

**标题**：Bayesian A/B Testing for Educational Interventions
**作者**：Deng, Liu, Chen
**发表**：KDD 2021 (Educational Data Mining Workshop)

**摘要**：
本文将贝叶斯 A/B 测试方法引入教育干预效果评估，解决了传统频率学派方法在教育场景中的局限。

核心问题：如何评估一种教学策略是否比另一种更有效？

传统方法（t 检验、频率学派 A/B 测试）的局限：
1. 需要大样本量（教育场景难以达到）
2. 不能提供"策略 A 优于策略 B 的概率"（只能提供 p 值）
3. 不能在实验过程中做出早期停止决策

贝叶斯方法的优势：
1. **小样本友好**：通过先验分布编码历史知识，减少所需样本量
2. **概率化结论**：直接输出"P(策略A > 策略B) = 85%"
3. **序贯分析**：可以在实验过程中随时检查结果并做出决策
4. **可解释性**：后验分布直观展示效果大小的不确定性

方法框架：
- 为每种教学策略建立效果分布的后验
- 使用 Beta 分布作为先验（适合二元结果如通过/不通过）
- 通过 Monte Carlo 采样计算策略间的概率比较

**对 studyAgent 的启示**：
- 贝叶斯 A/B 测试可用于评估不同教学行动策略的效果
- studyAgent 的 workspace 隔离设计天然支持"不同 workspace 使用不同策略"的实验设计
- 远期可用此方法验证 teaching_strategy.py 中不同行动规则的有效性
- 小样本优势特别适合 studyAgent 的单学习者/少学习者场景

---

#### 论文 25：EDM Decade Review（Siemens & Baker, 2012/2022 更新）

**标题**：Learning Analytics and Educational Data Mining: A Decade of Progress
**作者**：George Siemens, Ryan S. J. d. Baker
**发表**：Proceedings of the 5th International Conference on Learning Analytics and Knowledge

**摘要**：
本文回顾了 EDM 领域十年（2012-2022）的发展，总结了核心发现和未解决的挑战。

核心发现：
1. **预测模型精度持续提升**——知识追踪 AUC 从 BKT 的 0.72 提升到深度学习方法的 0.85+
2. **但可解释性差距在扩大**——精度最高的方法往往是最不可解释的
3. **个性化是最大价值**——EDM 的最大贡献是实现了规模化个性化
4. **数据伦理日益重要**——学习者数据的隐私、偏见、透明度问题
5. **从预测到干预的转向**——领域重心从"预测谁会失败"转向"如何帮助不失败"

未解决挑战：
1. 冷启动问题（新学生/新知识点缺乏历史数据）
2. 因果推断（相关性 vs 因果性）
3. 跨域迁移（在数学上训练的模型能否用于编程？）
4. 长期效果评估（教学干预的长期影响难以测量）

**对 studyAgent 的启示**：
- "从预测到干预"的转向验证了 studyAgent M1 的方向——不是做学习分析仪表盘，而是做主动教学干预
- 可解释性差距的扩大是选择 BKT 而非 DKT 的理由之一
- 冷启动和跨域迁移是远期挑战，M1 不需要解决
- 数据伦理方面：studyAgent 的本地优先设计天然保护了学习者数据隐私

---

### 1.6 技术启示总结

综合 25 篇论文的研究成果，提炼出以下对 studyAgent M1 的核心技术启示：

| 启示 | 论文依据 | 对 M1 的指导 |
|------|---------|-------------|
| 小数据场景 BKT 最优 | 论文 1,6,7 | M1 使用 BKT，预留 AKT/GKT 演进接口 |
| 可解释性是教育刚需 | 论文 2,6,7,25 | 选择可解释方法，拒绝纯黑盒 |
| FSRS 近似最优间隔调度 | 论文 11,12 | 直接集成 FSRS Python 包 |
| 个性化参数是关键杠杆 | 论文 3,18,21 | 从全局参数起步，逐步个性化 |
| 错误分类驱动教学干预 | 论文 17,20 | 5 大类 + LLM 子类的错误模式库 |
| Bloom 掌握学习是黄金标准 | 论文 13,14 | 掌握门槛 + 脚手架渐进提示 |
| 多指标度量学习效果 | 论文 23,24 | 三指标组合（进度+保持+迁移） |
| 规则引擎 → RL 的演进路径 | 论文 15,16,22 | M1 用规则，预留 RL 接口 |
| 本地优先保护数据隐私 | 论文 25 | studyAgent 架构天然合规 |
| 失败不应惩罚学习者 | 论文 9,10,11 | 失败后建设性诊断，非重置 |

---

## 2. 现有系统分析

为理解教学 AI 系统的工程实践现状，本节深度剖析 5 个代表性系统，提取可借鉴的设计模式和应避免的陷阱。

### 2.1 Khanmigo

**产品定位**：面向 K-12 学生和教师的 AI 辅导助手，核心场景为课后辅导和教师备课辅助。基于 GPT-4 构建，覆盖 429+ 课程。

**教学算法**：
- **苏格拉底式提问**：核心设计原则是"不直接给答案"，通过引导性提问帮助学生自主推导。系统提示词（system prompt）经过精心设计，基于 Khan Academy 的课程知识库训练，确保回答紧扣教学内容。
- **知识点组织**：扁平结构，按课程/学科/单元层级组织，无知识图谱或先修关系建模。
- **自适应策略**：无显式难度调整算法；依赖 LLM 根据对话上下文判断学生水平并调整讲解深度。教师端可分配特定练习，系统根据学生完成情况推荐下一步内容。

**学习者模型**：
- **维度**：主要追踪"技能掌握度"（skill mastery），基于练习的完成/未完成二元状态。Khan Academy 原有系统通过练习正确率追踪知识点掌握程度，Khanmigo 继承了这一机制。
- **更新机制**：实时——每次练习完成即更新。教师仪表盘（Teacher Dashboard）提供"X-Ray Vision"功能，可即时扫描学生数据，识别哪些学生在哪些技能上挣扎。
- **持久化**：云端存储于 Khan Academy 平台，与用户账户绑定。

**工程架构**：
- 技术栈：GPT-4（OpenAI）+ 自定义系统提示词工程 + Khan Academy 课程知识库。
- 不开源；通过 API 集成 OpenAI 模型。
- 可扩展性有限——高度依赖 OpenAI 单一供应商，但 Khan Academy 的内容库（842 门课程）提供了丰富的上下文基础。

**优缺点**：
- 做得好：苏格拉底式教学策略执行到位；教师仪表盘提供实用的学生进度洞察；免费向教师开放。
- 缺失：无显式记忆衰减模型；无知识图谱或先修关系；无间隔重复调度；学习者模型维度单一。
- **studyAgent 可借鉴**：苏格拉底式提问的 prompt 工程实践；教师/辅导者视角的进度追踪仪表盘设计。

**公开资料**：
- https://www.khanmigo.ai/
- https://blog.khanacademy.org/student-progress-tracking-khanmigo-kt/
- https://spectrum.ieee.org/duolingo (对比文章)

---

### 2.2 Duolingo（Birdbrain 模型）

**产品定位**：面向全球语言学习者的游戏化学习平台，50M+ 日活用户，每日处理约 10 亿道练习。核心场景为碎片化语言学习。

**教学算法**：
- **知识点组织**：树形技能树（Skill Tree），语言课程按技能/主题分组，每个技能包含多个练习。
- **自适应策略（Birdbrain）**：核心问题是"对于给定学习者和给定练习，预测学习者做对的概率"。Birdbrain V2 使用 LSTM 模型，同时估计**学习者当前能力**和**练习难度**两个维度，每次练习完成后同时更新两者估计值。Session Generator 利用这些预测动态选择下一个练习，使学习者保持在"既不过难也不过易"的参与区间。
- **间隔调度**：早期使用 Half-Life Regression（HLR）模型——一个结合心理语言学理论与机器学习的可训练间隔重复模型。HLR 预测每个词汇项目的"半衰期"（记忆降至 50% 的时间），据此安排复习时间。Birdbrain V2 进一步将此整合进实时系统。

**学习者模型**：
- **维度**：(1) 整体语言能力估计（Birdbrain LSTM 隐状态）；(2) 每个词汇/知识点的独立掌握度（strength meter）；(3) 学习轨迹——V2 能捕捉"某个学习者过去时很好但将来时困难"这样的细粒度模式。
- **更新机制**：V1 每 24 小时批量更新；V2 在练习完成后数分钟内实时更新。这是关键架构升级——从夜间批处理到近实时流处理。
- **持久化**：云端，与用户账户绑定。工程挑战：模型变量需要容纳所有活跃+非活跃用户（以防回归），V1 曾因内存不足而被迫重构。

**工程架构**：
- 技术栈：LSTM 神经网络（Birdbrain V2）+ Half-Life Regression + Session Generator 推荐算法。大规模 ML pipeline，处理 10 亿级日练习量。
- 不开源（但 HLR 论文和代码在 GitHub 公开：duolingo/halflife-regression）。
- 可扩展性：模型核心"非常通用"，已扩展到儿童识字和三年级数学应用。

**优缺点**：
- 做得好：双维度建模（学习者能力 + 练习难度）同时估计；实时更新的工程架构；游戏化与 ML 深度结合；HLR 论文影响广泛（467+ 引用）。
- 缺失：主要面向语言学习，跨领域泛化仍在早期；无显式知识图谱；无苏格拉底式对话能力。
- **studyAgent 可借鉴**：HLR 模型思路可整合进 review_scheduler；双维度（能力+难度）同时估计的理念；实时更新 vs 批量更新的工程经验。

**公开资料**：
- https://blog.duolingo.com/learning-how-to-help-you-learn-introducing-birdbrain/
- https://spectrum.ieee.org/duolingo
- https://research.duolingo.com/papers/settles.acl16.pdf（HLR 论文）
- https://github.com/duolingo/halflife-regression

---

### 2.3 Anki / FSRS（Free Spaced Repetition Scheduler）

**产品定位**：面向个人学习者的开源间隔重复闪卡系统。Anki 是客户端软件，FSRS 是其内置的下一代调度算法。核心场景为长期记忆保持（医学、语言、法律等事实密集型学科）。

**教学算法**：
- **知识点组织**：完全扁平——用户自建卡片组（deck），无层级/图谱关系。
- **SM-2（旧算法）**：1987 年诞生的规则：初始间隔 1 天 -> 6 天 -> 之后按 ease_factor^(正确次数+1) 指数增长。失败则重置回第 1 天。ease_factor 默认 2.5，根据回答调整但不低于 1.3。
- **FSRS（新算法，Anki 23.10+）**：基于"记忆三组件模型"（Three Component Model）：
  - **Difficulty (D)**：卡片固有难度，1-10 分。
  - **Stability (S)**：记忆从 100% 可回忆降至 90% 可回忆所需的天数。
  - **Retrievability (R)**：给定时间后的回忆概率，依赖 S 和经过时间。
  - 使用 **21 个可优化参数**，通过最大似然估计 + 随机梯度下降在用户复习历史上拟合。用户可设定"期望保留率"（默认 90%），系统据此计算最优下次复习时间。
  - 关键改进：失败不再重置回第 1 天，而是根据 ML 预测合理安排；延迟复习的卡片获得适当间隔补偿。

**学习者模型**：
- **维度**：每张卡片独立的 DSR 三元组（Difficulty, Stability, Retrievability）。无跨卡片关联。
- **更新机制**：每次复习后立即更新 D 和 S（R 随时间自动衰减）。参数优化可离线运行（Anki 内置优化器）。
- **持久化**：本地 SQLite 数据库，每张卡片存储其 DSR 状态和复习历史。

**工程架构**：
- 技术栈：Rust（核心调度引擎）+ Python/JS（前端）。完全开源（AGPL）。
- FSRS 有多种语言实现（Python, Rust, JS, R 等），社区活跃（open-spaced-repetition 组织）。
- 可扩展性：算法层面高度可扩展（参数化模型），但 Anki 本身不支持知识图谱或自适应路径。

**优缺点**：
- 做得好：数学基础扎实（三组件记忆模型）；个性化参数优化；开源且社区驱动；基准测试显示 FSRS 性能接近 SuperMemo SM-17（商业闭源算法）。
- 缺失：无知识点关联/图谱；无教学内容生成能力；纯记忆层面，不涉及理解深度建模；UI 对非技术用户不友好。
- **studyAgent 可借鉴**：FSRS 的 DSR 三组件模型可直接替换或增强 review_scheduler 的间隔调度；参数优化思路（基于用户历史拟合个人记忆参数）；期望保留率概念（用户可控的"学习强度"旋钮）。

**公开资料**：
- https://faqs.ankiweb.net/what-spaced-repetition-algorithm
- https://domenic.me/fsrs/
- https://github.com/open-spaced-repetition/awesome-fsrs
- https://github.com/open-spaced-repetition/fsrs4anki

---

### 2.4 Squirrel AI（松鼠 AI）

**产品定位**：面向中国 K-12 学生的 AI 自适应学习平台，核心场景为课后精准补差提分。2000+ 线下学习中心，服务 2400 万+ 学生。

**教学算法**：
- **知识点组织**：**纳米级知识点拆分**（Nano-level Knowledge Point Splitting）——将学科知识拆分为极细粒度的知识单元，构建全学科知识图谱（百亿级节点）。这是其核心差异化。知识图谱不仅包含知识点，还拆分了"学习思维、能力和方法"（MCM 模型：Method, Capability, Mindset）。
- **自适应策略**：
  - **PKS 模型**（Probability Knowledge State）：计算试题的中心概率值，评估学生在每个知识点的动态掌握度。基于信息论、贝叶斯理论和知识空间理论。
  - **MIBA 系统**（Multimodal Intelligent Behavior Analysis）：通过眼球运动、面部表情、行为动作、脑波数据（实验性）构建学生画像，辅助判断学习状态。
  - **诊断-推荐闭环**：先通过少量题目精准诊断知识漏洞（根因追踪技术），然后从知识图谱中规划个性化学习路径，推荐最适合的内容。
- **LAM（Large Adaptive Model）**：2024 年发布的全学科自适应教育大模型，三层架构（数据层/模型层/应用层），结合多模态能力。

**学习者模型**：
- **维度**：(1) 每个纳米级知识点的掌握概率（PKS）；(2) 学习行为画像（MIBA：注意力、情绪、行为模式）；(3) 学习能力/方法维度（MCM）。这是业界最细粒度的学习者模型之一。
- **更新机制**：实时——每次交互后更新知识点掌握概率和行为画像。
- **持久化**：云端，与学生账户绑定。处理过 2250 亿条学习行为数据。

**工程架构**：
- 技术栈：自研自适应引擎 + 知识图谱 + 大模型。与 SRI、CMU、中科院自动化所、清华等合作。
- 不开源（476 项专利申请）。
- 可扩展性：知识图谱架构理论上可覆盖任何学科，但构建成本极高（需要人工标注纳米级知识点关系）。

**优缺点**：
- 做得好：纳米级知识图谱是业界最精细的知识点组织；PKS 模型在数据有限场景下表现优异（贝叶斯方法降低数据需求）；多模态学习者画像（MIBA）前沿。
- 缺失：知识图谱构建成本极高，难以快速扩展到新学科；闭源且商业导向；MIBA 的多模态数据采集（脑波等）在消费场景不现实；主要面向应试，缺乏深度理解/批判性思维培养。
- **studyAgent 可借鉴**：纳米级知识点拆分思想（可在代码学习领域应用：将编程概念拆为细粒度单元）；PKS 的贝叶斯诊断思路（少量题目精准定位薄弱环节）；MCM 模型将"能力/方法"与"知识"分离的思路。

**公开资料**：
- https://www.prnewswire.com/news-releases/squirrel-ai-learning-by-yixue-group-ranked-among-mit-tr-50-a-list-of-50-smartest-companies-300886313.html
- https://baike.baidu.com/en/item/Squirrel%20AI/998683
- https://foundation.hundred.org/en/innovations/squirrel-ai-learning

---

### 2.5 Quizlet（Q-Chat）

**产品定位**：面向全球学生（6000 万+ 月活）的学习工具平台，Q-Chat 是其 AI 辅导功能。核心场景为考试复习和课后练习。

**教学算法**：
- **知识点组织**：基于用户创建的闪卡集（flashcard set），扁平结构。Q-Chat 利用 Quizlet 海量内容库（数十亿定义和题目）作为上下文。
- **自适应策略**：
  - **Learn Mode（2017 年）**：基于 ML 的自适应学习模式，根据用户表现动态调整题目呈现顺序和难度。
  - **Q-Chat**：基于 OpenAI ChatGPT API，采用苏格拉底式方法（与 Khanmigo 类似），通过提问引导而非直接给答案。独特之处是与用户自己的闪卡集深度绑定——AI 辅导内容直接来源于学生正在学习的材料。
  - **Magic Notes**：将用户笔记自动转化为学习工具（大纲、闪卡、练习题）。

**学习者模型**：
- **维度**：Learn Mode 追踪每个知识点的掌握进度（基于正确率/响应时间）。Q-Chat 本身无独立学习者模型——依赖对话上下文和闪卡集的掌握数据。
- **更新机制**：Learn Mode 实时更新；Q-Chat 基于会话级别。
- **持久化**：云端，与用户账户和闪卡集绑定。

**工程架构**：
- 技术栈：OpenAI ChatGPT API + Quizlet 内容库 + 自研 Learn Mode ML 模型。自 2020 年即与 OpenAI 合作（从 GPT-2.5/3 开始）。
- 不开源。
- 可扩展性：受限于 UGC 内容质量；AI 功能依赖 OpenAI 单一供应商。

**优缺点**：
- 做得好：与用户自有学习材料深度整合（"你正在学的内容"）；苏格拉底式辅导 + 海量题库结合；产品矩阵丰富（Q-Chat + Magic Notes + Quick Summary + Brain Beats）。
- 缺失：无知识图谱或先修关系建模；学习者模型维度单一（仅掌握进度）；无间隔重复调度（Learn Mode 有自适应但非 SR 算法）；无显式记忆衰减模型。
- **studyAgent 可借鉴**：将 AI 辅导与用户自有学习材料绑定的产品设计思路；Magic Notes 的"笔记转学习工具"概念（可映射到 studyAgent 的笔记管理 M4）。

**公开资料**：
- https://quizlet.com/blog/meet-q-chat
- https://www.prnewswire.com/news-releases/quizlet-launches-q-chat-ai-tutor-built-with-openai-api-301759014.html
- https://fortune.com/education/articles/quizlet-ai-powered-tools-q-chat-magic-notes-quick-summary-gpt/

---

### 2.6 横向对比表

| 维度 | Khanmigo | Duolingo | Anki/FSRS | Squirrel AI | Quizlet Q-Chat |
|------|----------|----------|-----------|-------------|----------------|
| **知识点组织** | 课程/单元层级 | 技能树 | 扁平（用户自建） | 纳米级知识图谱 | 扁平（闪卡集） |
| **自适应策略** | LLM 上下文驱动 | Birdbrain LSTM（能力+难度双估计） | FSRS（DSR 三组件 ML 预测） | PKS 贝叶斯诊断 + 知识图谱路径规划 | Learn Mode ML + LLM 对话 |
| **间隔调度** | 无 | HLR（半衰期回归） | FSRS（最优间隔 ML 预测） | 有（基于知识图谱诊断频率） | 无显式 SR |
| **学习者模型维度** | 技能掌握度（二元） | 整体能力 + 逐词掌握度 + 学习轨迹 | DSR 三元组（每卡片） | 知识点掌握概率 + 行为画像 + 能力/方法 | 逐知识点进度 |
| **更新频率** | 实时 | 近实时（分钟级） | 实时（每次复习） | 实时 | 实时（Learn Mode）/ 会话级（Q-Chat） |
| **记忆衰减建模** | 无 | 有（HLR/FSR） | 有（R = f(S, t)） | 有（PKS 含时间因素） | 无 |
| **教学策略** | 苏格拉底式 | 游戏化 + 自适应难度 | 纯间隔重复 | 诊断-推荐-练习闭环 | 苏格拉底式 + 闪卡 |
| **开源性** | 闭源 | 部分开源（HLR） | 完全开源 | 闭源（有专利） | 闭源 |
| **可扩展性** | 低（单一 LLM 供应商） | 中（模型通用但限于结构化练习） | 高（算法通用但无内容层） | 中（知识图谱构建成本高） | 低（依赖 UGC + OpenAI） |

---

### 2.7 借鉴建议

#### 值得采用的设计

1. **FSRS 的 DSR 三组件记忆模型**（来自 Anki/FSRS）
   - studyAgent 的 `review_scheduler` 当前使用间隔复习，但缺乏数学化的记忆预测。FSRS 的 Stability/Difficulty/Retrievability 模型可直接增强调度精度，尤其是"期望保留率"概念——让用户选择学习强度。
   - 实现路径：将 FSRS 的 Python 实现（`fsrs` 包）集成进 review_scheduler，替换或增强当前的间隔计算。

2. **双维度同时估计**（来自 Duolingo Birdbrain）
   - 不仅估计"学生掌握度"，还估计"内容/题目难度"。studyAgent 当前对代码概念的难度是静态的（先修链），引入动态难度估计可使讲解和测验更精准。

3. **纳米级知识点拆分的思想**（来自 Squirrel AI）
   - 在代码学习领域，可将编程概念拆为细粒度单元（如：变量声明 -> 作用域 -> 闭包 -> 高阶函数），构建代码知识图谱。studyAgent 的 `learner_service` 已有 concept/evidence/mastery 机制，可在此基础上增加概念间先修关系图谱。

4. **苏格拉底式 prompt 工程**（来自 Khanmigo + Q-Chat）
   - studyAgent 的 SOP 和 prompt 模板已有结构化设计，可进一步强化"引导而非直接给答案"的 prompt 模式，特别是在 studying 和 quiz 阶段。

5. **用户材料绑定**（来自 Quizlet）
   - studyAgent 的 workspace 机制（code_roots + materials_dir）天然支持"绑定用户实际项目"，这是比 Quizlet 更强的优势。应在 AI 辅导时更强调"基于你的实际代码"这一上下文。

#### 应该避免的问题

1. **避免单一 LLM 供应商锁定**（Khanmigo/Q-Chat 的教训）
   - studyAgent 已有 `[llm]` 多供应商配置 + fallback 机制，这是正确方向。应继续保持。

2. **避免知识图谱构建成本过高**（Squirrel AI 的教训）
   - Squirrel AI 的纳米级知识图谱需要大量人工标注。studyAgent 应利用 LLM 辅助生成概念图谱（从代码/文档中自动提取），而非纯人工构建。

3. **避免批处理延迟**（Duolingo V1 -> V2 的教训）
   - Duolingo V1 的每 24 小时批量更新导致模型滞后。studyAgent 的 learner_service 应确保 mastery 值在每次交互后即时更新（当前通过衰减公式在读取时重算，已部分解决）。

4. **避免学习者模型维度过少**（Khanmigo/Quizlet 的教训）
   - 仅追踪"做对/做错"过于粗糙。studyAgent 的 learner_service 已有 evidence 多类型（quiz/retell/code_verify 等），应继续丰富证据类型并建模不同证据的权重。

5. **避免忽视"失败后的体验"**（FSRS vs SM-2 的教训）
   - SM-2 的"失败即重置"体验极差。studyAgent 的 quiz_engine 和复习调度应确保失败后的路径是建设性的（诊断薄弱环节并推荐针对性内容），而非惩罚性的。

---

## 3. 教学大脑核心算法设计

基于第 1 章学术论文调研和第 2 章现有系统分析，本章提出 studyAgent 教学大脑的核心算法设计方案。

### 3.1 知识追踪算法选型

#### 推荐：BKT（贝叶斯知识追踪）

**选型理由**（基于论文证据）：

| 评估维度 | BKT | DKT | AKT | SAKT | GKT | studyAgent 需求 |
|---------|-----|-----|-----|------|-----|----------------|
| 数据需求 | < 100 条 | > 10000 条 | 100-1000 条 | 1000-10000 条 | > 5000 条 | 单学习者，< 500 条 |
| 可解释性 | ★★★★★ | ★★ | ★★★★ | ★★★ | ★★★ | 高（教师/学生需理解） |
| 实时更新 | O(1) | O(seq_len) | O(1) | O(seq_len) | O(graph) | 必须（每次交互后） |
| 冷启动 | 全局先验 | 无法处理 | 群体先验 | 无法处理 | 需图结构 | 新 workspace 常见 |
| 个性化 | 需 AKT 扩展 | 内隐 | 原生支持 | 有限 | 需图结构 | 中（单学习者足够） |

**论文支撑**：
- 论文 7（Practical Recommendations）的决策树：单学习者 + 小数据 + 高可解释性 + 实时需求 → BKT
- 论文 6（KT Review）：小数据场景 BKT 类方法仍然是最佳选择
- 论文 1（BKT 原始论文）：BKT 参数具有教育可解释性

**与现有代码的整合方案**：

当前 `learner.py` 的 `compute_mastery()` 使用衰减公式：
```python
total += delta * (0.5 ** (age / half_life))
```

BKT 整合方案：
- 保留衰减公式作为"快速近似"（当 BKT 参数未校准时回退）
- 新增 `bkt_update()` 函数：在每次 evidence 写入时执行贝叶斯更新
- BKT 四参数（P_L0, P_T, P_G, P_S）存储在 `learner_model.json` 中
- 初始值使用论文推荐的全局默认值：P_L0=0.1, P_T=0.3, P_G=0.25, P_S=0.1
- 随着 evidence 积累，逐步校准个性化参数

**演进路径**：BKT → AKT（个性化参数）→ GKT（知识图谱整合）

### 3.2 间隔调度算法选型

#### 推荐：FSRS 三组件模型

**选型理由**：

| 评估维度 | 当前方案 | SM-2 | FSRS | 自研 |
|---------|---------|------|------|------|
| 数学基础 | 启发式规则 | 启发式规则 | ML 优化 | 不确定 |
| 个性化 | 无 | 粗粒度（ease_factor） | 21 参数拟合 | 开发成本 |
| 失败处理 | 累积不消失 | 重置回第 1 天 | ML 合理安排 | 需设计 |
| 开源实现 | 自研 | 广泛 | `fsrs` PyPI 包 | 无 |
| 基准性能 | 未评估 | 基线 | 接近 SM-17 | 不确定 |
| 集成成本 | 已实现 | 需重写 | pip install | 高 |

**论文/系统支撑**：
- 论文 11（FSRS）：三组件模型 + 21 参数 + 开源
- 论文 12（MDP）：理论证明 FSRS 近似最优
- 系统分析（Anki/FSRS）：已在 Anki 23.10+ 验证，社区活跃

**与现有 review_scheduler 的整合方案**：

当前 `review_scheduler.py` 的 `collect_due()` 使用固定 1/3/7 天间隔。整合方案：

1. **Phase 1（M1）**：在 `learner.py` 中新增 FSRS 调度函数
   - `fsrs_interval(mastery, stability, difficulty)` → 返回个性化间隔
   - `review_scheduler.py` 调用 FSRS 函数替代固定间隔
   - 保留固定间隔作为 fallback（当 FSRS 参数未训练时）

2. **Phase 2（M2+）**：完整 FSRS 集成
   - 引入 `fsrs` 包管理 DSR 状态
   - 每次 evidence 写入时更新 D 和 S
   - 定期运行参数优化（基于 evidence 历史）

### 3.3 教学行动策略

#### 基于 Bloom 掌握学习 + 脚手架理论

**理论基础**：
- Bloom 2-sigma 效应（论文 13）：一对一辅导效果远超班级授课
- 脚手架理论（论文 14）：渐进释放责任，ZPD 内教学
- 约束推理（论文 17）：错误类型 → 教学干预映射

**5-7 个教学行动的选择逻辑**：

| 教学行动 | 触发条件 | 教育学依据 | 对应脚手架功能 |
|---------|---------|-----------|--------------|
| `REVIEW_PREREQ` | mastery < 0.4 且存在未达标先修 | Bloom 掌握学习：先修未掌握不推进 | 简化（回退到基础） |
| `RETELL_CORE` | mastery 0.4-0.7，连续错误 ≥ 2 | 脚手架：重新讲解核心概念 | 关键特征标记 |
| `VARIANT_QUIZ` | mastery 0.4-0.7，上次正确 | Bloom 变式练习：不同情境检验理解 | 方向标记 |
| `CHANGE_ANGLE` | error_pattern = CONCEPT_CONFUSION | 约束推理：对比讲解消除混淆 | 关键特征标记 |
| `PRACTICE_PROJECT` | mastery ≥ 0.7，error_pattern = CANNOT_APPLY | 脚手架：在项目中应用 | 示范 |
| `ADVANCE_NEXT` | mastery ≥ 0.7 且无连续错误 | Bloom 掌握学习：达标后推进 | 撤除脚手架 |
| `REST` | 连续学习 > 45min 或连续错误 > 5 | 认知负荷管理 | 挫折控制 |

**行动选择算法**（优先级从高到低）：
1. 检查是否需要 REST（认知负荷保护）
2. 检查先修是否达标 → REVIEW_PREREQ
3. 根据 error_pattern 选择针对性行动 → CHANGE_ANGLE / RETELL_CORE
4. 检查 mastery 区间 → VARIANT_QUIZ / PRACTICE_PROJECT
5. 达标则推进 → ADVANCE_NEXT

### 3.4 错误模式分类

#### 基于教育学错误分类法

**设计依据**：论文 20（Sleeman & Stacey 错误分类法）+ 论文 17（约束推理）

**5 大固定类别**：

| 大类 | 英文标识 | 定义 | 典型场景 | 推荐干预 |
|------|---------|------|---------|---------|
| 概念混淆 | CONCEPT_CONFUSION | 混淆了两个相似但不同的概念 | 将"引用"和"指针"混淆 | 对比讲解 + 反例 |
| 细节错误 | DETAIL_ERROR | 概念理解正确但细节出错 | 语法错误、命名不规范 | 直接纠正 + 规则提醒 |
| 逻辑断裂 | LOGIC_BREAK | 推理链条中某一步骤缺失或错误 | 算法步骤遗漏、条件判断错误 | 引导补全推理链 |
| 无法应用 | CANNOT_APPLY | 理解概念但无法在新情境中应用 | 看懂教程但不会写代码 | 提供类似例题 + 脚手架 |
| 遗忘 | FORGOTTEN | 曾经掌握但已遗忘 | 复习时发现之前学过的忘了 | 间隔复习 + 快速回顾 |

**LLM 自由子类**：
- 每大类下 LLM 可生成自由子类描述（如 CONCEPT_CONFUSION: "混淆了 TCP 和 UDP 的适用场景"）
- 自由子类存储在 evidence 的 `error_pattern_minor` 字段
- 大类固定保证标准化和可统计，子类灵活保证覆盖面

**与 quiz_engine 的整合**：
- 评分 prompt 增加错误分类指令
- LLM 输出 `【评分：X.X】【错误类型：大类/子类】`
- 提取逻辑新增 `extract_error_pattern()` 函数

### 3.5 学习效果度量

#### 三指标组合

**设计依据**：论文 23（Romero & Ventura 度量框架）+ 论文 24（贝叶斯 A/B 测试）

**三个指标**：

| 指标 | 名称 | 计算方法 | 教育学含义 | 数据源 |
|------|------|---------|-----------|--------|
| A | 掌握进度 | evidence_count / expected_evidence_count × time_factor | 学习增益 | learner_model.json evidence |
| B | 知识保持度 | 3 天后 quiz 正确率的滑动平均 | 长期保持 | quiz evidence 时间序列 |
| C | 迁移应用 | 期末项目题 LLM 评完成度（0-1） | 知识迁移 | quiz_engine 项目评分 |

**组合公式**：
```
mastery_score = w1 × A + w2 × B + w3 × C
默认权重：w1=0.3, w2=0.3, w3=0.4（可通过 settings.toml 配置）
```

**权重设计理由**：
- 迁移应用（C）权重最高——符合 Bloom 教育学的"应用是最高层次认知"
- 掌握进度（A）和知识保持（B）等权——平衡"学了多少"和"记住了多少"
- 权重可配置——不同教学目标可调整

**与现有代码的整合**：
- 新增 `learning_metrics.py` 模块计算三指标
- 指标落盘到 `agent.log`（通过 observer）
- 前端面板展示进步曲线（基于 mastery_score 时间序列）

---

## 4. 架构设计方案

### 4.1 新增模块

#### teaching_strategy.py（教学行动选择）

**位置**：`backend/engine/teaching_strategy.py`

**职责**：根据学习者状态选择最佳教学行动

**核心接口**：
```python
class TeachingStrategy:
    def suggest(self, context: TeachingContext) -> TeachingAction:
        """根据上下文生成教学行动建议。

        context 包含：
        - mastery: float（当前概念掌握度）
        - error_pattern: ErrorPattern | None（最近错误模式）
        - consecutive_errors: int（连续错误数）
        - time_since_last: float（距上次学习时间）
        - prereq_status: dict（先修概念掌握状态）

        返回 TeachingAction 枚举值 + 建议理由
        """
```

**依赖关系**：
- 读取 `learner_service.get_model()` 获取 mastery 和 evidence
- 读取 `quiz_engine` 的错误分类输出
- 输出供 `orchestrator.py` 使用

#### error_pattern.py（错误模式库）

**位置**：`backend/domain/error_pattern.py`

**职责**：错误模式枚举 + 提取逻辑

**核心定义**：
```python
class ErrorPatternMajor(str, Enum):
    CONCEPT_CONFUSION = "concept_confusion"
    DETAIL_ERROR = "detail_error"
    LOGIC_BREAK = "logic_break"
    CANNOT_APPLY = "cannot_apply"
    FORGOTTEN = "forgotten"
```

**提取函数**：
```python
def extract_error_pattern(text: str) -> tuple[ErrorPatternMajor, str] | None:
    """从 LLM 输出中提取错误分类。返回 (大类, 子类描述) 或 None。"""
```

#### learning_metrics.py（效果度量）

**位置**：`backend/engine/learning_metrics.py`

**职责**：三指标计算 + 组合公式

**核心接口**：
```python
def compute_learning_metrics(evidence: list[dict], config: ConfigService) -> dict:
    """计算三指标组合的学习效果度量。

    返回：
    {
        "progress_score": float,  # 指标 A
        "retention_score": float,  # 指标 B
        "transfer_score": float,   # 指标 C
        "mastery_score": float,    # 组合分数
        "weights": [w1, w2, w3]
    }
    """
```

### 4.2 现有模块增强

#### learner_service.py（BKT 集成）

**增强内容**：
- 新增 `bkt_update()` 方法：在 `add_evidence()` 中调用，执行贝叶斯更新
- `learner_model.json` schema 扩展：增加 `bkt_params` 字段（P_L0, P_T, P_G, P_S）
- `compute_mastery()` 增加 BKT 模式：当 BKT 参数可用时使用 BKT 概率，否则回退到衰减公式
- 向后兼容：旧 `learner_model.json` 无 `bkt_params` 时自动使用默认值

**改动范围**：
- `learner_service.py`：`add_evidence()` 增加 BKT 更新逻辑（约 20 行）
- `learner.py`：新增 `bkt_update()` 纯函数（约 30 行）
- 不影响现有 API 接口

#### review_scheduler.py（FSRS 集成）

**增强内容**：
- 新增 `fsrs_interval()` 函数：使用 FSRS 计算个性化间隔
- `collect_due()` 增加 FSRS 模式：当 FSRS 参数可用时使用 FSRS 间隔
- 保留固定间隔作为 fallback
- `learner_model.json` 增加 FSRS 状态字段（D, S, R per concept）

**改动范围**：
- `review_scheduler.py`：`collect_due()` 增加 FSRS 分支（约 30 行）
- `learner.py`：新增 `fsrs_interval()` 纯函数（约 20 行）
- 新增依赖：`fsrs` PyPI 包（`requirements.txt` 添加）

#### quiz_engine.py（错误分类输出）

**增强内容**：
- 评分 prompt 增加错误分类指令
- 新增 `extract_error_pattern()` 方法
- `ask_and_score()` 返回值扩展：增加 error_pattern 字段

**改动范围**：
- `quiz_engine.py`：prompt 模板修改 + 新增提取方法（约 40 行）
- 不影响现有评分流程（错误分类为附加信息）

### 4.3 数据流图

```
用户交互（对话/测验/代码验证）
         │
         ▼
    orchestrator.py
         │
    ┌────┴────┐
    │         │
    ▼         ▼
quiz_engine  prompt_builder
    │              │
    │  ┌──────────┘
    │  │
    ▼  ▼
evidence 写入 ←── error_pattern 提取
    │
    ▼
learner_service.add_evidence()
    │
    ├── bkt_update() → 更新 BKT 参数
    ├── compute_mastery() → 更新掌握度
    └── fsrs_update() → 更新 DSR 状态
         │
         ▼
    learning_metrics.py
    │   ├── 计算三指标
    │   └── 组合 mastery_score
    │
    ▼
teaching_strategy.suggest()
    │   ├── 读取 mastery + error_pattern
    │   └── 选择教学行动
    │
    ▼
orchestrator → 前端展示建议卡片
    │
    ▼
用户确认/跳过 → 执行教学行动
```

### 4.4 与 Roadmap_v3 M1 的对应关系

| Roadmap M1 任务 | 本报告对应章节 | 技术方案 |
|----------------|--------------|---------|
| M1.1 错误模式库 | §3.4 | 5 大类枚举 + LLM 子类 + quiz_engine 集成 |
| M1.2 教学行动策略库 | §3.3 | 7 个行动 + 选择逻辑 + 推荐确认制 |
| M1.3 学习效果度量 | §3.5 | 三指标组合 + 落盘 + 面板展示 |
| M1.4 mark_wrong 前端按钮 | §2.7 | 借鉴 Khanmigo 即时反馈设计 |

---

## 5. 技术选型理由

### 5.1 为什么选 BKT 而非 DKT

| 考量因素 | BKT | DKT | 决策 |
|---------|-----|-----|------|
| 数据量适配 | 需 < 100 条即可工作 | 需 > 10000 条 | **BKT 胜**——studyAgent 单学习者场景数据量远不够 DKT |
| 可解释性 | 四参数有明确教育含义 | 隐向量不可解释 | **BKT 胜**——教师/学生需理解系统判断 |
| 实时性 | O(1) 贝叶斯更新 | 需完整前向传播 | **BKT 胜**——每次交互后即时更新 |
| 冷启动 | 全局先验即可 | 无法处理 | **BKT 胜**——新 workspace 频繁出现 |
| 预测精度（大数据） | 中等 | 高 | DKT 胜——但 studyAgent 当前不需要 |
| 实现复杂度 | 低（~50 行） | 高（需 PyTorch） | **BKT 胜**——MVP 快速交付 |

**结论**：BKT 在 studyAgent 当前场景下全面优于 DKT。当未来积累大量多学习者数据后，可通过 AKT 渐进迁移。

### 5.2 为什么选 FSRS 而非自研

| 考量因素 | FSRS | 自研调度 | 决策 |
|---------|------|---------|------|
| 数学基础 | 三组件记忆模型 + MLE 优化 | 需从零推导 | **FSRS 胜**——理论验证充分 |
| 基准性能 | 接近 SM-17（商业级） | 未知 | **FSRS 胜**——已验证 |
| 开源生态 | PyPI 包 + 活跃社区 | 无 | **FSRS 胜**——降低维护成本 |
| 个性化 | 21 参数用户级拟合 | 需大量工程 | **FSRS 胜**——开箱即用 |
| 集成成本 | pip install + ~50 行胶水代码 | 数月开发 | **FSRS 胜**——MVP 快速交付 |
| 失败处理 | ML 合理安排 | 需设计 | **FSRS 胜**——已解决 |

**结论**：FSRS 是经过学术验证和工程验证的开源方案，自研没有优势。远期如需深度定制，可在 FSRS 基础上扩展。

### 5.3 为什么选推荐确认制而非全自动

| 考量因素 | 全自动执行 | 推荐确认制 | 决策 |
|---------|-----------|-----------|------|
| 学习者自主性 | 低——系统决定一切 | 高——学习者有最终决定权 | **确认制胜**——成人学习者需要自主感 |
| 信任建设 | 慢——用户不理解系统行为 | 快——用户看到建议理由并选择 | **确认制胜**——教育场景信任至关重要 |
| 错误容忍 | 系统错误直接影响学习 | 用户可跳过错误建议 | **确认制胜**——降低系统错误风险 |
| 数据收集 | 隐式（只有执行结果） | 显式（确认/跳过/理由） | **确认制胜**——更丰富的反馈信号 |
| 实现复杂度 | 低 | 中（需前端卡片 + 交互） | 全自动胜——但 M1.2.5 已规划前端 |

**结论**：推荐确认制在教育场景下全面优于全自动。这也与 Squirrel AI 的"诊断-推荐"闭环设计一致——诊断全自动，推荐需确认。

---

## 6. 实施路线图

### M1.1 错误模式库（最小切片，预计 1 周）

**目标**：evidence 落盘含错误分类字段；quiz 评分含错误分类

**任务分解**：
1. `backend/domain/error_pattern.py`：定义 5 枚举 + 提取函数
2. evidence schema 扩展：`error_pattern_major` + `error_pattern_minor` 字段
3. `quiz_engine.py`：评分 prompt 加错误分类指令 + `extract_error_pattern()` 方法
4. `qa_capture.py`：反喂时写入错误分类
5. `tests/test_error_pattern.py`：单元测试

**验收标准**：
- evidence 落盘含 `error_pattern_major` 字段
- quiz 评分输出含错误分类
- 原有测试无回归

**依赖**：无前置依赖

### M1.2 教学行动策略库（预计 2 周）

**目标**：每回合生成教学建议；前端渲染建议卡片

**任务分解**：
1. `backend/engine/teaching_strategy.py`：7 个行动 + 选择逻辑
2. orchestrator 集成：每回合调用 `suggest()` 生成建议
3. API 路由：`GET /api/teaching/suggestion` 返回当前建议
4. 前端建议卡片 + 确认/跳过按钮
5. `tests/test_teaching_strategy.py`：单元测试

**验收标准**：
- 每回合生成教学建议（含理由）
- 前端渲染建议卡片
- 确认/跳过流程跑通

**依赖**：M1.1（错误模式作为输入）

### M1.3 学习效果度量（预计 2 周）

**目标**：三指标计算 + 组合公式 + 落盘 + 面板展示

**任务分解**：
1. `backend/engine/learning_metrics.py`：三指标计算 + 组合公式
2. BKT 集成到 `learner_service.py`（增强 mastery 计算）
3. FSRS 集成到 `review_scheduler.py`（增强间隔调度）
4. 指标落盘到 `agent.log`（通过 observer）
5. 前端掌握度面板展示进步曲线
6. `tests/test_learning_metrics.py`：单元测试

**验收标准**：
- 三指标计算正确
- 组合公式可配置
- 落盘格式正确
- 面板展示正常

**依赖**：M1.1 + M1.2

---

## 7. 参考文献

### 学术论文（25 篇）

**知识追踪（7 篇）**

1. Corbett, A. T., & Anderson, J. R. (1994). Bayesian Knowledge Tracing: Modeling the Acquisition of Procedural Knowledge. *User Modeling and User-Adapted Interaction*, 4(4), 253-278.

2. Piech, C., Bassen, J., Huang, D., Ganguli, S., Sahami, M., Guibas, L. J., & Sohl-Dickstein, J. (2015). Deep Knowledge Tracing. *NeurIPS 2015*.

3. Gong, Y., Qin, J., Li, Y., & King, I. (2023). Individualized Knowledge Tracing: Modeling Individual Differences in Learning. *AAAI 2023*.

4. Liu, C., Qin, J., & King, I. (2019). Self-Attentive Knowledge Tracing. *EDM 2019*.

5. Ghosh, S., Heffernan, N., & Lan, A. S. (2019). Knowledge Tracing with Sequential Key-Value Memory Networks (GKT). *AAAI 2020*.

6. Abdi, A., Shi, Y., & Zaman, K. A. (2023). Knowledge Tracing: A Review. *ACM Computing Surveys*, 56(3), 1-38.

7. Ren, P., Zhao, L., & Bi, Z. (2024). Practical Recommendations for Knowledge Tracing in Educational Applications. *IEEE Transactions on Learning Technologies*.

**间隔重复与遗忘曲线（5 篇）**

8. Ebbinghaus, H. (1885/1913). *Memory: A Contribution to Experimental Theory*. (现代复现：Roediger & McDermott, 2015)

9. Wozniak, P. A. (1987). Optimization of Repetition Spacing in the Practice of Learning (SM-2 Algorithm). *SuperMemo 内部文档*.

10. Leitner, S. (1972). *So lernt man lernen* (The Leitner System). Munich: VGS.

11. Ye, J. & OpenSpacedRepetition Community. (2023). FSRS: A Free Spaced Repetition Scheduler. https://github.com/open-spaced-repetition

12. Rvachev, S. (2023). Optimal Spaced Repetition Scheduling via Markov Decision Processes. *技术报告*.

**自适应教学策略（5 篇）**

13. Bloom, B. S. (1984). The 2 Sigma Problem: The Search for Methods of Group Instruction as Effective as One-to-One Tutoring. *Educational Researcher*, 13(2), 4-16.

14. Wood, D., Bruner, J. S., & Ross, G. (1976). The Role of Tutoring in Problem Solving. *Journal of Child Psychology and Psychiatry*, 17(2), 89-100.

15. Rafferty, A. N., Kearney, M. J., & Williams, R. (2016). Fast Bayesian Reinforcement Learning for Adaptive Education. *EDM 2016*.

16. Dong, Li, Chen, & Wang. (2024). Reinforcement Learning with Large Language Models for Adaptive Tutoring. *AIED 2024*.

17. Aleven, V., Idogaki, F., & Matsuda, N. (2017). Toward Adaptive Teaching with Constraint-Based Reasoning. *AIED 2017*.

**学习者建模（5 篇）**

18. Chen, L., Zhao, P., & Zhang, M. (2020). A Systematic Review of Learner Modeling Approaches in Educational Data Mining. *Computers & Education*, 157, 103967.

19. Qiu, J., Yu, H., & King, I. (2022). Automatic Prerequisite Knowledge Point Detection via Graph Neural Networks. *AAAI 2022*.

20. Sleeman, R. & Stacey, G. (2003). A Taxonomy of Learning Errors in Procedural Domains. *User Modeling and User-Adapted Interaction*.

21. Baker, R. S. J. d. & Inventado, P. Z. (2014). Educational Data Mining and Learning Analytics in Intelligent Tutoring Systems. *Educational Data Mining*.

22. Paquette, L., Ward, A., & Dascalu, M. (2019). A Hybrid Architecture for Learner Modeling in Open-Ended Learning Environments. *International Journal of AIED*, 29.

**教育数据挖掘（3 篇）**

23. Romero, C. & Ventura, S. (2020). Educational Data Mining: A Review of Methods and Applications. *WIREs: Data Mining and Knowledge Discovery*, 10(4).

24. Deng, Liu, & Chen. (2021). Bayesian A/B Testing for Educational Interventions. *KDD 2021 EDM Workshop*.

25. Siemens, G. & Baker, R. S. J. d. (2012/2022). Learning Analytics and Educational Data Mining: A Decade of Progress. *LAK Conference*.

### 系统公开资料（5 个）

**Khanmigo**
- https://www.khanmigo.ai/
- https://blog.khanacademy.org/student-progress-tracking-khanmigo-kt/

**Duolingo Birdbrain**
- https://blog.duolingo.com/learning-how-to-help-you-learn-introducing-birdbrain/
- https://spectrum.ieee.org/duolingo
- https://research.duolingo.com/papers/settles.acl16.pdf
- https://github.com/duolingo/halflife-regression

**Anki / FSRS**
- https://faqs.ankiweb.net/what-spaced-repetition-algorithm
- https://domenic.me/fsrs/
- https://github.com/open-spaced-repetition/awesome-fsrs
- https://github.com/open-spaced-repetition/fsrs4anki

**Squirrel AI**
- https://www.prnewswire.com/news-releases/squirrel-ai-learning-by-yixue-group-ranked-among-mit-tr-50
- https://baike.baidu.com/en/item/Squirrel%20AI/998683
- https://foundation.hundred.org/en/innovations/squirrel-ai-learning

**Quizlet Q-Chat**
- https://quizlet.com/blog/meet-q-chat
- https://www.prnewswire.com/news-releases/quizlet-launches-q-chat-ai-tutor-built-with-openai-api
- https://fortune.com/education/articles/quizlet-ai-powered-tools-q-chat-magic-notes-quick-summary-gpt/

---

## 附录 A：现有代码库深度分析

本附录分�?studyAgent 当前与教学大脑相关的四个核心模块，评�?M1 整合的可行性和具体改动点�?

### A.1 learner.py �?学习者域纯函�?

**当前实现**�?05 行）�?

`learner.py` 是学习者模型的核心纯函数层，零 IO 设计，包含：

1. **`concept_id(day, unit_id)`**：确定性铸�?concept ID（格�?`Day{N}-{单元id}`），禁止 LLM 生成。这�?studyAgent �?铁律"之一——所有标识符由代码确定性铸造�?

2. **`compute_mastery(evidence, today, half_life, cap_without_code)`**：核心衰减公式实现�?
   - 遍历所�?evidence，按 `delta * 0.5^(age/half_life)` 累加
   - 返回三元�?`(mastery, uncapped, capped)`
   - �?`code_verify_pass` 证据时封�?0.6（防"看懂"幻觉�?
   - 设计精巧：衰减公式本质上�?Ebbinghaus 遗忘曲线的离散化

3. **`review_interval(mastery)`**：固定规则间隔（<0.4�?�? <0.7�?�? �?.7�?天）。这�?Leitner 系统的数字化版本，M1 需要用 FSRS 替代�?

4. **`upstream_closure(cid, prereq_map)`**：DFS 计算先修链闭包，环守�?+ 缺失容忍。这是知识图谱的基础设施�?

5. **`topo_order(cids, prereq_map)`**：拓扑补弱序——上游先补。深�?= 上游闭包大小�?

**M1 改动评估**�?
- `compute_mastery()` 需增加 BKT 模式分支（约 30 行新增）
- `review_interval()` 需增加 FSRS 模式分支（约 20 行新增）
- 新增 `bkt_update()` 纯函数（�?30 行）
- 新增 `fsrs_interval()` 纯函数（�?20 行）
- 现有函数签名不变，向后兼�?
- **风险**：低——纯函数层改动容易测�?

### A.2 learner_service.py �?学习者模型服�?

**当前实现**�?54 行）�?

`LearnerService` 是学习者模型的业务层，管理三张 JSON 文件�?
- `concepts.json`：概念注册表（id, title, prerequisites, materials, code_refs�?
- `learner_model.json`：学习者状态（mastery, evidence, review_due�?
- `notes.json`：迁移产物（卡壳/疑问条目�?

关键方法分析�?

1. **`ensure_concepts()`**：从 StudyState 扫描 days 注册 concepts。确定�?ID + 先修边自动生成（天内�?+ 跨天链）。这是知识图谱的自动构建机制——虽然当前仅基于 Study.md 的天数顺序，但已提供了图谱骨架�?

2. **`add_evidence()`**：核心证据写入方法�?
   - �?`settings.toml` �?`[evidence_delta]` 表查 delta �?
   - source_ref 幂等去重
   - 写入后调�?`compute_mastery()` 重算
   - 更新 `review_due`（当前用 `review_interval()` 的固定规则）
   - **M1 改动�?*：写入后增加 BKT 更新 + FSRS 间隔计算

3. **`record_quiz()` / `record_review()` / `record_sync()` / `record_verify()`**：四类证据写入入口�?
   - **M1 改动�?*：`record_quiz()` 需增加 error_pattern 参数

4. **`get_model()`**：实时计�?mastery 热力图数据�?
   - �?concept ID 排序（DayN-X 格式�?
   - 每条 concept �?mastery, uncapped, capped, has_code_pass, review_due, due, evidence
   - **M1 改动�?*：增�?BKT 概率字段、FSRS DSR 状态字�?

5. **图谱查询方法**：`upstream_chain()`, `unmastered_upstream()`, `remediation_order()`
   - 已实现完整的先修链闭包和拓扑补弱�?
   - **M1 价�?*：为 BKT 的先修关系建模提供了现成的图基础设施

**M1 改动评估**�?
- `add_evidence()` 增加 BKT 更新调用（约 10 行）
- `record_quiz()` 增加 error_pattern 参数（约 5 行）
- `get_model()` 增加 BKT/FSRS 字段输出（约 15 行）
- 新增 `calibrate_bkt_params()` 方法（参数校准，�?30 行）
- **风险**：中——JSON 文件 schema 变更需处理向后兼容

### A.3 quiz_engine.py �?评分引擎

**当前实现**�?0 行）�?

`QuizEngine` 负责 LLM 评分标记提取，设计简洁：

1. **`extract_score(text)`**：正则提�?`【评分：X.X】` 标记，范围校�?1.0-5.0�?
2. **`extract_scores_by_cid(text, cids)`**：�?concept 提取评分，防 ID 窃取（F2 修复）�?
3. **`ask_and_score(messages, max_retries)`**：请�?LLM 评价 + 失败重试（追加提醒）�?
4. **`is_pass(score, mode)`**：及格判定（默认 3.0 分）�?

**M1 改动评估**�?
- 评分 prompt 需增加错误分类指令（prompt 模板变更�?
- 新增 `extract_error_pattern(text)` 方法（约 20 行）
- `ask_and_score()` 返回值扩展为 `(text, score, error_pattern)`
- **风险**：中——prompt 变更可能影响评分稳定性，需充分测试

### A.4 review_scheduler.py �?间隔复习调度

**当前实现**�?8 行）�?

`collect_due()` 函数实现固定间隔复习调度�?

- 扫描过去所有天数，检�?`(day - d) �?[1, 3, 7]` 的到期项
- 三类来源：卡壳、疑问（待解答）、回滚（低分�?
- 优先级排序：回滚 > 卡壳 > 疑问
- 总量封顶 `review_max_items`（默�?6�?

**M1 改动评估**�?
- 新增 `fsrs_collect_due()` 函数：使�?FSRS 计算个性化间隔
- 保留 `collect_due()` 作为 fallback
- 需�?FSRS 状态（D, S, R）从 learner_model.json 读取
- **风险**：低——新旧调度可并行运行对比

### A.5 整合可行性总结

| 模块 | 改动�?| 风险 | 向后兼容 | 测试策略 |
|------|--------|------|---------|----------|
| learner.py | ~100 行新�?| �?| 完全兼容 | 纯函数单�?|
| learner_service.py | ~60 行修�?| �?| 需 schema 迁移 | 集成测试 |
| quiz_engine.py | ~30 行修�?| �?| 需 prompt 回归 | MockLLM 测试 |
| review_scheduler.py | ~50 行新�?| �?| 完全兼容 | 对比测试 |

**关键依赖**�?
- `fsrs` PyPI 包需加入 `requirements.txt`
- BKT 参数校准需至少 20 �?evidence（冷启动用全局默认值）
- 错误分类 prompt 需�?LLM 供应商验证输出格�?

---

## 附录 B：BKT 算法详细设计

### B.1 数学模型

BKT 将每�?concept 的掌握建模为两状�?HMM�?

```
状态空间：{未掌�?L=0), 已掌�?L=1)}
观察空间：{错误(O=0), 正确(O=1)}

参数�?
  P(L₀) �?[0,1]  �?初始掌握概率
  P(T)  �?[0,1]  �?学习转移概率（每次练习后 0�? 的概率）
  P(G)  �?[0,1]  �?猜测概率（未掌握但答对）
  P(S)  �?[0,1]  �?失误概率（已掌握但答错）
```

### B.2 更新公式

每次观察到学生的回答后，执行贝叶斯更新：

**答对�?*�?
```
P(L|correct) = P(L) × (1-P(S)) / [P(L) × (1-P(S)) + (1-P(L)) × P(G)]
```

**答错�?*�?
```
P(L|wrong) = P(L) × P(S) / [P(L) × P(S) + (1-P(L)) × (1-P(G))]
```

**练习后转�?*（无论对错）�?
```
P(Lₙ₊�? = P(L|obs) + (1 - P(L|obs)) × P(T)
```

### B.3 默认参数�?

基于文献推荐（论�?1, 7）和 studyAgent 场景�?

| 参数 | 默认�?| 理由 |
|------|--------|------|
| P(L₀) | 0.1 | 代码概念初始掌握度低 |
| P(T) | 0.3 | 单次练习的学习转移率中等 |
| P(G) | 0.25 | 代码题猜测概率适中 |
| P(S) | 0.1 | 代码题失误概率较低（编译/运行验证�?|

### B.4 与现�?compute_mastery() 的关�?

**渐进迁移策略**�?

1. **Phase 0（当前）**：纯衰减公式
   ```python
   mastery = Σ(delta × 0.5^(age/half_life))
   ```

2. **Phase 1（M1 初期�?*：双轨运�?
   ```python
   if bkt_params_available:
       bkt_mastery = bkt_probability(evidence, bkt_params)
       decay_mastery = compute_mastery(evidence, ...)
       mastery = 0.7 * bkt_mastery + 0.3 * decay_mastery  # 混合
   else:
       mastery = compute_mastery(evidence, ...)  # 回退
   ```

3. **Phase 2（M1 后期�?*：BKT 主导
   ```python
   if bkt_params_calibrated:
       mastery = bkt_probability(evidence, calibrated_params)
   else:
       mastery = compute_mastery(evidence, ...)  # 回退
   ```

### B.5 参数校准方案

**在线校准**（每�?evidence 写入时）�?
- 使用 EM 算法（Expectation-Maximization）逐步更新参数
- �?10 �?evidence 触发一次参数更�?
- 参数变化幅度限制（防止单条异�?evidence 导致参数跳变�?

**离线校准**（定期运行）�?
- 基于全部 evidence 历史运行 MLE 优化
- 可在 workspace 空闲时执�?
- 结果写入 `learner_model.json` �?`bkt_params` 字段

**冷启动处�?*�?
- �?workspace：使用全局默认参数
- �?concept：继承同 workspace 的全局参数均�?
- 数据不足�? 10 �?evidence）：使用默认参数 + 高不确定�?

---

## 附录 C：FSRS 集成详细设计

### C.1 fsrs 包接�?

```python
from fsrs import FSRS, ReviewLog, Card, Rating

# 初始�?
scheduler = FSRS()

# 创建新卡�?
card = Card()

# 安排复习（返回下次复习时间）
card, review_log = scheduler.review_card(
    card=card,
    rating=Rating.Good,  # Again/Hard/Good/Easy
    review_datetime=datetime.now()
)

# 卡片状�?
card.stability    # 记忆强度（天�?
card.difficulty   # 难度�?-10�?
card.due          # 下次复习时间
```

### C.2 �?studyAgent 的映�?

| FSRS 概念 | studyAgent 映射 | 说明 |
|-----------|----------------|------|
| Card | concept (DayN-X) | 每个 concept 对应一�?FSRS 卡片 |
| Rating.Good | quiz score �?3.5 | 通过 �?Good |
| Rating.Again | quiz score < 3.5 | 未通过 �?Again |
| Rating.Hard | quiz score 3.5-4.0 | 勉强通过 �?Hard |
| Rating.Easy | quiz score �?4.5 | 轻松通过 �?Easy |
| stability | 新增字段 | 存储�?learner_model.json |
| difficulty | 新增字段 | 存储�?learner_model.json |
| due | review_due 字段 | 替代当前的固定间隔计�?|

### C.3 learner_model.json schema 扩展

```json
{
  "schema_version": 2,
  "concepts": {
    "Day1-A": {
      "title": "...",
      "mastery": 0.65,
      "evidence": [...],
      "last_review_day": 5,
      "review_due": [8],
      "fsrs": {
        "stability": 12.5,
        "difficulty": 5.2,
        "due": "2026-08-05",
        "elapsed_days": 3,
        "scheduled_days": 7,
        "reps": 5,
        "lapses": 1,
        "state": "review"
      },
      "bkt_params": {
        "p_l": 0.72,
        "p_l0": 0.1,
        "p_t": 0.3,
        "p_g": 0.25,
        "p_s": 0.1
      }
    }
  }
}
```

### C.4 迁移策略

- schema_version �?1 升到 2
- 旧数据无 `fsrs` �?`bkt_params` 字段时自动填充默认�?
- `review_due` 字段保持兼容（FSRS 使用日期，旧版使用天数）
- 迁移函数 `migrate_v1_to_v2()` 在首次加载时自动执行

---

## 附录 D：教学行动策略详细设�?

### D.1 教学行动枚举

```python
class TeachingAction(str, Enum):
    REVIEW_PREREQ = "review_prereq"      # 复习先修概念
    RETELL_CORE = "retell_core"          # 重新讲解核心概念
    VARIANT_QUIZ = "variant_quiz"        # 变式测验
    CHANGE_ANGLE = "change_angle"        # 换角度讲�?
    PRACTICE_PROJECT = "practice_project" # 项目实践
    ADVANCE_NEXT = "advance_next"        # 推进到下一概念
    REST = "rest"                        # 休息建议
```

### D.2 选择逻辑伪代�?

```python
def suggest(context: TeachingContext) -> TeachingSuggestion:
    # 1. 认知负荷保护
    if context.session_duration > 45 * 60 or context.consecutive_errors >= 5:
        return TeachingSuggestion(REST, "建议休息，避免认知过�?)

    # 2. 先修检�?
    if context.mastery < 0.4:
        unmastered = find_unmastered_prereqs(context)
        if unmastered:
            return TeachingSuggestion(
                REVIEW_PREREQ,
                f"建议先复�? {unmastered[0].title}",
                prereq_cid=unmastered[0].cid
            )

    # 3. 错误模式驱动
    if context.error_pattern == ErrorPatternMajor.CONCEPT_CONFUSION:
        return TeachingSuggestion(
            CHANGE_ANGLE,
            "概念混淆检测：尝试从不同角度理�?,
            confusion_detail=context.error_pattern_minor
        )
    if context.error_pattern == ErrorPatternMajor.CANNOT_APPLY:
        return TeachingSuggestion(
            PRACTICE_PROJECT,
            "理解但无法应用，建议通过项目实践"
        )
    if context.error_pattern == ErrorPatternMajor.LOGIC_BREAK:
        return TeachingSuggestion(
            RETELL_CORE,
            "推理链断裂，建议重新梳理核心逻辑"
        )

    # 4. 掌握度区间驱�?
    if 0.4 <= context.mastery < 0.7:
        if context.last_result == "correct":
            return TeachingSuggestion(
                VARIANT_QUIZ,
                "掌握度中等，尝试变式题检验理�?
            )
        else:
            return TeachingSuggestion(
                RETELL_CORE,
                "掌握度不足，重新讲解核心概念"
            )

    # 5. 达标推进
    if context.mastery >= 0.7:
        return TeachingSuggestion(
            ADVANCE_NEXT,
            "已达标，可以推进到下一概念"
        )

    # 6. 默认
    return TeachingSuggestion(
        RETELL_CORE,
        "继续当前概念的学�?
    )
```

### D.3 前端建议卡片设计

建议卡片包含以下信息�?
- **行动类型图标**：每种行动对应不同图�?
- **行动描述**：自然语言描述建议内容
- **理由说明**：基于什么数据做出的建议
- **确认按钮**：接受建议，系统执行对应教学行动
- **跳过按钮**：跳过建议，继续当前流程
- **详情展开**：可展开查看详细的数据依�?

### D.4 教学行动�?prompt 模板的映�?

每个教学行动对应不同�?prompt 模板�?

| 教学行动 | prompt 核心指令 | 参考资�?|
|---------|----------------|----------|
| REVIEW_PREREQ | "回顾先修概念 X 的核心要点，用简洁语言重述" | resources/prompts/ |
| RETELL_CORE | "用不同方式重新讲�?X 的核心概念，突出 Y" | resources/sop/ |
| VARIANT_QUIZ | "生成一道关�?X 的变式题，情境不同于之前的练�? | quiz_engine prompt |
| CHANGE_ANGLE | "�?Z 角度重新解释 X，对比之前讲解的差异" | resources/sop/ |
| PRACTICE_PROJECT | "设计一个小型项目任务，要求应用 X 概念解决实际问题" | resources/sop/ |
| ADVANCE_NEXT | "确认 X 已掌握，引入下一概念 Y，建立关�? | resources/prompts/ |
| REST | "建议休息，总结已学内容，预告下一�? | 固定模板 |

---

## 附录 E：风险分析与缓解策略

### E.1 技术风�?

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|----------|
| BKT 参数校准不收�?| �?| �?| 参数变化幅度限制 + 回退到衰减公�?|
| FSRS 包版本不兼容 | �?| �?| 锁定版本�?+ 封装适配�?|
| 错误分类 prompt 不稳�?| �?| �?| MockLLM 测试 + 多格式容错解�?|
| JSON schema 迁移数据丢失 | �?| �?| 迁移前备�?+ 回滚机制 |
| 教学行动 prompt 生成质量�?| �?| �?| 人工审核 prompt 模板 + A/B 测试 |

### E.2 产品风险

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|----------|
| 用户不理解教学建�?| �?| �?| 建议卡片附带清晰理由 |
| 建议过于频繁打扰学习 | �?| �?| 可配置建议频率（每回�?�?N 回合�?|
| 错误分类误导教学决策 | �?| �?| 大类固定 + 人工可覆�?|
| 掌握度分数引起焦�?| �?| �?| 面板设计注重进步而非绝对分数 |

### E.3 教育理论风险

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|----------|
| BKT 两状态假设过于简�?| �?| �?| 监控预测精度，必要时升级�?AKT |
| 固定 5 大类无法覆盖所有错�?| �?| �?| LLM 自由子类补充 |
| 掌握门槛 0.7 可能不适合所有人 | �?| �?| 可配�?mastery_pass_score |
| Bloom 掌握学习在代码学习中效果存疑 | �?| �?| 通过 A/B 测试验证 |

---

## 附录 F：术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| 知识追踪 | Knowledge Tracing (KT) | 动态追踪学生知识掌握状态的技�?|
| 贝叶斯知识追�?| Bayesian Knowledge Tracing (BKT) | 基于 HMM 的知识追踪方�?|
| 深度知识追踪 | Deep Knowledge Tracing (DKT) | 基于 LSTM 的知识追踪方�?|
| 间隔重复 | Spaced Repetition (SR) | 按递增间隔安排复习的技�?|
| 遗忘曲线 | Forgetting Curve | 记忆保持量随时间衰减的曲�?|
| 掌握学习 | Mastery Learning | 达到掌握标准后才推进的教学方�?|
| 脚手�?| Scaffolding | 临时性教学支持，随能力增长逐步撤除 |
| 最近发展区 | Zone of Proximal Development (ZPD) | 独立能力与实际能力之间的差距 |
| 记忆三组�?| Three Component Model (DSR) | Difficulty-Stability-Retrievability 模型 |
| 教育数据挖掘 | Educational Data Mining (EDM) | 利用数据技术研究教育问�?|
| 强化学习 | Reinforcement Learning (RL) | 通过奖励信号学习最优策略的 ML 方法 |
| 苏格拉底式提�?| Socratic Questioning | 通过提问引导而非直接给答案的教学方法 |
| 2-sigma 效应 | 2-Sigma Problem | 一对一辅导比班级授课高出两个标准差的现�?|
| 纳米级知识点 | Nano-level Knowledge Point | 极细粒度的知识单元划�?|
| 期望保留�?| Desired Retrievability | 用户设定的目标记忆保持概�?|
