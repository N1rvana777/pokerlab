# Libratus 一手文献精读笔记
Brown & Sandholm, "Superhuman AI for heads-up no-limit poker: Libratus beats top professionals", Science 359(6374):418–424, 2018（DOI 10.1126/science.aao1733）

- 用途：为 PokerLab（HU PLO4，turn/river subgame solver）提供设计参考。
- 规则：凡写成"论文内容"的条目，都来自本次实际读过的全文，并附页码。我自己的推断或评估一律标【评估】；凭记忆的内容标 **UNVERIFIED (from memory)**；论文没写的内容标"未披露"。
- 整理日期：2026-10-23

---

## 要点速览（细节与页码见各节）
1. 三个模块：(i) 抽象 + ES-MCCFR（带采样式 negative-regret pruning）算 blueprint；(ii) 从 turn 起做 nested subgame solving，不用 card abstraction，求解器是 CFR+，迭代 1,000 或 1,900 次；(iii) self-improver：每晚为 preflop 补 3 个对手常用的 bet size。
2. 比赛中的配置是：第一次进入 turn 时做一次 **unsafe** 求解，之后对手每次 bet/raise 都做 **safe** 重解。safe 部分包括：每个对手手牌的 alternative payoff 用估计值（不是上界），再加上 gifts 向量；off-tree 下注被纳入 subgame 后重解。
3. 理论保证只有 Theorem 1：两人零和、perfect recall，可剥削性 ≤ exp(σ*) + 2Δ。作者自己承认，unsafe 根求解、采样剪枝、imperfect-recall 抽象、self-improver、post-processing 都没有保证。
4. 评估：12 万手、duplicate 发牌、all-in 时按所有 runout 取平均，没有用 AIVAT。结果是 147 mbb/hand，p = 0.0002（以 i.i.d. 为前提）。
5. 算力：总共约 1,200 万 core hours（Bridges 超算，只用 CPU）。其中 blueprint 约 300 万，实时求解 150 万，self-improve 150 万。
6. 论文没有披露：bet size 列表、card abstraction 的特征、blueprint 迭代次数、剪枝常数、比赛中 augmented game 的确切目标函数。

---

## 0. 来源、文件与读取范围

| 本地文件（scratchpad\papers\libratus\） | 请求 URL → 实际 URL | 大小 (bytes) | 页数 | SHA256（前8…后6） | 读了多少 |
|---|---|---|---|---|---|
| science_main.pdf | https://noambrown.github.io/papers/17-Science-Superhuman.pdf → https://noambrown.com/papers/17-Science-Superhuman.pdf | 290,978 | 8 个 PDF 页（正文 "1–7 of 7" + 1 页 Science 信息页） | 7c8dc72b…a6217a | 全部 8 页 |
| aea_with_supplement.pdf | https://www.aeaweb.org/conference/2018/preliminary/paper/h9Bs5dth（这个链接直接返回 PDF，并不是 landing page） | 1,804,607 | 50 个 PDF 页 | 94950608…702059 | 全部 50 页 |
| neurips2017_safe_nested_arxiv.pdf（次要澄清来源） | https://arxiv.org/pdf/1705.02955（v3，2017-11-16） | 1,021,588 | 22 页 | f70b5cf6…62fbfb | 全部 22 页 |

**AEA PDF 的结构**
- PDF 第 1–11 页：Science First Release 版正文（2017-12-17），含 Fig.1–3 和 Table 1–3。
- PDF 第 12 页：Science 信息页。
- PDF 第 13–50 页：Supplementary Materials（SM），包括封面和打印页码 2–38 的内容：Supplementary Text、Figs. S1–S2、Table S1、References 1–68。
- 换算：**SM 打印页码 N 对应 AEA PDF 第 N+12 页**。

**其它访问**
- https://arxiv.org/abs/1705.02955（41,931 bytes）：用来确认版本历史，v1 为 2017-05-08，v2 为 2017-05-26，v3 为 2017-11-16。
- https://noambrown.github.io/（重定向到 noambrown.com，8,997 bytes）：首页没有 Libratus 补充材料的链接。
- 以下尝试都失败了，所以未读：
  - noambrown.com/papers/17-Science-Superhuman-SM.pdf（404）
  - noambrown.com/papers/17-Science-Superhuman-Supplementary.pdf（404）
  - science.org 官方 SM PDF（403）
  - science.sciencemag.org/content/suppl/2017/12/15/science.aao1733.DC1（403）

**页码约定**
- 【Sci p.N】：Science 印刷版第 N 页（"N of 7"）。
- 【FR p.N】：First Release 版正文，即 AEA PDF 第 N 页。它与印刷版内容一致，主要差别是单位写成 mbb/hand（印刷版写 mbb/game），另有少量措辞不同。
- 【SM p.N】：补充材料的打印页码 N。
- 【NIPS p.N】：Brown & Sandholm, "Safe and Nested Subgame Solving for Imperfect-Information Games"（NeurIPS 2017）arXiv v3 的打印页码。**这是另一篇论文**，只用来澄清概念，引用处都会明确标出。

**读取方式与可靠性**
- 用 Claude Code 的 Read 工具读取（PDF 文本抽取 + 页面图像）。
- 文本抽取中部分公式符号会错位（如 σ*、下标），我结合伪代码与上下文还原。唯一发现的符号矛盾见 C2。

**无法读取 / 未读的内容**
1. Science 官网的最终版 SM（403）。本笔记读的是 First Release 版 SM（2017-12-17），与最终版是否有差异未知。
2. 方法细节所在的被引文献都没读：ref 29（用参数优化选 bet size）、ref 30（Baby Tartanian8）、refs 31–33（Tartanian7 / card abstraction / post-processing）、ref 61（CFR+ 的优化）。所以下文凡涉及这些细节，都标"未披露"。

---

## A. Abstraction

### A1 Blueprint 的 action abstraction
- 大部分 bet size 是底池的"整齐"分数或倍数。这些尺寸是分析以往 ACPC 顶级 AI 在各个位置最常用的下注尺寸后大致定下的。【Sci p.1】
- 博弈树早期的某些 bet size 由一个通用（与应用无关）的参数优化算法确定，该算法收敛到局部最优的尺寸集合（ref 29 = Brown & Sandholm AAAI 2014）。【Sci p.1】
- 前两轮（preflop、flop）的 action abstraction 很密（dense），也就是包含很多 bet size，用来减小对 off-tree 下注做 rounding 时的误差。【Sci p.5 首段；Sci p.5 Self-improvement 节】
- 正文中"按 $100 递增"只是解释 action abstraction 的例子，不是 Libratus 的实际抽象。【Sci p.1】
- Libratus 有**多个 blueprint**，会按两个条件切换：自己是先手还是后手；人类的 opening action behavior。【SM p.8，Hardware 节】这是全文唯一提到"根据对手行为选择策略"的地方，切换规则未披露。
- **未披露**：每轮具体的 bet size 列表和数量、raise 次数上限、all-in 的处理方式。Science 正文和 SM 都没写。

### A2 Subgame 内的 action abstraction
- 实时求解时，Libratus 会为剩余的 subgame 构造一个新的、更细的抽象。【Sci p.3】
- 对手的 off-tree 动作会先加入 subgame，然后再求解。【Sci p.1，p.4】
- 每手牌第一次做 subgame solving 时，Libratus 会改变本手及后续 subgame 中**自己**使用的 bet size：所有尺寸统一放大或缩小一个百分比，该百分比在 0–8% 之间均匀随机抽取。目的是迫使对手不断适应新的尺寸和策略。【Sci p.4，第 (4) 点；Sci p.6，note 49】
- SM 明确说，**所有 subgame 都使用 perfect-recall abstraction**。【SM p.10】这与 blueprint 使用的 imperfect-recall card abstraction 形成对比。
- **未披露**：subgame 内 bet size 的数量和列表。

### A3 Card abstraction
- **Blueprint 中各轮的处理**【Sci p.1–2】
  - 第 1、2 轮（preflop、flop）：不做任何 card abstraction。
  - 第 3、4 轮：只在 blueprint 中抽象，由算法自动分组。
    - 第三轮：约 5,500 万种手牌可能，分成 250 万个 bucket。
    - 第四轮：约 24 亿种，分成 125 万个 bucket。
- 抽象算法与 Baby Tartanian8（2016 ACPC 冠军，ref 30）和 Tartanian7（2014 ACPC 冠军，refs 31–33）"相似"。【Sci p.2】
- 这是 imperfect-recall abstraction：为了让当前牌面的抽象更细，刻意遗忘部分历史牌面信息。【Sci p.2】
- **未披露**：聚类特征、距离度量，是否 potential-aware、是否用 EMD。Science 正文和 SM 都没写。
  - NIPS 论文**自己的实验**用的是"一个领先的 information abstraction 算法 [11]"，即 Ganzfried & Sandholm AAAI 2014 的 potential-aware imperfect-recall + EMD【NIPS p.10，ref 11 在 NIPS p.13】。但该文没说 Libratus 也用这个。
- **实战中的做法**
  - 第 3、4 轮不按 blueprint 出牌，而是用不做任何 card abstraction 的 nested subgame solving。所以实战中每一手牌都被单独考虑。【Sci p.2】
  - 正文说，blueprint 在后两轮只用来估计"在某个 subgame 中拿某手牌应得多少回报"。【Sci p.2】
- 【评估】正文与 SM 的说法可能存在张力：
  - SM 说，比赛中第三轮开头用 unsafe 求解，正是因为它只需要存前两轮的策略；而 safe 求解需要存第三轮的 infoset values，blueprint 会大约变大 50 倍。【SM p.16】
  - 之后的 safe 求解，用的是上一次 augmented subgame 的解作为"blueprint"。【SM p.17】
  - 因此按比赛配置，第 3、4 轮的 bucketed blueprint 似乎**没有**被用作 alternative payoff 的数值来源。
  - 正文"用 blueprint 估值"的说法应是一般性描述。论文没有明说两者的关系，以上是我的推断。

---

## B. Blueprint 计算

### B1 算法
- **算法变体**：改进版 External-Sampling MCCFR（ES-MCCFR，ref 34 = Lanctot et al. NIPS 2009），再加上采样式的 negative-regret pruning。【Sci p.2；SM p.11】
- **存储**：每个 (infoset, action) 维护两个量。【SM p.11】
  - regret R(I,a)。
  - 计数 φ(I,a)：在对手的遍历中，该动作被采样的次数，用来计算平均策略。
- **当前策略**：regret matching，即 σ^t(I,a) = R₊^{t−1}(I,a) / Σ_{a'} R₊^{t−1}(I,a')；若分母为 0 则取均匀分布。【SM p.11；伪代码 CALCULATE-STRATEGY 在 SM p.16】
  - note 38 提到 hedge 也是可选的更新规则【Sci p.6】，但 SM 的伪代码用的是 regret matching。
- **每一轮迭代 t 做什么**【SM p.11–12；Alg.1 在 SM p.14】
  - 对两个玩家各遍历一次博弈树（正文的说法是每局之后交换角色【Sci p.2】）。
  - 遍历是深度优先的。
  - chance 节点：只采样 1 个结果。
  - 对手节点：按 σ^t 采样 1 个动作，并令 φ+=1。
  - traverser 节点：展开所有动作，计算 v(I) = Σ_a σ(I,a)·v(I,a)，然后更新 R ← R + v(I,a) − v(I)。
  - 第一局还没有任何学习，所以使用均匀随机策略。【Sci p.2】
- **平均策略**：跑完 T 轮后，把 φ(I,·) 归一化得到 σ̄^T。Alg.1 的标题写明，实战中在 infoset I 按 φ(I,a) 的比例采样动作。所以 **blueprint 实战用的是平均策略**。【SM p.12，p.14】
- **收敛性**【SM p.12】
  - 只在"无抽象的两人零和博弈"中保证：σ̄^T 以高概率趋近 Nash 均衡。
  - imperfect-recall abstraction 可能让算法无法收敛，作者说 Libratus 的 blueprint "可能就是这种情况"；但实践中得到的仍是好策略。
- **没有提到任何 discounting 或 linear averaging**：Alg.1 中 φ 每次等权累加。【SM p.11–15，基于我读完的全文】

### B2 采样式 negative-regret pruning
- **何时启用**：只在 t > T0 之后启用；在此之前是标准 ES-MCCFR。【SM p.12；Alg.1 第 8 行在 SM p.14；note 39 在 Sci p.6】
  - 伪代码中 T0 = T/2。
  - note 39 的说法是"大约最后一半的迭代"。
- **规则**（只作用于 traverser 自己的 infoset）【SM p.12–13；伪代码 TRAVERSE-ESMCCFR-P 在 SM p.15】
  - 若 R(I,a) < C（C < 0），则该动作被探索的概率为 K/(K + C − R(I,a))，其中 K > 0。
  - 每个动作独立采样。
  - 探索概率有 2% 的下限，而且这个下限作用在链式采样概率 p 上：thresh = max{0.02/p, K/(K+C−R)}。
  - 向下遍历时更新 p ← p·min{thresh, 1}。
  - 如果某动作被探索，它下方对手 infoset 的 φ 增加 1/p，而不是 1。
  - 如果某动作没被探索，本轮既不遍历它的子树，也不更新它的 regret。
- 被剪掉的动作 regret 为负，所以 σ = 0，不影响 v(I) 的计算。【SM p.13】
- **效果**
  - MCCFR 大约加速 3 倍，因此能解更大的抽象。【Sci p.2】
  - 缓解了 imperfect-recall 中同一个 bucket 内不同决策点互相"拉扯"（fight）策略的问题：实战中根本到不了的决策点不再更新策略。【Sci p.2】
- **作者明说**：这种采样式剪枝**没有**收敛到 Nash 均衡的理论保证。它的灵感来自有理论保证的 regret-based pruning（ref 66）和 best-response pruning（ref 67）。【SM p.13】
- **未披露**：C、K 的数值；T 与 T0 的具体值。

### B3 平均策略与当前策略分别用在哪里
- blueprint 实战：用平均策略（即 φ 归一化的结果）。【SM p.12，p.14】
- safe subgame solving 的 alternative payoff：v_bp(I1(h)) = (1/T)·Σ_{t=1..T} v^t(I1)。也就是"在 blueprint 中跑 T 轮某个 CFR 变体后，各轮 iterate 价值的平均"，而**不是**平均策略的价值。【SM p.17】
- nested 情形：v_bp 来自上一个 augmented subgame 的解。在下一次 subgame solving 之前，这个解就充当 blueprint。【SM p.17】
- （次要来源）NIPS 的实验用 CFR 最后一轮的 P1 策略 σ₁^T 来近似"抽象内的 counterfactual best response"。【NIPS p.8】这与 Science SM 的"迭代价值平均"做法不同，两者描述的是不同系统、不同实验。
- **未披露**：子博弈的 CFR+ 解出来后，实战用的是平均策略还是最后一轮的 iterate。

### B4 Post-processing
- 对 Baby Tartanian8（BT8）的结果【Sci p.5，Table 3】
  - 纯 blueprint：−8 ± 15 mbb/game。
  - 在第 3、4 轮加上已有的 post-processing（ref 31，例如去掉低概率动作）：+18 ± 21 mbb/game。
- 去掉低概率动作对"不会调整的 AI"更有效，但会增加可剥削性，因为策略变得更可预测。【Sci p.5】
- 完整版 Libratus 在第 3、4 轮**不做** post-processing；前两轮主要用一种新的、更稳健的形式。【Sci p.5】
- 这种新形式叫 **range thresholding**【SM p.22–23】
  - 只有当**所有**手牌选择某动作的概率都低于阈值时，才把该动作置零。
  - 比赛中前两轮的阈值是 4%。
  - 作者的动机示例来自他们 2015 年的 Claudico：按单手牌设阈值会导致 limp 只出现在坏牌上，从而极易被剥削。
- nested subgame solving 的子博弈中**不做** post-processing。【SM p.32，Table S1 图注；Sci p.5】

### B5 计算量
- Blueprint 使用 196 个 nodes，约 300 万 core hours（包含多个 blueprint）。【SM p.8】
- **迭代次数未披露**。

---

## C. Nested subgame solving

### C1 何时调用
- **前两轮**：按 blueprint 出牌；对手的 off-tree 下注被 rounding 到附近的抽象内尺寸（即 action translation），靠密集的 action abstraction 降低误差。【Sci p.4–5】
  - 理由：前两轮的 blueprint 本来就没有 card abstraction；在这么早的位置做实时求解，反而需要在 subgame 里做很重的抽象，不太可能比 blueprint 更好。【Sci p.5】
- **何时开始实时求解**：到达第三轮（turn）时；或者在更早的位置、但剩余博弈树已经"足够小"时（note 44：指双方都不能再下注或加注的情形）。此时构造剩余 subgame 并实时求解。【Sci p.3；note 44 在 Sci p.6】
- **unsafe 与 safe 的分工**：第一次进入第三轮时做**一次 unsafe** 求解；之后对手每次 bet 或 raise，都做 **safe** 求解。【note 45 在 Sci p.6；SM p.16】
  - NIPS 论文对 Libratus 的描述一致：从第三轮开始，并且之后对对手的每次下注都重解。【NIPS p.12】
- 【评估】按字面描述，触发重解的是对手的 bet/raise；发 river 牌本身不触发重解，因为 turn 时求解的 subgame 一直延伸到游戏结束，已经包含了所有可能的 river。
- **为什么 turn 根用 unsafe**【SM p.16】
  - unsafe 只需要存前两轮的策略。
  - safe 需要存第三轮的 infoset values，blueprint 空间会大约变大 50 倍。
  - 在中等规模的实验中，unsafe 的头对头表现有竞争力，可剥削性通常也较低。
- **subgame 一直解到游戏结束**，不是 depth-limited。【Sci p.3】
  - 正文说 P1 进入 subgame 后，就"正常进行到游戏结束"。
  - 作为对比，DeepStack 在前两轮用神经网络估计深度上限处的价值，做的是 depth-limited 求解。【Sci p.4】

### C2 Subgame 与 augmented subgame 的构造
- **Subgame 的定义**【note 13 在 Sci p.6；形式定义在 SM p.10】
  - 由公共知识确定：已发的公共牌 + 已发生的动作序列。
  - 与这份公共知识相容的每一种私有牌组合（即每个节点）都是该 subgame 的一个根。
  - S_top = subgame 中最早可达的节点集合。【SM p.13】
- **Unsafe**【SM p.13，p.16；Sci p.3】
  - augmented subgame 只有一个起始 chance 节点，它以 π^σ(h)/Σ_{h'∈S_top} π^σ(h') 的概率连到每个 h ∈ S_top，之后与 S 完全相同。
  - 这里的权重是双方按 blueprint 到达该节点的联合概率，相当于用双方的 blueprint range 作为信念。
  - 它假设对手按 blueprint 打，所以对手换策略就能剥削它。
- **Safe**（我方 P2 求解，对手是 P1）【SM p.16–17】
  1. 对每个 h ∈ S_top，在它前面插入一个 P1 节点 h_r。
  2. 起始 chance 节点按对手可达权重连到 h_r。这个权重只包含 chance 与我方 P2 的到达概率，不包含 P1 自己的概率（见下面的符号问题）。
  3. 在 h_r 处，P1 二选一：
     - a_S：进入 subgame，之后与 S 相同。
     - a_alt：直接结束，P1 得到 v_alt(h) = v_bp(I1(h)) + g[c]，其中 g 是 gift（见 C4），c 是 P1 的手牌。
- 【我的观察：符号不一致】
  - SM p.16 的公式写的是 π^σ_{−2}(h) / Σ π^σ_{−2}(h')。
  - 但按 SM 自己的记号定义（SM p.9：π_{−i} = 除 i 以外所有玩家与 chance 的贡献），π_{−2} 应包含 P1 的概率。
  - 而同一段的文字解释是"假如 P1 总是试图到达该节点时的到达概率"；正文 Sci p.3 和 NIPS p.5（那里明确写的是 π^σ_{−1}）都描述"chance × P2 的到达概率"。
  - 所以 SM 公式的下标大概率是笔误，**应为 π_{−1}**。
- **正文的等价描述**【Sci p.3；Fig.1 在 Sci p.2】
  - 先随机给 P1 发一手私有牌。
  - 给定我方 σ2 和 P1 的手牌，P2 的手牌按条件分布发出。
  - P1 选择进入更细的 subgame，或者拿 alternative payoff（即 blueprint 估计的、该手牌在该 subgame 中的价值）。
  - 解出后，P2 用这个解继续打。
- **Algorithm 2（Safe Subgame Solving）的流程**【SM p.20】
  1. 记录 P1 若试图到达、到达各个 S_top 节点的概率 π_{−i}。
  2. 对每个 P1 infoset，取 v_bp 并加上 gift，得到 v_alt。
  3. 构造对手动作 a 之后的 subgame。
  4. 调用 SOLVEAUGMENTED 求解。
  5. 用新解的价值更新 gift 向量。

### C3 Margin、Estimated-Maxmargin 与 Theorem 1
- **Margin**（每个 P1 手牌一个）= 该手牌按 blueprint 的期望值 − P1 进入更细 subgame 后可得的期望值。【Sci p.3】
- **Estimated-Maxmargin**：寻找使所有 P1 手牌中**最小 margin 最大**的策略。【Sci p.3】
  - 它与早先的 Maxmargin（ref 15 = Moravčík et al. AAAI 2016）的区别：原 Maxmargin 保守地用"P1 对 P2 blueprint 打 best response 时在 subgame 中的所得"作为基准，也就是用上界而不是估计值。
- **Theorem 1**【Sci p.3；证明在 SM p.23–26】
  - 前提：σ_i 是两人零和、perfect-recall 博弈中的一个策略；S 是一组互不重叠的 subgame；σ_i* 是仅在 S 中与 σ_i 不同、且可剥削性最小的策略。
  - 假设：对每个对手决策点（扑克中即每手牌）和每个 subgame，我们对"对手 best response to σ_i* 的价值"的估计误差都不超过 Δ。
  - 结论：对实战中到达的任何 S 中 subgame 应用 Estimated-Maxmargin，整体可剥削性 ≤ exp(σ_i*) + 2Δ。
  - 证明的关键：实时只解到达的 subgame，在可剥削性上等价于事先独立解好所有 subgame；然后对 P1 的 infoset 按"层级"归纳，证明每层的 CBV 上界。
- **note 47**【Sci p.6】
  - 定理只要求真实博弈是 perfect recall，不要求 blueprint 的抽象是 perfect recall。
  - 定理还假设子程序真的最大化了最小 margin；一个充分条件是 subgame 内没有任何抽象。
- **相对旧方法的四点改进**【Sci p.3–4】
  1. 用估计值代替上界。旧方法（refs 14、15）用上界，能保证不劣于 blueprint，但过于保守；用估计值理论上可能比 blueprint 更可剥削，不过 Theorem 1 给出了上限。
  2. gifts（见 C4）。
  3. 对 off-tree 下注实时计算专门的回应（见 C5）。
  4. 每手牌更换 bet size（见 A2）。
- **术语**
  - Science 文中使用：safe/unsafe subgame solving、Maxmargin、Estimated-Maxmargin、augmented subgame、gifts（在 SM 中）、nested subgame solving。
  - Science 文中**没有**使用 "Reach" 或 "Resolve"。
  - Reach、Resolve、Distributional、inexpensive/expensive 都是 NIPS 论文的术语。【NIPS §4–7，p.4–10】
- **比赛中实际求解的是哪个目标函数？Science/SM 未明说。**
  - 候选包括 Maxmargin 的 gadget game、Resolve 型 augmented game、Distributional alternative payoffs。
  - Alg.2 只写了通用的 SOLVEAUGMENTED；正文只说 augmented subgame 用 CFR+ 求解。
  - NIPS 说，实践中 Resolve 配合估计值远好于 Maxmargin【NIPS p.9】；其实验中表现最好的是 Reach-Estimate + Distributional【NIPS p.11】。
  - 另见 C8 的数值交叉核对。

### C4 Gifts（NIPS 称为 Reach subgame solving）
- **直觉**【Sci p.4；SM p.17】
  - 如果 P1 只有在之前犯过错（放弃了更高 EV 的动作）的情况下才可能拿着某手牌，那么在后续 subgame 中可以允许这手牌的价值上升，只要上升量仍小于它犯错的代价。
  - 这样 P2 就能把防守集中在 P1 真正可能持有的手牌上。
  - 正文的例子是 2♠7♥（最差的手牌，本应立刻弃牌）。SM 的例子是 2♠2♣：动作 A 只对 2♠2♣ 有巨额收益，如果对手选了 B，就几乎可以确定她没有 2♠2♣。
- **实现**【SM p.18；Alg.2 在 SM p.20】
  - 为对手的每一种私有手牌维护一个 gift 值，组成向量 g。
  - 在游戏开始时清零；在 Libratus 中，是在 turn 那次 unsafe 求解之后清零。
  - 每当观察到对手动作 a，对我方 infoset 中可能对应的每一手对手牌 c，更新 g_new[c] = g[c] + v_bp(I1(h)) − v_bp(I1(h), a)。如果对动作 a 做过 subgame solving，就用相应 augmented subgame 的价值代替 v_bp(I1(h), a)。
  - 后续 subgame 中，把 g[c] 加到 v_alt 上。
- **不能把 gift 放大**【SM p.18–19】
  - 实时只解到达的 subgame，在可剥削性上等价于独立地解所有 subgame。
  - SM 举例：动作 B 之后有 100 个各以 1% 概率到达的 subgame。如果每个 subgame 都把 gift 放大 100 倍，对手在 B 上的总价值就会超出上限。
- **gift 在多个 subgame 间如何分配**（脚注 2）【SM p.19–20】
  - Libratus 中，各 subgame 实际上按"对手可到达的概率"加权，即路径上 chance 与我方动作概率的乘积，不含对手自己的动作概率。
  - 因此每个 subgame 恰好用到 100% 的 gift，不多也不少。
  - 其它分配方式也可以，只要按到达概率加权后的总和不超过整份 gift。
- **（次要来源）NIPS 的相关说法**
  - Reach 的理论保证（NIPS Theorem 1）使用 gift 的**下界**，下界只用直接通向终局的动作来计算。【NIPS p.7–8】
  - 只要所用 gift 不超过真实的 CBV 差，结果就仍然安全。【NIPS p.7】
  - 如果按 chance 节点的分支因子（1,755）放大 gift（论文称 "not split"），理论保证会被削弱。经验上这样常常更好，但并不总是如此。【NIPS p.11；附录 D 在 NIPS p.18】
- 【评估】
  - Libratus 的 gift 用的是估计值 v_bp 之差，而不是 NIPS 定理要求的下界。
  - 所以 Libratus 实际的 gift 用法不在 NIPS Theorem 1 的保证范围内。
  - Science 的 Theorem 1 只讲 Estimated-Maxmargin，也没有涵盖 gift。

### C5 Off-tree 对手动作的处理
- **前两轮**：rounding 到附近的抽象内尺寸。具体用哪种映射**未披露**；实验中作对比的是 pseudo-harmonic mapping（ref 27）。【Sci p.4–5】
- **第 3、4 轮：不做 rounding，而是实时求解**【Sci p.4】
  - 在 off-tree 动作之后生成一个 augmented subgame。
  - 其中 alternative payoff = 对手本可以选的、**最好的抽象内动作**的价值；这个"最好的动作"可以随手牌不同而不同。
  - 这样无论对手拿什么牌，选择 off-tree 动作都不会让她比选抽象内动作更好。
  - 之后的每一个 off-tree 动作都重复这一过程，这就是 nested subgame solving（见 Fig.2）。
- **实验**【Sci p.5，Table 2】
  - 在一个小型扑克变体中（博弈有三个 bet size，抽象只含其中两个）比较可剥削性（mbb/game）：
    - action translation：1,465
    - nested unsafe：148
    - nested safe：119
  - 改进超过 10 倍。
- **（次要来源）NIPS §7 的两种方法**【NIPS p.9–10】
  - inexpensive 方法：subgame 从 off-tree 动作之后开始；alternative payoff 用 CBV~，即 P1 被限制在 blueprint 抽象内（不含该动作）时能达到的近似最优价值。作者明确说这**放松了安全保证**。
  - expensive 方法：从父节点 h 开始做 unsafe 求解，因此要重算 h 处的所有动作。
- **NIPS Table 4 的结果**（mbb/h）【NIPS p.12】
  - Randomized Pseudo-Harmonic：1,465
  - Resolve：150.2
  - Reach-Maxmargin（expensive）：149.2
  - Unsafe（expensive）：148.3
  - Maxmargin：122.0
  - Reach-Maxmargin：119.1
- 【评估】Science Table 2 的三个数（1,465 / 148 / 119）与 NIPS Table 4 中的 pseudo-harmonic、Unsafe(expensive)、Reach-Maxmargin 完全对应。由此推断，Science 所说的"nested safe"就是 NIPS 中带估计值的 inexpensive Reach-Maxmargin。

### C6 子博弈求解算法
- **算法**：高度优化的 CFR+（refs 22 = Tammelin et al. IJCAI 2015；61 = Johanson et al. IJCAI 2011）。【note 46 在 Sci p.6】
  - 选 CFR+ 的理由：在需要精确解的小博弈中，CFR+ 表现更好。
  - 已知的一项优化：同时跟踪 P1 所有可能的手牌，而不是每次随机发一手。也就是对整个 range 做向量化遍历。
- **迭代次数**【SM p.19】
  - 双方投入底池合计不超过 $1,600（即 16 BB）时：1,000 次 CFR+。
  - 否则：1,900 次。
  - 理由：大底池涉及的钱更多、更重要；同时剩余动作更少，每次迭代更快。
- **时间与资源**
  - Libratus 平均每**手**思考 13.0 秒；人类为 16.4–22.4 秒（统计时排除了超过 10 分钟的手）。【SM p.7】
  - Libratus 的用时被设计成与自己的私有牌无关，以防暴露 timing tells。【SM p.7】
  - 每局使用 50 个 Bridges nodes。【SM p.8】
- **未披露**：单次决策的时间上限；实战用 CFR+ 的平均策略还是当前策略；CFR+ 的具体细节（例如平均策略的加权方式）。
- **UNVERIFIED (from memory)**：ref 61 的标题应为 "Accelerating Best Response Calculation in Large Extensive Games"，内容是公共树上的向量化遍历技巧。本次没有读该文。

### C7 Subgame 内的 card abstraction
- 没有。【Sci p.2】
- note 47 指出，"subgame 内无任何抽象"正好是 Theorem 1 所需假设（子程序真的最大化了最小 margin）的充分条件。

### C8 实验结果
- **Table 1：小型变体上的可剥削性**（mbb/game）【Sci p.4–5】
  - 实验设置：这些变体足够小，可以精确计算可剥削性；只在到达最后一轮时做一次 subgame solving；双方都只能用两个 bet size，所以不涉及 off-tree 动作。

  | 方法 | Small 2-round | Large 2-round | 3-round |
  |---|---|---|---|
  | No subgame solving | 91.3 | 41.3 | 346 |
  | Unsafe | 5.51 | 397 | 79.3 |
  | Safe | 22.6 | 9.84 | 72.6 |

  - 作者的结论：safe 在所有情况下都把可剥削性降到原来的 1/4 以下；unsafe 有时更好，有时却恶化将近一个数量级。【Sci p.5】
- 【评估/交叉核对】
  - Large 2-round 与 3-round 两列的数值，与 NIPS Table 2（Large Flop，30,000 buckets）和 Table 3（Turn，20,000 buckets）中 Trunk / Unsafe / "Reach-Estimate + Distributional" 三行一致：分别是 41.41 / 396.8 / 9.840 和 345.5 / 79.34 / 72.59。【NIPS p.10–11】
  - 由此推断，Science 所说的"safe subgame solving"很可能就是 NIPS 的 Reach-Estimate + Distributional（gift 按理论安全的方式分配）。
  - Small 2-round 这一列与 NIPS Table 1 对不上。
- **Table 3：HUNL 中对 Baby Tartanian8 的表现**（mbb/game，95% CI）【Sci p.5】
  - Blueprint：−8 ± 15
  - Blueprint + post-processing：18 ± 21
  - On-tree nested（只用 BT8 抽象中有的尺寸，以排除 action translation 的影响）：59 ± 28
  - Full nested：63 ± 28
  - 作为参照，BT8 对 ACPC 另外两个最强 AI 的胜率分别是 12 ± 10 和 24 ± 20。【Sci p.5–6】
  - note 56 指出，这组实验可视为偏保守的估计。
- **对 BT8 评估时的方差缩减方法**【SM p.19】
  - 先直接测 blueprint 对 BT8 的胜率（无需实时计算，所以很快）。
  - 再从两个 AI 的对局中，随机抽取从第三轮开始的 subgame。
  - 在每个 subgame 中，对每一种可能的私有牌组合计算 nested solving 带来的期望改进，再按"根据动作序列推出的持牌概率"加权平均。
  - 这样只需解一次 subgame，就能评估大量手牌上的改进。
- **Table S1**【SM p.28–32】
  - 按我的人工计数，共 200 个 turn subgame（公共牌 4 张），底池大小在 200–8,580 之间。
  - 三列分别是：No subgame solving（blueprint + fold-call-bet purification）、On-tree、Libratus；单位 mbb/h。

---

## D. Self-improvement（自我改进模块）

### D1 做什么
- 在后台为 blueprint 补全缺失的分支（即新增 bet size），并为这些分支计算博弈论意义上的策略。新增哪里，由对手实际使用的 bet size 来指示。【Sci p.1，p.5】
- 只作用于第一轮（preflop）的动作。【SM p.20；Sci p.5】
- **每晚的流程**【Sci p.5；note 54 在 Sci p.6】
  1. 统计当天四位对手（汇总）在第一轮最常用的 bet size。
  2. 综合"使用频率"和"与最近的抽象内尺寸的距离"，选出 k 个尺寸，整夜求解。
  3. 到早上已经"合理收敛"的尺寸，连同它后面的策略一起加入 blueprint。
  - k = 3。理由是按现有算力，一般 24 小时内能较好地修补 3 个漏洞。
- **两种形式**【Sci p.5；SM p.20–22；Fig. S2 在 SM p.33】
  - **Type 1**（每晚 1 个）
    - 选当天四人汇总下来最常用的对手 bet size。
    - 用 unsafe subgame solving 求解，即假设此前双方都按 blueprint 打。
    - subgame 开始时，对手可以 fold、check、call 或下这个新尺寸。游戏的第一个动作处不提供 call 选项。
    - 只有当某位对手在该情境下**最近 8 次下注都用了这个尺寸**时，Libratus 才使用 Type 1 生成的回应。
    - 作者认为，这可以看作在对手打法不平衡时，以相对安全的方式一定程度地剥削对手。
    - 但人类几乎每天都换尺寸，所以 Type 1 在比赛中作用很小。
    - 正文称这种"不加默认尺寸"的形式更冒险，甚至带有剥削性；Libratus 用"只在对手大部分时间确实使用该尺寸时才启用"来降低风险。
  - **Type 2**（每晚 2 个）
    - 给相邻的两个已有尺寸 A < B 之间的"空档（gap）"打分：对手当天每次下出 A < x < B 的尺寸，该空档的分数就加 min{x−A, B−x}。
    - 取得分最高的两个空档，新增尺寸取它们的 pseudo-harmonic midpoint：(A + B + 2AB)/(A + B + 2)。尺寸都以底池的分数计。
    - 求解时额外加入至少一个 blueprint 中常用的默认尺寸，以免假设对手所有手牌都用新尺寸下注。
    - 默认动作之后的部分用更粗的抽象，解完就丢弃；只有新尺寸后面的策略被并入 blueprint。
    - 对手的动作只要接近新尺寸，Libratus 就使用这套策略。
    - 到比赛结束时，大约一半的手牌是用 Type 2 生成的策略打的。
- **作者对理论保证的说明**【SM p.22】
  - 带默认动作的 unsafe 求解，只有在"游戏的第一个动作"处才有可剥削性的理论界，因为那里不需要对对手之前的打法做任何假设。
  - 其它位置没有理论保证，但经验上可剥削性一般较低。

### D2 不做什么
- 大体上不做 opponent exploitation：不建对手模型，也不去找"弃牌太多""跟注太多"之类的错误来利用。【Sci p.5】
- 补上的修补是"通用的"：对所有对手都有效，而不只针对遇到过的对手。【Sci p.5】
- 双方每晚都能拿到当天的 hand histories，其中包括对手弃牌的手。self-improver 只用到对手**采取了哪些动作**，没有用到对手的底牌。【SM p.7】
- 【评估】Libratus 不为个体对手建模。仅有的"与具体对手相关"的成分有两处：
  - Type 1 是否启用，按该对手本人最近 8 次下注来判定。【SM p.21】
  - blueprint 会按人类的 opening action behavior 切换，规则未披露。【SM p.8】
- **算力**：夜间同时求解 3 个尺寸，白天 1 个；每个尺寸用 196 个 nodes（夜间共 588 个）；共约 150 万 core hours。【SM p.8】

---

## E. 评估协议（Brains vs. AI: Upping the Ante，2017 年 1 月）

**比赛规模与对手**【Sci p.6；SM p.5】
- 共 120,000 手，历时 20 天（人类自己选择了连续打 20 天）。
- 对手四人：Jason Les、Dong Kim、Daniel McCauley、Jimmy Chou。
- 奖金池 $200,000：每人保底 $20,000，剩下的 $120,000 按每人比四人中表现最差者好多少来分配。

**规则**【SM p.4，p.6；note 23 在 Sci p.6】
- 使用 ACPC 版 HUNL：每手开始时双方各有 $20,000（= 200 BB），盲注 $50/$100。
- P1/P2 的位置每手交替；最小加注等规则见 SM p.4。
- 筹码每手都重置为 200 BB。
- 作者指出，若用 100 BB，博弈更小，会对 AI 更有利。【SM p.6】

**方差控制**【SM p.5】
- duplicate matches：四名人类分成两组；同组中一人拿到的牌，Libratus 在对另一人时也拿到，从而双方都不会系统性地走运。
- 如果在最后一张公共牌发出之前 all-in，底池按所有可能的剩余牌 runout 的平均来分配，而不是只发一次。
- Science 正文和 SM **都没有**提到 AIVAT 或任何控制变量类的估计方法。

**结果**【Sci p.6；Fig.3 在 Sci p.4】
- Libratus 以 147 mbb/game 获胜（First Release 版写作 mbb/hand）。
- 统计显著性 99.98%，p = 0.0002，前提是把每一手视为 i.i.d.。
- Libratus 也分别赢了每一位人类，但每人的具体数据没有给出。
- Fig.3 中的 95% 置信区间同样基于 i.i.d. 假设。
- note 57 说，由于双方在比赛中都在适应，把各手视为独立是有问题的；但字面原文写的是 "not entirely inappropriate"，这与上下文的保留语气不一致，可能是笔误。作者还说，12 万手上 147 mbb/hand 无论如何都是决定性的胜利。【Sci p.6】

**其它（偏向人类的）赛制设计**【SM p.5–8】
- 人类可以同时打两桌，在 AI 思考时切到另一桌。
- 按人类要求使用四色牌，并提供可自定义的快捷键（主要用于下各种少见的底池分数）。
- 人类可以利用 timing tells，AI 则约定不用。
- 每晚可以用任何电脑软件分析，也可以请外援。
- 人类之间可以协作和协调（只是不能在同一手牌内），他们大量协调用不同的 bet size 去试探 AI 的弱点。
- 思考时间不限。
- 人类声称误点按钮时，该手牌作废。

【评估/低置信】Fig.3 左图纵轴标为"mbb × 10^6"，曲线终点约为 175。但 147 × 120,000 ≈ 1.76 × 10^7 mbb，若单位真是 10^6，终点应约为 17.6。也就是说，坐标轴标签和我对图的读数之间差了一个数量级；NIPS Fig.5 也是同样情况。这不影响任何结论。

---

## F. 算力与硬件
全部来自 SM p.8 的 Hardware 节。正文只在致谢中提到使用了 PSC 的 XSEDE 计算资源【Sci p.7】。

- **平台**：Pittsburgh Supercomputing Center 的 Bridges 超算。
- **总量**：比赛前和比赛期间使用 200–600 个 nodes；总计约 1,200 万 core hours，其中包括生产运行之前的探索性实验。
- **单个 node 的配置**：128 GB 内存，2 颗 Intel Haswell CPU，每颗 14 核。
  - 由于主要瓶颈是内存访问，每个 node 只用了 14 核，而不是 28 核；如果把闲置的 14 核也算进去，各项 core-hour 数都要翻倍。
  - 没有使用 GPU。
- **Blueprint**：196 个 nodes；算了多个 blueprint（按先后手和人类的 opening 行为切换）；约 300 万 core hours。
- **Nested subgame solving**（比赛中实时运行）：4 名人类每人可同时对 2 个 Libratus 副本，共 8 局并行；每局 50 个 nodes，共 400 个；约 150 万 core hours。
- **Self-improvement**：夜间同时解 3 个尺寸，白天解 1 个（白天大部分 nodes 用于实时求解）；每个尺寸 196 个 nodes，夜间共 588 个；约 150 万 core hours。
- 【评估】3 + 1.5 + 1.5 = 600 万 core hours；剩下约 600 万应属于探索性实验等，论文没有细分。

---

## G. 理论保证的适用范围，以及作者自认的启发式 / 不安全部分

### G1 只在两人零和（且 perfect recall）下成立的结论
- Theorem 1 的 2Δ 界，明确限定于 two-player zero-sum、perfect-recall 博弈。【Sci p.3】
- 证明所用的 exploitability 与 CBV 定义，依赖于"在两人零和博弈中，所有 Nash 均衡给同一玩家的价值相同"这一性质。【SM p.10】
- ES-MCCFR 的收敛只在"两人零和、无抽象"时成立。【SM p.12】
- 背景部分对 Nash 均衡、exploitability、CBR/CBV 的定义，都是在两人零和框架下给出的。【SM p.9–11】
- "safe"的含义是：无论对手用什么策略，她都不会比面对 blueprint 时更好。只有在零和博弈中，这才等价于"我方不会比 blueprint 更差"。【Sci p.3】
- （次要来源）NIPS 中对应的定理（其 Theorem 2）还要求博弈"没有私有动作"【NIPS p.8】，而 Science 版的 Theorem 1 没有写这个条件。扑克的下注动作全部公开，满足该条件。

### G2 作者自认没有保证、属于启发式或有风险的部分
1. turn 根部的 unsafe subgame solving：没有理论保证，只有中等规模实验支撑。【note 45 在 Sci p.6；SM p.13，p.16】
2. 采样式 negative-regret pruning：没有收敛保证。【SM p.13】
3. blueprint 使用 imperfect-recall card abstraction：可能导致无法收敛。【SM p.12】
4. 用估计值代替上界：理论上可能比 blueprint 更可剥削，由 Theorem 1 给出上限，但这个上限依赖未知的 Δ。【Sci p.3】
   - 因此正文所说的"可证明的安全保证"【Sci p.1】，应理解为这个 2Δ 界，而不是"永不劣于 blueprint"。
5. gift 不能放大，否则就失去安全保证。【SM p.18–19】另外，Libratus 是用估计值计算 gift 的（见 C4 的评估）。
6. off-tree 动作的 alternative payoff 取"最好的抽象内动作的价值"：Science 没有单独讨论这一步的理论保证；NIPS 明确说 inexpensive 方法放松了安全保证。【NIPS p.9】
7. 前两轮对 off-tree 下注做 rounding：作者自己称之为弱点，靠密集的 action abstraction 和 self-improvement 来缓解。【Sci p.4–5】
8. Self-improvement：Type 1 是 unsafe 求解，"更冒险，甚至带有剥削性"；Type 2 是带默认动作的 unsafe 求解，只在游戏的第一个动作处有理论界。【Sci p.5；SM p.21–22】
9. Post-processing 会增加可剥削性，range thresholding 只是缓解。【Sci p.5；SM p.22–23】
10. 统计显著性以 i.i.d. 为前提。【Sci p.6，note 57】

---

## H. 【评估】迁移到 PokerLab（HU PLO4 的 turn/river subgame solver）
本节**全部是我的评估，不是论文内容**。表中数字是我用 Python 计算的，方法见文末"计算记录"。

### H1 规模对比（计算结果）

| 量 | HUNL | PLO4 | 比值 |
|---|---|---|---|
| 起手牌组合数 | C(52,2) = 1,326 | C(52,4) = 270,725 | 204× |
| 按花色同构合并后的起手牌类别数 | 169 | 16,432 | 97× |
| flop 后对手可能的手牌（只排除公共牌） | 1,176 | 211,876 | 180× |
| turn 后（同上） | 1,128 | 194,580 | 172× |
| river 后（同上） | 1,081 | 178,365 | 165× |
| river 后，再排除己方手牌 | 990 | 123,410 | 125× |
| turn 时"私有牌 + 公共牌"组合数（原始，不合并同构） | 1.22e9 | 2.11e11 | 172× |
| river 时"私有牌 + 公共牌"组合数（原始） | 5.62e10 | 9.27e12 | 165× |

- Libratus 给出的 5,500 万（第三轮）和 24 亿（第四轮）应是合并花色同构后的数，与原始组合数相差约 22–23 倍。这是我的推断，论文没有说明计数口径。

### H2 基本可以照搬的
1. **safe nested subgame solving 的整体框架**：augmented subgame（每个对手手牌一个 alternative payoff）、用估计值而不是上界、gift 向量、off-tree 下注后重解并以"最好的抽象内动作的价值"作为 alternative payoff。
   - 这些方法对任何两人零和、perfect-recall 的博弈都成立。
   - HU PLO4 的下注动作全部公开，也满足 NIPS 定理的"无私有动作"条件。
2. **river subgame**：不做 card abstraction，用 CFR+ 对整个 range 做向量化遍历，迭代约 1,000–2,000 次。这在 PLO4 中仍然可行。
   - 每次迭代的成本约为 HUNL 的 165 倍（与 range 长度之比相同）。
   - Libratus 按底池大小分配迭代预算（以 $1,600 为分界）的思路可以沿用。
3. **"第一个求解的街用 unsafe，之后对手每次 bet/raise 用 safe 重解"的折中**，在 PLO 中更有吸引力。
   - 原因：要在 blueprint 中保存每手牌的价值，PLO 的存储成本放大约 170–200 倍；而 Libratus 在 HUNL 中就已经因为 50 倍的空间开销放弃了保存第三轮的价值。
   - 对于用户手动输入 range 的研究型 solver，根节点本身就相当于 unsafe（range 是假定的），这没有问题。safe/nested 的价值在于：对手在已解树中做出 off-tree 下注时，能安全地重解。
4. **gift 向量**：270,725 个 float 约 1 MB，开销可以忽略。
   - 但更新 gift 需要上一次求解在根部给出的、每个对手手牌的 v(I1) 和 v(I1,a)。所以每次求解都要保存这些按手牌、按动作的价值。
5. **post-processing**：用 range thresholding（只有当所有手牌的概率都低于阈值时才置零），并且在 turn/river 子博弈中不做 post-processing。
6. **实时扰动 bet size**（0–8%）：在 pot-limit 下需要在底池上限处截断。
7. **评估方法**：沿用 duplicate 发牌，以及 all-in 时按所有 runout 取平均。
   - 在 river/turn 子博弈中，可以直接精确计算 best response 和 exploitability，并把它作为主要指标。这一指标在两人零和下才有意义。

### H3 需要改造的
1. **card abstraction**：Libratus "前两轮不做 card abstraction" 的做法在 PLO 中不可行。
   - flop 的组合数约为 HUNL 的 180 倍；花色同构后的起手牌类别是 16,432 对 169。
   - 所以 PLO 的 blueprint 至少在 flop 就需要 bucketing，或者从更早的街开始做 depth-limited 实时求解。Libratus 没有这样做；Sci p.4 只在介绍 DeepStack 时提到这种做法。
2. **turn subgame 解到底且不做 card abstraction**
   - 粗略估算，仅 river 部分的存储（regret + 平均策略）≈ 48 张 river × 20 个 river 决策节点 × 3 个动作 × 178,365 手牌 × 8 字节 ≈ 4.1 GB。同样假设下 HUNL 只要约 0.025 GB。
   - （2026-10-23 补注）20 个节点的假设只对应极简树。本项目四档抽象实测每张河牌有 70–24,332 个 river 决策节点，对应约 42GB–14.5TB，见 docs/ARCHITECTURE.md 的规模估算。
   - 这是可行的，但实时运行有压力：Libratus 平均每手 13 秒，每局用 50 个 nodes。
   - 可选的做法：
     - 对 river 牌做花色同构。
     - 在 turn 求解中对 river 做 bucketing。但这会破坏 Theorem 1 的充分条件（subgame 内无抽象），理论界不再直接适用。
     - depth-limited 求解，在 river 处用价值估计。
3. **摊牌评估**：PLO 必须恰好用 2 张手牌 + 3 张公共牌。
   - river 上每手牌有 C(4,2) × C(5,3) = 60 种五张组合。每个 river 牌面都要为约 17.8 万手牌预先算出并排序牌力。
   - 在 O(n) 的向量化摊牌 / 弃牌求值中，处理 blocker（card removal）需要对己方 4 张牌的 15 个非空子集做容斥，并分别为单张（47 个）、两张组合（1,081 个）、三张组合（16,215 个）维护前缀累加器。HUNL 只需要单张修正。
   - 这是我的工程判断；HUNL 中的对应技巧，Science 论文也没有描述。
4. **action abstraction**
   - Libratus 用的是"底池的分数或倍数"。在 pot-limit 下，单次下注上限是"跟注后的底池"，加注上限是"跟注额 + 跟注后的底池"，所以不存在 overbet；只有筹码不超过上限时才会出现 all-in。
   - 底池按几何级数增长，打到 all-in 所需的加注层数更少，所以博弈树更浅。
   - off-tree 尺寸被限制在 [最小下注, 底池] 区间内，rounding 误差可能比 NL 小。但 Table 2"重解比 action translation 好 10 倍以上"的证据来自 NL 风格的变体，在 PL 中的改进幅度未知。
   - Type 2 的 pseudo-harmonic 中点公式对不超过 1 倍底池的尺寸照样可用。
5. **方差**：PLO 的方差通常被认为更高（我未核实）。因此人机或机机评估需要更多手数，或者引入 AIVAT 一类的方差缩减方法（Libratus 没有用）。

### H4 只在两人零和下成立的
- Theorem 1 的 2Δ 界、"safe"的概念、exploitability 指标、Nash 均衡价值的唯一性、CFR/MCCFR 的收敛性：
  - HU PLO4（无抽水）满足条件。
  - 有抽水时，博弈不再严格零和（我的判断），这些保证在形式上不再成立。
  - 多人 PLO 完全不适用。
- gift 的推理（"对手只有犯过错才会拿着这手牌"）建立在两人零和下的均衡价值之上。
- 论文中的所有实证数字（147 mbb/hand、Table 1–3、Table S1）都只针对 HUNL 或 hold'em 变体，不能直接外推到 PLO。

---

## I. 未核实 / 未披露 / 无法读取的清单
1. Science 最终版 SM（官网返回 403）未读；本笔记读的是 First Release 版 SM。
2. 每轮 blueprint 的 bet size 列表、数量和 raise 上限：Science 正文与 SM 都没有披露。
3. card abstraction 的特征、聚类方法和距离度量：未披露（只说与 BT8/Tartanian7 相似；refs 30–33 未读）。
4. blueprint 的迭代次数 T、剪枝启用点 T0、剪枝常数 C 和 K：未披露。
5. 比赛中 augmented subgame 的确切目标函数（Maxmargin gadget、Resolve 还是 Distributional）：未披露。
   - 数值比对显示：Table 1 的 "safe" 与 NIPS 的 Reach-Estimate + Distributional 一致，Table 2 的 "nested safe" 与 NIPS 的 Reach-Maxmargin 一致。这是我的推断。
6. 子博弈 CFR+ 的解在实战中用平均策略还是当前策略：未披露。
7. 前两轮做 rounding 时用哪种 action translation 映射：未披露。
8. 每位人类对手的个人胜率：未给出。
9. 多个 blueprint 如何按人类的 opening 行为切换：未披露。
10. **UNVERIFIED (from memory)**：ref 61 的标题（见 C6）。
11. SM p.16 中 safe gadget 的权重写作 π_{−2}，与文字解释、正文和 NIPS 的 π_{−1} 不一致（见 C2）。我判断是笔误。
12. 【评估/低置信】Fig.3 纵轴单位存在一个数量级的出入（见 E 节）。
13. "Table S1 共 200 行"是我人工数出来的。

---

## 计算记录
- 组合数：用 Python 的 math.comb 计算。
- 花色同构类别数：枚举全部 C(52,k) 种手牌，在 4! 种花色置换下取规范形后去重计数。结果：HUNL 169，PLO4 16,432。
- 内存粗估的假设：共 48 张可能的 river；每张 river 后有 20 个决策节点；平均每个节点 3 个动作；每个 (节点, 手牌, 动作) 存 regret 和平均策略各 4 字节。
