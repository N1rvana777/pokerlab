# Pluribus 一手阅读笔记 — Brown & Sandholm, "Superhuman AI for multiplayer poker", Science 365:885–890 (2019)

> 用途：PokerLab（PLO4，2–8 人）研究。A–G 节内容全部来自本人实际读到的全文（正文 + 补充材料），每条带页码；以意译为主，只保留极少量短引语。
> H 节是**本人评估（Assessment），不是论文内容**。凡是凭记忆补充的内容，一律标注 **UNVERIFIED (from memory)**。
> 阅读日期：2026-10-23。

---

## 0. 来源、文件与读取记录

| 项 | 正文 (main) | 补充材料 (supp) |
|---|---|---|
| 请求 URL | https://noambrown.github.io/papers/19-Science-Superhuman.pdf | https://noambrown.github.io/papers/19-Science-Superhuman_Supp.pdf |
| 实际读取 URL（curl -L 跟随重定向后） | https://noambrown.com/papers/19-Science-Superhuman.pdf | https://noambrown.com/papers/19-Science-Superhuman_Supp.pdf |
| HTTP / Content-Type | 200 / application/pdf | 200 / application/pdf |
| 文件大小 | 526,902 bytes | 577,404 bytes |
| SHA-256 | 04e3d2bf9baf601feebd703cd27838f0eb89310fdf02324c68fcc4fe842cd4c5 | c135897c574faad6fa70e943ae9d61ae0d4c189a6e0ed3e74fff596aba8d7535 |
| 页数 | 7 页（6 页正文 = Science pp. 885–890，外加 1 页 Science 的 article-tools 元数据页） | 30 页（`file` 工具误报为 10 页；用 pdftotext 逐页确认共 30 页） |
| 本地路径 | C:\Users\n1rva\AppData\Local\Temp\claude\C--Users-n1rva--claude-spares-spare-T7S9v9\6a9e7026-d511-4ad0-b9f7-d36a25f22f9c\scratchpad\papers\pluribus\pluribus_main.pdf | 同目录 pluribus_supp.pdf |

正文 PDF 是 Science 的重印版（页眉写明 2019-09-02 从 science.sciencemag.org 下载）；DOI 10.1126/science.aay2400；2019-07-11 在线发表 (M-p.6, M-p.7)。

**页码约定**
- `M-p.N` = 正文 PDF 第 N 页 = Science 印刷页 884+N（N = 1..6）。M-p.7 是 Science 元数据页。
- `S-p.N` = 补充材料 PDF 第 N 页。补充材料页脚印刷页码 = N−1（S-p.1 是封面，没有页码）。

**读取方式**：Read 工具无法渲染 PDF（系统没有 pdftoppm，也没有任何 Python PDF 渲染库），所以我用 pdftotext 4.00（Xpdf）提取文本，并用 raw、`-layout`、`-table`、`-lineprinter` 几种模式交叉核对。37 页全部逐页读完。提取后的文本在 `scratchpad\research\pluribus_text\`（含 `pages\` 下的逐页文件）。

**没能读到 / 没有读的部分**
1. Fig.1–5 的图形本身没看到（只读了图注）。Fig.5 胜率曲线上的逐日数值没有读出。
2. Data File S1（S-p.1 提到的 zipped archive）没有下载，也没有读。
3. 被引用的原论文都没读：Linear CFR (ref 38)、pseudo-harmonic 动作映射 (ref 39)、depth-limited search / Modicum (ref 41)、vector/public-chance-sampling CFR (ref 42)、AIVAT (ref 44)、抽象方法 (ref 26–28, 48) 等。凡涉及这些文献内部细节的内容，都标注为 UNVERIFIED。
4. 公式和伪代码的缩进是从文本提取结果复原的（`-table` 模式缩进最清楚），没能对照渲染后的 PDF 目测核对。数学符号（Σ、分数线）在提取时被拆散，但几种模式的结果一致。Table S1 在 `-layout` 模式下列错位，`-table` 和 `-lineprinter` 两种模式一致给出了正确对齐（见 E 节）。

---

## A. Abstraction（抽象）

正文：Pluribus 使用两种抽象，action abstraction 和 information abstraction，blueprint 和实时搜索都会用到 (M-p.2)。补充材料：两个 infoset 只有在 action-abstraction 序列相同、并且落在同一个 information-abstraction bucket 时，才被归为一类 (S-p.13)。

### A1. Action abstraction
- 每个决策点考虑的下注尺寸数量在 **1 到 14 个**之间，随局面而变 (M-p.2；S-p.13 说的是 "1–14 个 raise sizes")。
- 所有加注尺寸都是 **pot 的分数**。候选尺寸是**人工选定**的，依据是早期版本 Pluribus 以显著正概率使用过哪些尺寸 (S-p.13)。
- 各轮粒度不同 (S-p.13)：
  - 第 1 轮（preflop）的 blueprint 动作抽象特别细，原因是这一轮通常不做实时搜索。
  - 第 2 轮（flop）较粗。
  - 第 3、4 轮（turn/river）：本轮第一次加注最多 3 种尺寸（0.5×pot、1×pot、all-in），之后的加注最多 2 种（1×pot、all-in）。
- 实时搜索中，加注尺寸在 **1–6 个**之间 (S-p.13–14)；另一处写的是"通常不超过 5 个" (S-p.23)。
- 只要 fold/call 合法，blueprint 和搜索里都一定包含 (S-p.14)。
- blueprint 动作抽象共有 **664,845,654** 个 action sequences，训练中实际只遇到过 **413,507,309** 个 (S-p.14)。
- 搜索子博弈里的 action sequences（只计玩家动作，不计 chance）在 **100–2,000** 之间 (S-p.14)。
- 规则背景：每手每人 $10,000 筹码，盲注 $50/$100，相当于 100bb；每轮第一次加注至少 $100，之后每次加注至少等于前一次加注的增量；不能超过剩余筹码 (S-p.5)。
- 对手在 blueprint 树外的下注（off-tree）怎么处理，见 D 节。

### A2. Information (card) abstraction
- 实战中，信息抽象**只用于推理未来轮次**，当前所在轮从不使用；离线 self-play 同样使用信息抽象 (M-p.3)。
- **Blueprint** (S-p.14)：
  - 只在第 1 轮用 lossless abstraction（169 类）。
  - 作者给出的参考数字：如果每轮都用 lossless，各轮的 strategically unique information situations 分别是 169 / 1,286,792 / 55,190,538 / 2,428,287,420。
  - 第 2–4 轮各用 **200 个 buckets** 的 lossy abstraction，方法是基于 domain-specific features 的 k-means 聚类（ref 26）。
  - 第 2 轮平均每个 abstract infoset bucket 覆盖 **6,434** 个 infosets (S-p.15)。本人验算：1,286,792 / 200 ≈ 6,434。
- **实时搜索** (S-p.14–15, S-p.23)：
  - 当前轮用 lossless。
  - 之后各轮用 lossy，每轮 **500 个 buckets**。
  - 这些 buckets **按每个 flop 单独计算**，算法考虑手牌的 future potential（ref 28），把 potential-aware abstraction（ref 48）和基于 earth-mover distance 的聚类（ref 27）结合起来。
- Blueprint 只在第 1 轮直接用来出牌。这一轮决策点少，所以 blueprint 可以不做信息抽象，并且容纳很多动作 (M-p.4)。

---

## B. Blueprint 算法

### B1. 算法变体
- 正文：MCCFR 的一种形式，在博弈树中采样动作，而不是每次迭代遍历整棵树 (M-p.3)。每次迭代指定一个 traverser，只更新它的 current strategy。实现是 depth-first 遍历 (M-p.2, Fig.2 图注)。
- 补充材料明确写的是 **external-sampling MCCFR**（refs 29, 35）加两项改进 (S-p.15)。伪代码标题是 "MCCFR with Negative-Regret Pruning" (S-p.17)。
- 补充材料称之为 **Linear MCCFR**：作者说以前发表过但从未在大规模上实现和测试过，估计带来约 **3 倍**加速 (S-p.4)。

### B2. Linear CFR 加权（discounting）
- 正文：Linear CFR 给第 T 次迭代的 regret 贡献赋权 T，所以第一次迭代的影响按 1/Σ_{t=1..T} t = 2/(T(T+1)) 衰减；原始 CFR 是按 1/T 衰减。这样实际中策略改善更快，worst-case regret 上界几乎不变 (M-p.3)。只在早期迭代使用，因为后期做折扣乘法的时间成本不值得 (M-p.3)。
- 补充材料的具体参数 (S-p.15)：
  - 在训练的**前 400 分钟**，对 regrets 和 average strategy 两者都做 linear weighting。
  - 每 **10 分钟**把两者都乘以 d = (T/10)/(T/10+1)，其中 T 是训练开始以来经过的分钟数。
  - 400 分钟后停止折扣。
  - ref 38 在两人 NLTH 子博弈上的实验显示，这一改动带来约 3 倍收敛加速。
- 伪代码中写成 `d ← (t/DiscountInterval)/(t/DiscountInterval+1)`，DiscountInterval = 10 分钟；条件是 `t < LCFR Threshold` (S-p.17)，其值伪代码里没写，正文说是 400 分钟。

### B3. Negative-regret pruning（负 regret 剪枝）
- 前 **200 分钟**不剪枝。之后在 **95%** 的迭代中，regret 低于 **−300,000,000** 的 traverser 动作不展开 (S-p.15)。有两个例外，总会展开：
  - 处于最后一轮（river）的动作；
  - 直接通向终局节点的动作。
- 其余 **5%** 的迭代展开全部动作 (S-p.15)。
- 是否剪枝按**整次迭代**决定（一次随机数），而不是逐个动作决定，这样更省（减少随机数调用）(S-p.4)。
- 不在最后一轮剪枝的原因：最后一轮剪枝得不到"相当于加细 card abstraction"的好处。终局动作不剪是因为它们本来就便宜 (S-p.4)。
- 作者估计这些改动带来约 **2 倍**加速 (S-p.4)。
- 剪枝还有一个效果：相当于更细的信息抽象。某个 bucket 里很多 infoset 只有 5% 的时间被访问到，于是 bucket 的策略更侧重强策略下真正会遇到的 infoset (S-p.15–16)。6 人局里这个好处更大，因为好的策略在早期会弃掉大多数手牌 (S-p.16)。
- 伪代码里剪枝门限 C = −300,000,000；剪枝条件是 `t > PruneThreshold (200 min)` 并且 `q ≥ 0.05` (S-p.17, S-p.19)。**伪代码没有写出"最后一轮 / 终局动作不剪"这两个例外**，例外只在正文文字里出现 (S-p.15)。

### B4. Regret 存储、下限与内存
- regret 用 **4-byte 整数**存，而不是 8-byte double (S-p.16)。
- 每个动作的 regret 有**下限 −310,000,000**。作用是让先被剪枝、后来变好的动作更容易"解除剪枝"，同时防止整数溢出 (S-p.16)。
- **延迟分配**：某个 action sequence 第一次被遇到时才分配它的 regret 内存（第 1 轮除外，第 1 轮很小，一开始就分配）。内存减少一半以上 (S-p.4–5, S-p.14)。

### B5. Average strategy、current strategy 与 snapshots（按轮）
- 作者明确说：6 人扑克中 CFR 的 average strategy 不保证收敛到 Nash equilibrium，所以**用 average 还是用 current strategy，没有理论上的优劣** (S-p.16)。
- **第 1 轮（preflop）**：训练"最初 800 分钟之后"，存下第 1 轮的 average strategy，作为第 1 轮的 blueprint (S-p.16)。伪代码里 average strategy φ 只为第 1 轮的 infoset 分配和更新（见 C 节）。
- **第 2–4 轮**：最初 800 分钟之后，每 **200 分钟**对 current strategy 拍一个 snapshot；这几轮的 blueprint 是这些 snapshots 的平均（ref 32）(S-p.16)。
- snapshots 存在磁盘上，而不是在内存里维护 average strategy。这样内存减少近一半，每次 MCCFR 迭代也更便宜 (S-p.16)。
- **歧义（本人标注）**：文字说 800 分钟之后才"stored" 第 1 轮的 average strategy；但伪代码显示 φ 从 t=1 起就累加（每 10,000 次迭代一次），并在 LCFR 阶段被折扣，**没有显示在 800 分钟时清零**。两种读法（从头累加，或丢弃前 800 分钟）论文没有说清楚。

### B6. 总计算量与内存（blueprint）
- 64 核服务器训练 **8 天**，共 **12,400 CPU core hours**，内存 **< 512 GB** (M-p.3)。
- 按当时云 spot 实例价格约 **$144** (M-p.3)。本人推算：约 $0.0116/core-hour；8×24×64 = 12,288 core-hours，与 12,400 一致。
- 硬件：Pittsburgh Supercomputing Center 的 Bridges 超算上一个 64 核大共享内存节点（4 颗 16 核 Intel Xeon E5-8860 v3）。节点有 3 TB 内存，实际用量 < 0.5 TB (S-p.12)。全程没用 GPU (S-p.13)。
- blueprint 抽象规模的设定目标：实战时整个程序（含压缩后的 blueprint）能在 ≤128 GB 内存的机器上运行 (M-p.4)。
- **论文没有给出总迭代次数。** 本人推算：8 天 ≈ 11,520 分钟。按 800 分钟后每 200 分钟一个 snapshot，大约 53 个 snapshot；这是推算，论文没写。

---

## C. 补充材料伪代码（Algorithm 1, S-p.17–19；Algorithm 2, S-p.26）

符号：R(I,a) 是累计 regret；φ(I,a) 是 average-strategy 计数器（**只为第 1 轮的 infoset 分配**）；σ 是对 R⁺ 做 regret matching 得到的 current strategy；u_i(h) 是终局收益。最终策略 = φ(I) 归一化（第 1 轮）(S-p.17)。

### C1. Algorithm 1 逐步（本人意译）
```
MCCFR-P(T):                                   # External-Sampling MCCFR with Pruning
  初始化：对每个玩家 i 的每个 infoset I、每个 a：R(I,a)=0；若 I 在第 0 轮(preflop)：φ(I,a)=0
  for t = 1..T:
    for 每个玩家 Pi:                          # 每次迭代轮流让每个玩家各当一次 traverser
      if t mod StrategyInterval == 0:         # StrategyInterval = 10,000（单位未写明，按循环变量应是迭代次数）
          UPDATE-STRATEGY(root, Pi)
      if t > PruneThreshold:                  # 200 分钟
          q ~ U[0,1)
          if q < 0.05: TRAVERSE-MCCFR(root, Pi)      # 5%：不剪枝
          else:        TRAVERSE-MCCFR-P(root, Pi)    # 95%：剪枝
      else: TRAVERSE-MCCFR(root, Pi)
    if t < LCFRThreshold and t mod DiscountInterval == 0:   # DiscountInterval = 10 分钟；文字说 LCFR 共 400 分钟
      d = (t/DI) / (t/DI + 1)
      对所有玩家、infoset、动作：R *= d；φ *= d
  return φ

CALCULATE-STRATEGY(I):  regret matching。sum = Σ_a R⁺(I,a)；sum>0 时 σ(I,a)=R⁺(I,a)/sum，否则均匀 1/|A(I)|

UPDATE-STRATEGY(h, Pi):        # 只维护 preflop 的 average strategy
  若 h 是终局、Pi 已不在手中、或 betting_round(h) > 0：return
  chance 节点：按 chance 概率采样一个结果，递归
  Pi 的节点：σ = regret matching(R(I))；按 σ 采样一个 a；φ(I,a) += 1；递归 h·a
  其他玩家的节点：遍历所有动作 a，逐个递归            # 注意：与 regret 遍历的采样方式正好相反

TRAVERSE-MCCFR(h, Pi):         # 更新 Pi 的 regret
  终局：return u_i(h)
  Pi 已弃牌：return TRAVERSE(h·0)                    # 剩下的动作与 Pi 无关，只走第 0 个动作
  chance：按 chance 概率采样一个结果，递归
  Pi 的节点：σ = regret matching；v(h)=0
            对每个 a：v(h,a)=TRAVERSE(h·a)；v(h) += σ(I,a)·v(h,a)
            对每个 a：R(I,a) += v(h,a) − v(h)
            return v(h)
  对手的节点：对手 infoset 上的 σ = regret matching（用 current strategy，不是 average）；
            采样一个 a，递归

TRAVERSE-MCCFR-P(h, Pi):       # 同上，只是 Pi 节点只展开 R(I,a) > C 的动作（C = −300,000,000）
  未展开的动作不计入 v(h)，其 regret 本次不更新
```

伪代码层面的要点（都是从伪代码直接读出的事实）：
1. External sampling 的结构：traverser 节点展开所有动作；对手节点和 chance 节点各采样 1 个结果。对手用的是由当前 regret 即时算出的 current strategy。
2. regret 增量就是 v(h,a) − v(h)，**伪代码中没有显式的 reach-probability 或 importance weight**。Linear 加权是通过周期性地把 R 和 φ 乘以 d 来实现的，而不是给每次增量乘权重。
3. average strategy 只对 preflop 维护，用 "+1 计数器" 实现：每 10,000 次迭代走一次 UPDATE-STRATEGY，在 traverser 自己的节点上采样动作，在对手节点上遍历全部动作。postflop 的 average 靠磁盘 snapshots（文字，S-p.16）。
4. 伪代码混用了单位：t 是迭代计数，但 PruneThreshold 和 DiscountInterval 标的是分钟。
5. 文字里提到、但伪代码没写出的细节：剪枝例外（最后一轮、终局动作）、regret 下限 −310,000,000、4-byte 整数存储、延迟分配、snapshot 机制。

### C2. Algorithm 2：Nested search（S-p.26，本人意译）
```
初始化：I ← 游戏开始时的 infoset；G_root ← G(I)（I 所在的 public node）；σ ← σ_blueprint
OpponentTurn(a):                        # 对手选了动作 a
  若 a 不在 infoset I 的动作抽象里：
      对 G(I) 中每个节点 h：AddAction(h, a)       # 把 a 加成合法动作
      σ ← Search(G_root)                          # 从本轮根重新搜索
  I ← I·a；CheckNewRound()
OurTurn():
  a ~ σ(I)；frozen(I) = True                      # 之后重算子博弈时 σ(I) 不再改变
  I ← I·a；CheckNewRound()
CheckNewRound():
  若 BettingRound(G(I)) > BettingRound(G_root)：G_root ← G(I)；σ ← Search(G_root)
```
注意：Algorithm 2 是通用框架。它没有画出第 1 轮"偏离 ≤$100 或 >4 人时用 pseudo-harmonic 映射而不搜索"的分支，也没有区分"按 final iteration 出牌"和"用 weighted average 更新 σ"（这两点见 D 节）。

---

## D. 实时搜索（Real-time search）

### D1. 何时搜索
- **第 1 轮**：对手的加注尺寸与 blueprint 里任一尺寸相差**超过 $100**，并且手中剩下**不超过 4 名玩家**时，才做实时搜索 (S-p.16 → S-p.20)。否则用**随机化 pseudo-harmonic action translation** 把这个加注映射到附近的尺寸，然后当作对手下了映射后的尺寸，继续按 blueprint 打 (S-p.20)。作者称 pseudo-harmonic 在已知动作映射算法中经验上 exploitability 最低 (S-p.20)。正文也说：第 1 轮略微偏离树的下注，用 pseudoharmonic mapping 取整到树上尺寸 (M-p.4)。
- **第 2、3、4 轮总是搜索** (S-p.20)。正文：Pluribus 只在第一轮按 blueprint 打 (M-p.4)。

### D2. 子博弈根与 beliefs
- 根不是单个节点，而是 public state G 上的一个概率分布。形式上，根是一个 chance node，通向 G 中节点 h 的概率是 π^σ(h) / Σ_{h'∈G} π^σ(h') (S-p.20–21)。
- σ 的取值：本手第一次搜索时用 blueprint，之后用上一次搜索的结果 (M-p.4 Fig.4 图注；S-p.22)。
- 只有两种情况下，从根解剩余博弈才能得到最优的后续策略：根分布正确，并且只剩两名玩家；或者剩余玩家都打同一个解 (S-p.21)。Pluribus 不知道别人的真实策略，只看得到动作 (S-p.21)。
- **Unsafe search**：Pluribus 先算出"自己处在对手位置时会怎么打"，然后假设对手就是这么打的 (S-p.21)。
  - 即使在两人零和博弈里，unsafe search 也没有理论保证，有时会产生高度可被剥削的策略。
  - safe search 在两人零和博弈中有可证明的保证，但实际对战表现往往不如精心设计的 unsafe search。
  - unsafe 的额外好处：不必为概率为零的手牌算策略。6 人局里大多数手牌第一次行动就以 100% 概率弃掉，所以快了约 **4 倍** (S-p.21)。
- **新型 nested search** (S-p.3, S-p.21–22)：
  - 总是从**当前下注轮的开始**求解，而不是从最近的决策点开始。
  - 本轮中 Pluribus 已经做过的动作，其策略保持固定。
  - 允许其他玩家在本轮任何位置（包括当前决策点之上）改变策略，以此降低 unsafe search 被剥削的风险。
  - 依据：ref 52 的实验表明，如果根 public state 紧跟在一个分支因子很大的 chance node 之后（这种 nested search 总是如此），unsafe search 在两人零和博弈中通常得到低 exploitability 的策略 (S-p.22)。
- **Beliefs** (S-p.22)：
  - 从局外观察者的角度，为每名玩家（**包括 Pluribus 自己**）维护一个底牌对的分布，共 C(52,2) = 1,326 种，初始各为 1/1326。
  - 每轮结束时，把新一轮开始处的 public state 设为新子博弈的根，并按 σ 用 Bayes 规则更新每名玩家的分布。
  - σ 从搜索的 **weighted average strategy** 更新（S-p.23，见 D4）。
- **"Balanced"**：Pluribus 记录自己按策略以每种可能手牌到达当前局面的概率；不管实际拿什么牌，先算出所有手牌的平衡策略，再只对实际手牌执行动作 (M-p.5)。

### D3. Depth limit 与 leaf continuation strategies
- 叶节点位置 (S-p.22)：
  - 第 1 轮搜索：子博弈延伸到本轮结束，叶节点在第 2 轮开始处的 chance node。
  - 第 2 轮搜索、且本轮开始时**多于两名玩家**：叶节点在第 3 轮开始处的 chance node，或**第二次加注动作之后**，取较早者。
  - 其他所有情况：一直延伸到游戏结束。
- 叶节点处，每名还在手中的玩家**同时**从 **k = 4** 个 continuation strategies 中选一个，也可以选它们的任意混合。同一 infoset 内不可区分的叶节点必须做相同选择。这个选择本质上就是子博弈里的又一个动作，由搜索算法（改进版 MCCFR）来选 (M-p.4–5；S-p.24–25)。
- 叶节点的值：按各玩家所选的 continuation strategies 把剩余博弈 rollout 出来估计 (M-p.4 Fig.4 图注)。
- 4 个 continuation strategies 都是 blueprint 的偏置版本 (S-p.25；M-p.5)：
  1. 原始 blueprint；
  2. fold 偏置：所有决策点的 fold 概率 ×5 后重新归一化；
  3. call 偏置：call 概率 ×5 后归一化；
  4. raise 偏置：所有 raise 动作概率 ×5 后归一化。
- 压缩：在每个 abstract infoset 上按分布采样一个动作，只存这个动作（用最少的比特），不存 regret 或概率。作者认为偏差不大，因为同一 abstract infoset 被多次遇到的几率很低 (S-p.25)。
- 如果对手早先做过 blueprint 动作抽象里没有的动作，子博弈的叶节点可能在 blueprint 里不存在。此时用**确定性 pseudo-harmonic 映射**，映到 blueprint 抽象中最近的节点 (S-p.25)。
- 背景 (S-p.2)：depth-limited search 是让 6 人扑克可行的最重要改进。Libratus 一旦搜索就总是解到游戏结束（从第 3 轮起，有时更早）；而玩家数会让子博弈规模指数增长，没有 depth limit 时，在 flop 上对多于 3 名玩家做有益的实时搜索很可能不可行。
- 与旧工作的差别 (S-p.3, S-p.25 脚注)：在旧的 Modicum（ref 41）中只有对手能选 continuation，searcher 只能用 blueprint，结果偏保守。现在双方都能选；作者称这在两人零和中同样理论 sound，而且比旧的"惩罚对手"做法更有效、更简洁。

### D4. 子博弈求解算法
- 两种 CFR 视情况选用 (M-p.5；S-p.22–23)：
  - 子博弈**较大或处于游戏早期**：用 **Monte Carlo Linear CFR**，与 blueprint 相同。
  - 其他情况：用**向量化（vector-based）的 Linear CFR**，只采样 chance 事件，即每个线程采样一组公共牌（ref 42）。
  - 论文没有给出"较大 / 早期"的具体门限。
- 两种情况下，**实际出牌都按最后一次迭代（final iteration）的策略**，而不是 weighted average；但 σ（用于 beliefs）按 weighted average 更新 (S-p.23)。理由：final iterate 能避开 average 中没被完全清除的差动作。代价可能是 exploitability 上升，但作者称实际中 final iterate 已经足够难以预测，剥削它不可行 (S-p.23)。
- 时间：单个子博弈搜索 **1–33 秒**，视局面而定。与自身副本对打时平均每手 **20 秒**，大约是人类职业玩家速度的两倍 (M-p.5)。
- **论文没有报告搜索迭代次数，也没有说明搜索中的 Linear 折扣日程。**

### D5. Off-tree 动作、重新求解与冻结
- 对手的动作不在子博弈动作抽象里时：把它**作为合法动作加入子博弈模型**，然后从根（通常是本轮开始）**重新搜索**。新一轮到来之前根不变 (S-p.23；Algorithm 2 第 5–8 行，S-p.26)。
- 问题：重新搜索可能和之前已经打过的动作不一致。作者举例：根处有两个等价动作 A、B，第一次解选了 A，第二次解改选 B，那么 A 之后的新策略可能毫无意义 (S-p.23–24)。
- 解决办法 (S-p.24)：
  - 只冻结 Pluribus **在本子博弈中已经选过的动作**的概率，而且**只针对实际手牌**，其他可能手牌不冻结；对手的动作概率也不冻结。
  - 不冻结所有前序决策点的原因是：冻结对手决策点会降低对"对手换策略"的鲁棒性。
  - 一轮结束、根移到新一轮开始时，新根之前所有 infoset 的策略等于全部被冻结。

---

## E. 评估（Evaluation）

- 指标：mbb/game，即每千手赢多少个大盲 (M-p.5)。所有实验都用 **AIVAT** 降方差，并在 95% 置信水平上做**单尾 t 检验**，判断 Pluribus 是否盈利 (M-p.5；S-p.8)。每一手都当作 i.i.d. 样本；作者承认人类可能调整策略，这个假设未必严格成立，但它是该领域的标准假设 (S-p.8)。
- **筹码重置**：每手每人都从 $10,000 开始（100bb，盲注 $50/$100）。因为每手起始筹码相同，每一手可以作为独立样本 (S-p.5)。座位按手轮转 (S-p.6)。
- **AIVAT** (S-p.10–12)：
  - 修改过以支持多于两人的博弈；估计无偏，实际方差降低约 **9 倍**。
  - 在 Pluribus 的决策点和 chance 节点上用"采样值 − 基线 + 期望基线"做校正，不能用于人类决策点。
  - 利用 Pluribus 对整个 range 的策略，可以进一步降方差。
  - 每个 Pluribus 副本独立运行 AIVAT；人类胜率取各 AI 胜率平均值的相反数。
- **5H+1AI** (M-p.5–6；S-p.7–9)：
  - 13 名职业玩家，每人职业生涯赢过 100 万美元以上。12 天打了 10,000 手，每天从志愿者中选 5 人。
  - 玩家使用固定化名，彼此不知道对方身份。作者没有隐藏哪一个是 Pluribus。
  - 每天开始时随机分配座位；每天打 3–8 小时（通常 4 小时）；建议同时开 4 桌，后来上限改为 6 桌；4 桌时约每小时 180 手；决策不限时，不许用辅助软件 (S-p.6–7)。
  - 奖金：$50,000 按表现分配。每手按 $(1+0.005X) 支付，X 是调整后的降方差胜率，截断在 ±120 mbb/game，所以每手在 $0.40–$1.60 之间 (M-p.5；S-p.7–8)。
  - 结果：AIVAT 后 Pluribus **+48 mbb/game（SE 25）**，单尾 **p = 0.028** (M-p.5–6)。补充材料给出精确值 **47.7（SE 25.0）**。另有 13 手额外牌局未计入；计入后为 50.9 mbb/game (S-p.9)。
  - 个人胜率无法用 AIVAT 估计。Table S1 用较弱的降方差方法（减去按 blueprint 算的、给定所有人底牌时的期望值），作者声明从中**得不出任何关于个人的有意义结论** (S-p.9, S-p.27)。Table S1 正确对齐后（`-table` 与 `-lineprinter` 两种模式一致）：

    | 化名 | 手数 | 胜率 (mbb/game) | SE |
    |---|---|---|---|
    | A | 9,121 | 141.8 | 85.8 |
    | B | 7,512 | −86.7 | 87.7 |
    | C | 6,713 | −49.9 | 121.9 |
    | D | 6,055 | 4.9 | 122.2 |
    | E | 5,510 | 101.5 | 121.8 |
    | F | 4,483 | −59.7 | 108.6 |
    | G | 2,560 | −126.9 | 133.5 |
    | H | 2,509 | 229.7 | 177.6 |
    | I | 1,535 | −131.7 | 229.9 |
    | J | 1,378 | 89.3 | 237.6 |
    | K | 1,365 | 141.0 | 284.1 |
    | L | 771 | −35.6 | 418.6 |
    | M | 488 | −492.5 | 515.4 |

    手数合计正好 50,000 = 5×10,000。
- **1H+5AI** (M-p.6；S-p.6, S-p.8–9, S-p.12)：
  - Chris Ferguson 和 Darren Elias 各打 5,000 手对 5 个 Pluribus 副本，在家按自己的时间打。最多 4 桌：Elias 通常 4 桌，Ferguson 通常 1 桌。
  - 报酬：参与费 $2,000；表现优于另一位人类再加 $2,000。
  - Pluribus 不针对对手调整，也不知道对手身份，所以副本之间不可能有意合谋 (M-p.6)。
  - 额外降方差：每手再由一个坐在人类位置上的 Pluribus 副本（"Control"）重放一遍，人类胜率减去 Control 的胜率（后者期望为 0）。如果人类和 Control 都在第一轮弃牌、且之前的动作序列相同，这手记为 0 (S-p.12)。
  - 结果：Pluribus **+32 mbb/game（SE 15）**，单尾 **p = 0.014** (M-p.6)；补充材料为 32.7（SE 14.9）(S-p.8–9)。
    - Elias：落后 40（SE 22），p = 0.033 (M-p.6)；补充材料 40.2（SE 21.9）(S-p.8)。
    - Ferguson：落后 25（SE 20），p = 0.107 (M-p.6)；补充材料 25.2（SE 20.2），**p = 0.106** (S-p.8)。正文和补充材料之间这一小处不一致，照原文记录。
  - 作者说，Ferguson 输得较少可能是方差、技术，以及/或者在不熟悉的困难局面偏向弃牌的保守策略所致 (M-p.6)。
- 本人验算（**非论文内容**）：
  - 用 z = 均值/SE 正态近似，单尾 p 与论文完全吻合（47.7/25.0 → 0.028；32.7/14.9 → 0.014）。如果改用**双尾**，5H+1AI 的 p ≈ 0.056，在 5% 水平**不显著**；1H+5AI 双尾 p ≈ 0.028。
  - 由 SE 反推，AIVAT 后每手标准差约 2.5bb（5H+1AI）和约 1.5bb（1H+5AI，叠加了 Control）。
  - 把 Table S1 的人类结果按手数加总，得 +725,415 mbb，即 5 名人类合计每手约 +72.5 mbb。如果这个弱降方差估计在各座位之间是零和的（本人推断，论文未说明），那么在这个口径下 Pluribus 约为 −72 mbb/game。这说明结论高度依赖 AIVAT，而这正是作者声明 Table S1 不可用于结论的原因。
- 论文中的策略观察 (M-p.6)：
  - limping 对小盲以外的位置都不是好选择；Pluribus 在 self-play 中曾尝试 limp，后来逐渐放弃了。
  - 但 Pluribus **不同意** "donk bet 是错误"的民间说法，它 donk 的频率远高于职业玩家。

---

## F. 计算与硬件

| 项 | 数值 | 出处 |
|---|---|---|
| Blueprint 训练 | 8 天，64 核，12,400 CPU core hours，< 512 GB | M-p.3 |
| Blueprint 节点 | PSC Bridges，1 个 64 核大共享内存节点（4 颗 16 核 Xeon E5-8860 v3），3 TB 中使用 < 0.5 TB | S-p.12 |
| 成本估计 | 按云 spot 价约 $144 | M-p.3 |
| 实战硬件 | 2 颗 Intel Haswell E5-2695 v3，< 128 GB (M-p.5)；即 1 个 28 核、128 GB 节点（2 颗 14 核）(S-p.12) | M-p.5, S-p.12 |
| GPU | 全程不用 | S-p.13 |
| 搜索耗时 | 每个子博弈 1–33 秒；自对弈平均每手 20 秒 | M-p.5 |
| 对比 | AlphaGo 1920 CPU + 280 GPU；Deep Blue 480 块定制芯片；Libratus 100 CPU | M-p.5 |
| 规模约束 | blueprint 抽象规模按实战 ≤128 GB 内存（含压缩 blueprint）设定 | M-p.4 |
| 各项创新的加速估计 | depth-limited search 让算力和内存需求"大概至少"降 5 个数量级 (S-p.2)；Linear MCCFR 约 3 倍 (S-p.4)；剪枝改动约 2 倍 (S-p.4)；unsafe search 约 4 倍 (S-p.21)；延迟分配省内存一半以上 (S-p.5)；snapshot 省内存近一半 (S-p.16) | — |

作者说，逐项测量每个创新的影响代价太高（方差和人类实验成本），所以只给估计值 (S-p.2)。

---

## G. 理论保证方面的表述（以及哪些只是经验结论）

**明确的理论表述**
1. 两人零和博弈中，Nash equilibrium 不会输（期望意义上，在对称或轮换位置的前提下）。多人博弈中，各玩家独立选择的 NE 组合起来未必是 NE，即 equilibrium selection 问题，作者用 Lemonade Stand Game 举例（Fig.1）(M-p.1–2)。
2. 多人或一般和博弈中求 NE 很难：两人非零和博弈没有已知的多项式算法；三人及以上零和博弈至少一样难（可以加 dummy player 归约）；即使近似也难；最好的完备算法只能处理每人少量策略的博弈 (M-p.1–2)。
3. 作者表态：6 人扑克的目标**不是**某个博弈论解概念，而是经验上持续击败人类 (M-p.2)。
4. 构造 Pluribus 所用的算法在两人零和以外**不保证收敛到 NE** (M-p.2)。CFR 的 average strategy 只在两人零和下保证收敛到 NE (M-p.3)。
5. CFR 在**所有有限博弈**中的保证 (M-p.3)：counterfactual regret 次线性增长，所以长期平均表现等于事后最优固定策略；并且会迭代消除严格劣势动作（ref 23）。
6. 由于 6 人局 average 不保证收敛，用 average 还是 current 没有理论优劣 (S-p.16)。
7. 只有在根分布正确，并且只剩两人或所有剩余玩家都用同一个解时，从根求解才最优 (S-p.21)。
8. **Unsafe search 即使在两人零和中也没有理论保证**，有时会产生高度可剥削的策略；safe search 在两人零和中有保证 (S-p.21)。
9. 双方都选 continuation strategy 的做法，在两人零和中理论 sound (S-p.3, S-p.25)。
10. 结论段：尽管多人博弈缺乏已知的强理论保证，精心设计的 self-play 加 search 依然能产生超人策略 (M-p.2, M-p.6)。
11. 很容易构造出多于两人的玩具博弈，让常用的 self-play 算法无法收敛到有意义的解（ref 22，Shapley）(M-p.2)。

**只有经验依据的说法**
- 对人类显著盈利（单尾 p = 0.028 / 0.014）(M-p.5–6)。
- Fig.5 的曲线比较平稳，"表明"人类没能找到可剥削的弱点 (M-p.5 图注)。
- 实际中 final iterate 足够难以预测，"剥削不可行" (S-p.23)。
- 从本轮开始求解的 nested unsafe search 能降低被剥削风险（依据是 ref 52 的两人零和实验）(S-p.22)。
- 各项加速倍数都是估计值 (S-p.2, S-p.4)。
- pseudo-harmonic 映射"经验上" exploitability 最低 (S-p.20)。
- 实验中 self-play 在多人博弈里"实际表现还不错"（引 ref 23）(M-p.2)。
- **论文没有报告任何 exploitability 数值**（多人局也无从定义或计算）。
- Pluribus 是固定策略，不做对手建模或剥削 (M-p.1)。

---

## H. 本人评估：迁移到 PLO4 引擎/求解器（2–8 人）

> **Assessment — 以下不是论文内容。** 下面的 PLO4 组合数是本人用 Burnside 引理（24 种花色置换）计算的，脚本在 `scratchpad\scripts\iso_counts.py`。同一脚本**完全复现了论文 S-p.14 的 NLHE 数字**（169 / 1,286,792 / 55,190,538 / 2,428,287,420），以此验证方法正确。

| 轮 | NLHE raw | NLHE 花色同构 | PLO4 raw | PLO4 花色同构 | PLO4/NLHE（同构） |
|---|---|---|---|---|---|
| preflop | 1,326 | 169 | 270,725 | **16,432** | ×97 |
| flop | 25,989,600 | 1,286,792 | 4,682,459,600 | **204,461,673** | ×159 |
| turn | 1.22e9 | 55,190,538 | 2.11e11 | **8,964,883,057** | ×162 |
| river | 5.62e10 | 2,428,287,420 | 9.27e12 | **389,802,959,832** | ×160 |

### H1. 可以基本直接迁移的部分（与具体游戏无关）
- External-sampling MCCFR、前期 Linear CFR 折扣（周期性乘以 n/(n+1)）、95% / 5% 的整次迭代负 regret 剪枝（最后一轮和终局动作不剪）、int32 regret 加下限、regret 延迟分配、preflop 用计数式 average 而 postflop 用磁盘 snapshot 平均。这些都是通用的工程手段。
  - 注意：−300M 和 −310M 这类门限依赖筹码单位（$10,000 筹码）和累计迭代量，PokerLab 必须按自己的单位重新标定。
- Nested unsafe search 的整套机制：从本轮开始求解；只冻结自己实际手牌已经做过的动作；off-tree 动作加入子博弈后重新求解；beliefs 按 Bayes 规则用 weighted average 更新；按 final iterate 出牌；为整个 range 计算平衡策略。
- k = 4 个偏置 continuation strategies（blueprint、fold ×5、call ×5、raise ×5），以及"每个 abstract infoset 只存一个采样动作"的压缩方式。
- Pseudo-harmonic 映射：preflop 用随机化版本，叶节点映射用确定性版本。pot-limit 下尺寸被限制在 [min-raise, pot] 之间，映射区间有界，反而更友好。
  - 公式 **UNVERIFIED (from memory)**（来自 ref 39，本次未读）：f_{A,B}(x) = ((B−x)(1+A)) / ((B−A)(1+x))，是把 x 映到较小尺寸 A 的概率，尺寸以 pot 分数表示。
- 评估方法：多人版 AIVAT（利用自己全 range 的策略和 chance 节点做基线校正）、Control 重放、按手 i.i.d. 的检验。PLO 的单手方差通常更大（**UNVERIFIED，常识判断**），所以更需要这些手段。

### H2. 必须修改的部分
1. **Range 规模**：每名玩家 270,725 个组合（Pluribus 是 1,326，大 204 倍）。
   - Beliefs 向量、vector-based CFR 的 range 运算、叶节点 rollout、showdown 都要按这个规模重新设计。
   - 每人 4 张、8 人局共 32 张底牌，card removal 和 blocker 效应强得多。论文的 beliefs 看起来是每名玩家一个边缘分布（局外视角，初始均匀），**论文没有说明多人之间的 card removal 怎么处理**；PLO 多人局里这种近似误差更大。
   - Unsafe search 跳过零概率手牌的收益在 PLO 中很关键。但 PLO 的 preflop 入池范围通常更宽（**UNVERIFIED，常识判断**），这个加速可能比 NLHE 的约 4 倍小。
2. **Card abstraction**：
   - preflop lossless 是 16,432 类（×97）。blueprint 可能还放得下，但每类被 MCCFR 访问的频率会低很多，收敛会更慢。
   - postflop lossless 规模约为 NLHE 的 160 倍。如果照搬每轮 200 个 bucket，每个 flop bucket 要覆盖约 102 万个信息局面（NLHE 是 6,434 个）。可能需要更多 bucket，或者更依赖剪枝带来的"有效细化"，以及搜索时的 lossless 当前轮。
   - 特征必须针对 PLO 重做：必须用 2 张底牌 + 3 张公共牌（每次 showdown 有 C(4,2)×C(5,3) = 60 种组合）；nut 潜力、听牌、阻断牌都要考虑；equity 分布更集中，使 EMD 聚类更难区分。
   - 搜索里"当前轮 lossless"在 PLO 中就是 range 维度 270,725（扣掉公共牌后略少），代价远高于 1,326。
3. **Action abstraction（pot-limit）**：
   - 最大下注就是 pot。NLHE 的 0.5×pot / 1×pot / all-in 自然变成 0.5×pot / pot；只有当 pot 尺寸加注超过剩余筹码时才出现 all-in。
   - preflop 不需要多达 14 种尺寸，但要覆盖 limp、pot raise 和 min/half raise 这几类。
   - 100bb 下 3bet/4bet pot 很快把 SPR 压到很低，抽象里必须包含"pot 加注 = 实际 all-in"这种边界情况。
4. **人数 2–8**：
   - 论文的 depth-limit 规则（flop 上多于 2 人时，叶节点设在第二次加注后或本轮末）和 preflop 搜索条件（不超过 4 人）都是针对 6-max NLHE 调出来的，8 人局要重新调。
   - 动作序列数量随人数快速增长：6-max 时 blueprint 就有 6.6 亿个序列，其中 62% 被访问过。
   - **2 人（heads-up）时**，CFR 和 safe search 的理论保证成立，可以测 exploitability（在抽象内或用 local best response）；**3 人及以上只能做经验评估**，这和论文的定位一致。
5. **Side pots 与筹码**：论文每手重置为 100bb 且人人等量，**所以不会出现 side pot**（本人推断：筹码相同，任何 all-in 都会被完全跟注匹配；论文没有讨论 side pot，全文检索 "side pot" 出现 0 次）。PLO 引擎要支持不等筹码，就必须：
   - 在 u_i(h) 中正确实现多层 side pot 分配，包括多路分池和平分；
   - 把有效筹码深度纳入状态或抽象，或按筹码深度训练多套 blueprint；搜索时使用真实筹码。
6. **Rake、ante、straddle**：论文全文没有提到（检索 "rake"、"straddle" 均为 0 次）。实战环境的 rake 会改变最优策略（例如 limp、flat call 的价值），这类结论**不能**从 Pluribus 迁移过来。
7. **算力**：NLHE 6-max 的 blueprint 只用 1.24 万 core-hours、实战 128 GB。PLO4 的信息局面大约多两个数量级，blueprint 规模、内存（本人估计）和搜索延迟都会显著上升。可能需要更粗的抽象、更激进的剪枝，或者用神经网络做函数近似（后者超出本文范围）。

### H3. 只适用于 NLHE 6-max、100bb、每手重置的结论
- +48 / +32 mbb/game 的胜率、p 值、10,000 手的样本规模、对手阵容（特定职业玩家）、无 rake、AIVAT 下约 2.5bb 的每手标准差。
- 各项超参数：1–14 种尺寸、200 / 500 个 bucket、k = 4、×5 偏置、400 / 200 / 800 分钟和每 200 分钟的时间表、−300M 门限，以及 1–33 秒的搜索时间。
- 策略观察（limp 很差、donk 频率高）。
- 等筹码带来的简化：没有 side pot，每手可以视为独立样本。

---

## I. 未核实或论文未给出的内容

**UNVERIFIED (from memory)**
- pseudo-harmonic 的具体公式（H1）。
- refs 38 / 41 / 42 / 44 的论文标题：参考文献列表只有作者和会议，没有标题。本人记忆中分别是 "Solving imperfect-information games via discounted regret minimization"、"Depth-limited solving for imperfect-information games"、"Accelerating best response calculation in large extensive games"（public chance sampling）和 AIVAT 论文。
- Data File S1 的内容（推测是对局记录），未下载。
- "PLO 单手方差更大"、"PLO preflop 入池范围更宽"这类扑克常识（H 节中已标注）。

**论文未给出（读完全文确认）**
- blueprint 总迭代次数。
- 搜索的迭代次数和折扣日程。
- "子博弈较大或处于早期"的具体门限。
- preflop 和 flop 的具体加注尺寸表。
- k-means 用的具体特征。
- blueprint 压缩格式的细节（M-p.4 只说"压缩形式"；S-p.25 描述的是 continuation strategies 的压缩）。
- 叶节点 rollout 的次数。
- 线程数。
- 多人之间 card removal 的处理方式。
- 第 1 轮 average strategy 是否在 800 分钟时清零（B5 中的歧义）。
