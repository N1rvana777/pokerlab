# 研究笔记：论文思想 → 本项目实现

更新：2026-10-23。下文的论文内容都来自本轮读过的全文，页码和逐项细节见 `docs/research/`；作者自己的判断标为【评估】。
Libratus 和 Pluribus 只是方法参考，本项目没有复现其中任何一个系统，也没有它们那样的职业对抗评测。

## 0. 读了什么、没读什么

| 来源 | 状态 | 详细笔记 |
|---|---|---|
| Brown & Sandholm, Libratus, Science 359 (2018)：作者 PDF 正文 8 页；AEA 公开版 50 页（First Release 正文 + 补充材料全文） | 全文已读 | `research/libratus_notes.md` |
| Brown & Sandholm, Safe and Nested Subgame Solving, NeurIPS 2017（arXiv 1705.02955v3） | 全文已读，仅作次要澄清 | 同上 |
| Brown & Sandholm, Pluribus, Science 365 (2019)：正文 7 页、补充材料 30 页（含 Algorithm 1/2） | 全文已读 | `research/pluribus_notes.md` |
| Li & Huang, Abstraction Agent, arXiv 2609.04303（24 页 + TeX 源码 + 代码仓库） | 全文已读 | `research/plo_impl_notes.md` |
| PokerRL-Omaha（commit d48d0c8） | 静态代码审计，未运行 | 同上 |
| GTO Wizard 两篇 PLO 技术说明、MonkerSolver 文档 | 已读，按厂商自述处理 | 同上 |
| Oscarsson 2024 KTH 学位论文（62 页）；Oscarsson 等 2025 IEEE ISI（8 页，无文字层，按页渲染图像阅读）；moscars/student-of-games 代码（commit 60fb516，未运行） | 全文已读 | `research/oscarsson_notes.md` |

另外，为了核对本项目默认算法，读了 Brown & Sandholm 的 "Solving Imperfect-Information Games via Discounted Regret Minimization"（AAAI 2019，arXiv 1809.04040，504KB），用 pdftotext 抽文字后，读了定义与实验设置两节。原文要点：
- DCFR_{α,β,γ} 在每次迭代 t：累计正 regret 乘 t^α/(t^α+1)，负 regret 乘 t^β/(t^β+1)，平均策略的累计贡献乘 (t/(t+1))^γ。
- 推荐参数 α=3/2、β=0、γ=2。
- LCFR 第 t 次迭代的 regret 与平均策略更新权重为 t，等价于 DCFR_{1,1,1}。
- CFR+ 用 Q = max{0, Q + r}，平均策略按 T 加权。该文实验中给 CFR+ 用的是 t² 加权，说是经验上更快。
- 所有实验用交替更新。
- 该文指出 LCFR 类加权可与采样（MCCFR）、剪枝配合，CFR+ 不行。

本项目 `cfr.py` 的实现与上述一致：先加入第 t 次迭代的贡献，再折扣。CFR+ 用 Tammelin 的线性加权，不是该文实验里的 t²。

本轮未读或无法读取：
- Libratus 在 science.org 上的最终版补充材料（403）；读的是 First Release 版。
- CFR+ 原文（Tammelin 等 2015）、MCCFR 原文（Lanctot 等 2009）本轮没有重读。它们的公式与上面 DCFR 论文的转述一致，正确性另由 LP 和 Kuhn 实测核对。
- RSPSA 2006（Omaha Hi-Lo）没有重读，只沿用交接包里的结论。

## 1. Libratus（单挑 NLHE，两人零和，每手重置 200bb）

- **蓝图**：External-sampling MCCFR，后半程加采样式负 regret 剪枝；平均策略由对手节点的采样计数得到（SM p.11–15）。
  - 没有 discount/linear 加权（全文未提）。
  - 剪枝没有收敛保证（SM p.13）。
  - 约 300 万 core-hours（SM p.8）。
- **抽象**：前两轮不做卡牌抽象。第 3、4 轮在蓝图中分别分成 250 万和 125 万个桶（Sci p.1–2），实战中这两轮不用蓝图出牌。具体尺寸列表和聚类特征都未披露。
- **嵌套子博弈求解**：
  - 从 turn 起触发：先做一次 unsafe 求解，之后对手每次 bet/raise 都做 safe 重解（Sci note 45；SM p.16）。
  - 解到游戏结束，不做 depth limit；子博弈内不做卡牌抽象（Sci p.2–3）。
  - 求解器是高度优化的 CFR+，对整个 range 向量化。底池 ≤ $1,600 时迭代 1,000 次，否则 1,900 次（Sci note 46；SM p.19）。实战用平均还是当前策略：未披露。
- **Safe 机制**：
  - 对手每手牌有一个 alternative payoff，用估计值而不是上界；再加 gift 向量（SM p.16–20）。
  - Theorem 1：exploitability ≤ exp(σ*) + 2Δ，只在两人零和、perfect recall 下成立（Sci p.3）。
- **树外下注**：前两轮四舍五入到附近尺寸；第 3、4 轮把该动作加入子博弈后重解（Sci p.4）。
- **Self-improver**：每晚给翻前补 3 个尺寸，不建对手模型，也不用对手底牌（Sci p.5；SM p.7、p.20–22）。
- **评测**：12 万手 duplicate 发牌，all-in 时对所有 runout 取平均，未用 AIVAT。结果 147 mbb/hand，p = 0.0002，前提是 i.i.d.（Sci p.6；SM p.4–6）。

## 2. Pluribus（6 人 NLHE，每手重置 100bb）

- **蓝图**：External-sampling MCCFR（S-p.15）。
  - 前 400 分钟线性加权：每 10 分钟把 regret 和平均策略都乘以 (T/10)/(T/10+1)，T 为分钟数（S-p.15）。
  - 200 分钟后，95% 的迭代剪掉 regret < −3 亿的动作；river 动作和直接通向终局的动作不剪（S-p.15）。
  - regret 用 int32 存储，下限 −3.1 亿，内存延迟分配（S-p.4–5、S-p.16）。
  - 翻前用平均策略；其余三轮用 800 分钟后每 200 分钟一次的当前策略快照的平均（S-p.16）。
  - 64 核跑 8 天，共 12,400 core-hours，内存 < 512GB（M-p.3）。
- **抽象**：每个决策点 1–14 个尺寸（S-p.13）。卡牌方面，翻前 169 类无损，之后每轮 200 个桶（蓝图）；搜索中当前轮无损、之后各轮 500 个桶（S-p.14–15）。
- **实时搜索**：
  - 第 2–4 轮总是搜索；翻前只在下注偏离较大且剩余人数 ≤ 4 时搜索（S-p.20）。
  - 根是公共状态上的分布；为每个玩家（包括自己）维护 1,326 种底牌的信念，并做 Bayes 更新；先为所有可能手牌计算策略，再执行实际手牌（M-p.5；S-p.21–23）。
  - 属于 unsafe 搜索，总是从本轮开始重解；只冻结自己已做动作在实际手牌上的概率（S-p.21–24）。
  - Depth limit：叶节点处每个玩家从 4 种延续策略中选择，即蓝图本身，以及 fold、call、raise 概率各乘 5 后的偏置版本（S-p.24–25）。
  - 子博弈较大或在早期用 Monte Carlo Linear CFR，否则用向量 Linear CFR；**行动按最后一次迭代**，信念按加权平均更新（S-p.22–23）。
- **理论**：两人零和以外没有 Nash 保证；6 人局里平均策略和当前策略没有理论优劣；没有报告 exploitability（M-p.2–3；S-p.16、S-p.21）。
- **评测**：AIVAT 方差缩减（约 9 倍），单侧检验。5H+1AI：+47.7 ± 25.0 mbb/game，p = 0.028；1H+5AI：+32.7 ± 14.9，p = 0.014（S-p.8–11）。

## 3. 两篇论文的贡献对照（思想来源）

| 思想 | Libratus | Pluribus |
|---|---|---|
| ES-MCCFR 训练蓝图 | 是（无加权，采样式剪枝） | 是（早期线性加权、确定式负 regret 剪枝） |
| 子博弈求解器 | CFR+，全宽向量化，解到终局 | Linear CFR（向量或 Monte Carlo），depth-limited |
| 安全性 | safe nested 重解（margin + gift），有 2Δ 界 | 明确选择 unsafe，无保证 |
| 树外动作 | 后两轮加入子博弈重解 | 加入子博弈从本轮开始重解；叶节点缺失时用 pseudo-harmonic 映射 |
| 多人 | 否 | 是（信念、冻结、延续策略） |
| 出牌策略 | 蓝图用平均策略；子博弈未披露 | 搜索按最后迭代 |
| 评测 | duplicate + runout 平均 | AIVAT |

## 4. 迁移到 PLO：可直接用 / 需要改 / 不适用

**规模**（本项目自算，见 research/libratus_notes.md H1 和 plo_impl_notes.md）：
- 翻前私牌 270,725 种，Hold'em 为 1,326 种（204 倍）；花色同构后为 16,432 类对 169 类。
- 河牌时每方 178,365 手，排除己方底牌后剩 123,410 手。
- 己方 4 张牌挡掉 30.8% 的对手组合，Hold'em 只有 8.4%。

**可以直接用**（与游戏无关）：
- CFR 族子博弈求解，河牌无卡牌抽象、整个 range 向量化；用 exploitability 精确度量；duplicate 评测。
- ES-MCCFR 蓝图框架。
- safe/nested 重解的思路、gift。
- 多人搜索里的信念维护、自身动作冻结、延续策略。

**需要改**：
- 摊牌必须恰好 2+3。卡牌移除要对 4 张牌的 15 个非空子集做容斥，Hold'em 只需要单张修正。
- Pot limit 让尺寸以底池为上限，没有 overbet。树更浅，all-in 只在筹码不超过上限时出现。
- 卡牌抽象：Libratus "前两轮无损"的做法在 PLO 不可行；PLO 的 flop 起就需要分桶或 depth-limit。
- 解 turn 到底并展开 river：libratus_notes H3 的粗估约 4GB，但它假设每张河牌只有 20 个 river 决策节点。按本项目四档抽象的实测节点数（每张河牌 70–24,332 个），全范围 turn 仅 regret 和累计策略就要约 42GB（5bb、加注上限 1/1）到 14.5TB（100bb、2/2），见 ARCHITECTURE 的规模估算。所以需要牌力抽象、同构、采样或叶节点估值。
- Pluribus 的剪枝阈值随筹码单位而定，需要重新调。
- PLO 方差更大，评测需要更多手数或方差缩减；这一点是业内经验，未核实。
- 多人和不等筹码会产生边池，Pluribus 每手重置 100bb 时从不遇到这种情况。

**不适用或不能外推**：
- 两篇论文的胜率、全部超参数、NLHE 的打法观察。
- 两人零和的定理不能外推到多人 PLO 或有抽水的 PLO。

## 5. 本项目当前的实现与论文对应

| 组件 | 本项目实现（`src/pokerlab/plo`） | 论文来源 | 差异与限制 |
|---|---|---|---|
| 卡牌抽象 | 河牌子博弈不做卡牌抽象：精确手牌、精确公共牌 | Libratus 子博弈无抽象（Sci p.2） | 范围是输入的假设，不来自蓝图 |
| 动作抽象 | 默认 1/3、1/2、2/3、1 pot 四档精确比例（下注与加注同一套 P/h/c 公式），另加最小合法下注/加注和 pot 尺寸或短码 all-in 两个边界动作，最多 2 次加注 | 两篇都用 pot 比例尺寸；Pluribus 的 turn/river 首次加注最多用 {0.5, 1 pot, all-in} | 不表示树外尺寸，exploitability 只对这棵树成立 |
| 遗憾更新 | `cfr`、`cfr+`、`lcfr`、`dcfr`（默认 3/2, 0, 2）、`es-mccfr`，交替更新 | CFR+ 来自 Libratus 子博弈；线性加权来自 Pluribus；DCFR 来自 Brown & Sandholm AAAI 2019（已核对原文定义） | LCFR 按每次迭代乘权重 t，不是 Pluribus 那种每 10 分钟乘折扣 |
| 采样 | `es-mccfr` 每次遍历采样一手对手底牌（机会）和对手动作，遍历者的底牌向量化、动作全展开；平均策略在对手节点累加 | 两篇蓝图都是 ES-MCCFR | 不是标量全局版本；没有剪枝，没有 int32 regret |
| 平均策略 | 报告默认用平均策略，同时报告当前迭代的 exploitability | Libratus 蓝图用平均；Pluribus 搜索按最后迭代 | 实际行动用哪种尚未决定（DECISIONS 未定项） |
| 搜索 / 重解 | `RiverResolver`：给定范围的单条河牌 unsafe 重解。`SolverRiverAgent` 在对局中第一次河牌决策时，从河牌开始处求解 | Libratus 第一次进 turn 时做 unsafe 求解；Pluribus 每轮从本轮开始做 unsafe 搜索 | 没有 safe gadget、gift、depth-limit、延续策略；只到河牌 |
| 信念 / range | 用前三街固定基线策略的类别似然对均匀先验做 Bayes 更新，为双方（包括自己）各求一份公开信念 range；先为 range 内所有手牌求策略，再执行实际手牌 | Pluribus：为每个玩家（含自己）维护 1,326 种底牌的分布，按蓝图/上次搜索做 Bayes 更新；"balanced" 地为所有可能手牌计算策略（M-p.5；S-p.22–23） | 前三街是基线规则，不是蓝图；按尺寸无关的类别似然；对其他对手是错设模型；range 要抽样到 150 次抽取才能在决策时求解 |
| turn + river 联合求解 | 固定 turn 公共牌和给定 range，在一个子博弈里联合优化 turn 与 48 张河牌下的 river 策略：全宽向量 CFR（DCFR），river 按河牌批量计算，机会概率 1/40 | Libratus 从 turn 开始求解子博弈，一直解到终局，子博弈内不做牌力抽象，求解器是 CFR+（Sci p.2–3；SM p.16、p.19） | 精确核对只在小 range、SPR ≤ 2、加注上限 1/1 上做过；2026-10-25 起按河牌做容斥，可解到每方数千手；range 是输入（agent 里是 baseline-v1 后验的抽样），不来自蓝图；无 safe 增广；对拼接法做了对照测量 |
| 联合策略接入决策 | `turn_river_solver` 在每手第一次 turn 决策时实时求解 turn + river，river 读同一个解，树外动作重解 | Libratus 在 turn 和 river 实时做嵌套子博弈求解，对手的树外动作会触发新的求解（Sci p.3–4） | unsafe；range 来自 baseline-v1 后验的抽样，而不是蓝图；没有 gift/margin；river 的树外动作改为独立 river 重解，日志标明 |
| 树外动作 | 从当前状态重解：range 按前一解的树内动作概率加权，树外动作本身不更新 | Pluribus 把该动作加入子博弈，从本轮开始重新搜索（S-p.23，Alg. 2）；Libratus 在 turn/river 对树外下注做 safe 重解 | 不从本轮开始重解，也没有 safe 保证 |
| 卡牌移除 | 稠密矩阵，或按牌力排序前缀和 + 15 子集容斥（线性复杂度） | 论文未描述；是 Hold'em 常用技巧推广到 4 张牌 | 只适用于两人；三人及以上的联合卡牌移除没做 |
| 评测 | 子博弈内精确 exploitability（两人零和小博弈才可能）；整局用 duplicate 座位轮换 | duplicate 来自 Libratus；Pluribus 用 AIVAT | 没有 AIVAT；对手只有基线 bot |
| 收益 | 线性净筹码，起始底池沉没，常和 | 同 Libratus/Pluribus 的筹码收益 | 不用底池平方奖励（AMP3 那种设计） |

## 6. 只在两人零和或某个抽象子游戏里成立的结论

- 本项目 exploitability 数字的成立条件：单挑、无抽水、给定范围、给定离散尺寸树、给定公共牌。它们不是整局 PLO 的 exploitability，也不覆盖树外尺寸。
- CFR、CFR+、DCFR 的收敛保证，以及 MCCFR 的概率性保证，只适用于两人零和。多人求解没有这类保证（Pluribus M-p.2–3 明说）。
- Libratus 的 Theorem 1 和 gift 推理只在两人零和、perfect recall 下成立；Libratus 实际用估计值算 gift，已不在 NeurIPS 定理覆盖范围内（libratus_notes C4）。
- Pluribus 的胜率只对应 6 人 NLHE、每手 100bb 重置和那批职业选手；它没有个体对手学习。
- 有抽水时博弈不再严格常和，exploitability 的解释也随之失效【评估】。

## 7. PLO 相关工作：按变体区分

- **标准 PLO4（4 张底牌，恰好 2+3，pot-limit）**
  - GTO Wizard（2026-05-12）自述：精确表格求解 turn/river，神经网络估算下一街 EV，按街求解；河牌 < 0.1% pot；turn 基准平均 EV 损失 0.14% pot。全部是厂商自述，未独立核实。
  - GTO Wizard 2026-07 更新：单挑可从翻前到河牌自定义求解；多人只有预解好的翻前。
  - MonkerSolver：分桶抽象，河牌只区分 ≥3 张同花公共牌的花色；官方承认无法计算 exploitability。
  - PokerRL-Omaha：代码自称支持 2–6 人，但审计发现评估器不强制 2+3、pot limit 默认关闭、多人最小加注和零头分配有错，也没有训练结果。只能当规则测试清单用，不能当依赖。
- **PLO4 翻前表示**：Abstraction Agent 只对 16,432 个翻前同构类做 LLM 特征 + k-means（K=30）。没有 PLO 的 exploitability，也没有 postflop；论文所谓"发现"的特征大多已写在提示配置里。可靠的定量结果只在 HUNL turn 子博弈上（DCFR(1.5,0,2)，2,000 次迭代）。
- **Toy PLO（TPLO）**：Oscarsson 2024 学位论文（§4.1 p.25）与 2025 ISI 论文（§IV-A p.117）。
  - **游戏**：单挑，12 张牌（J–A 三种花色），3 轮下注，2 张公共牌。TPLO1/2/3 分别是 1/2/3 张底牌（12/66/220 种私牌）。
  - **下注与筹码**：只允许一种 pot 尺寸的下注；双方各下 100 前注，筹码 5,000。
  - **成牌规则**：底牌与公共牌自由组合，即 Hold'em 式，不是"恰好 2+3"（p.25 明说，代码一致）。代码只排高牌、对子、两对、三条四个等级。
  - **与 PLO4 的距离**：牌堆、底牌数、街数、成牌规则、牌型、尺寸、人数全都不同，实际上不是 Omaha。
  - **算法**：Student of Games 的简化实现。固定大小子树代替 GT-CFR，只有价值网络，没有策略头；代码更接近 DeepStack 式重解加 sound self-play。
  - **结果**：TPLO 没有计算 exploitability，只报告经运气校正的胜率（Table 5.1 p.35），对手是随机策略和自身早期快照，没有外部基线，也没给种子数和评测局数。
  - **结论**：隐藏信息越多学习越难，每个训练周期的计算量"看起来"次线性增长（2025 p.120）。最多只测到 220 种私牌，标准 PLO4 有 270,725 种。
  - **2025 论文**：与学位论文用同样的游戏、超参数和结果（Table III），没有新实验，而且没写成牌规则。只读 2025 版会误以为用的是 Omaha 规则。
  - **可借鉴的**：只改变底牌数量的受控设计（需要补上 exploitability、多个种子、匹配的计算预算），以及把公共信念状态（双方完整范围）作为网络输入的表示方式。
  - **不能引用为 PLO4 结果的**：其中任何数字或"次线性"结论。
- **Omaha Hi-Lo**：RSPSA 2006 的 MCRAISE 对手模型（交接包结论，本轮未重读）。它不是 high-only PLO4。

## 8. 未核实清单

- CFR+（Tammelin 2015）、MCCFR（Lanctot 2009）原文本轮没有重读。DCFR 原文的定义已核对（见 §0）。
- Libratus 未披露的内容：尺寸列表、聚类特征、蓝图迭代数、剪枝常数、比赛中实际用的 augmented 目标函数、子博弈出牌用平均还是当前策略。
- Pluribus 未披露的内容：总迭代数、"子博弈较大/处于早期"的门限、搜索迭代数、卡牌移除的实现方式。
- PLO 方差比 NLHE 大，这是业内经验，未核实。
- 所有厂商的精度数字。
