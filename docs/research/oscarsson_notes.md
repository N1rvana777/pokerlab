# Oscarsson (2024 KTH thesis) + Oscarsson et al. (2025 IEEE ISI) 一手阅读笔记

用途：PokerLab（标准 PLO4：52 张牌、4 张手牌、必须恰好 2 张手牌 + 3 张公共牌、pot-limit、2–9 人）背景调研。
原则：以下每条事实都来自我实际读到的全文或代码，并附页码或文件行号；凡是我自己的计算或判断都标为 **[评估]** 或 **[我的计算]**；读不到的内容会明确写出。所有代码只读，没有编译或运行。

---

## 0. 来源、文件与读取状态

| 项目 | 实际访问的 URL | 本地文件 | 大小 / 页数 | 状态 |
|---|---|---|---|---|
| 2024 硕士论文全文 | https://www.diva-portal.org/smash/get/diva2%3A1887934/FULLTEXT01.pdf | `C:\Users\n1rva\AppData\Local\Temp\claude\C--Users-n1rva--claude-spares-spare-T7S9v9\6a9e7026-d511-4ad0-b9f7-d36a25f22f9c\scratchpad\papers\oscarsson\oscarsson2024_thesis_diva2_1887934.pdf` | 1,282,295 bytes；62 个 PDF 页（正文印刷页码 1–48）；SHA256 `03f31c8a…84296f1` | **全文已读**。正文用 `pdftotext` 逐页读完，表格用 `-raw`/`-table` 两种模式再核对一遍；Figure 5.1/5.2/5.3 从 PDF 内嵌 PNG 还原后看图读取。Figure 3.1/3.2 只是示意图，读了图注，图片本身没有细看。 |
| 论文记录页 | https://kth.diva-portal.org/smash/record.jsf?pid=diva2%3A1887934 | — | — | **没读到**：页面返回 Anubis 反爬虫的 “Access Denied”，我没有尝试绕过。论文封底自带 TRITA-EECS-EX-2024:477（PDF p.62），日期为 June 23, 2024（PDF p.3）。 |
| 2025 IEEE ISI 论文（FOI 提供的版本） | https://www.foi.se/download/18.2f6a97f619b2374cd1569/1766417410156/Cost_in_self-play_RL_FOI-S--7147--SE.pdf | `C:\Users\n1rva\AppData\Local\Temp\claude\C--Users-n1rva--claude-spares-spare-T7S9v9\6a9e7026-d511-4ad0-b9f7-d36a25f22f9c\scratchpad\papers\oscarsson\oscarsson2025_isi_FOI_full.pdf` | 17,761,238 bytes；8 页（A4），对应会议论文集 pp.113–120；SHA256 `64c6fea9…2084177` | **全文已读**。这是带 IEEE Xplore 页边戳记的出版社版本：p.113 左边距印有 ISBN 979-8-3315-1276-7/25/$31.00 ©2025 IEEE 和 DOI 10.1109/ISI65680.2025.11201174。该 PDF **几乎没有文字层**，页面是矢量轮廓，只有 p.116 带一层质量很差的 OCR，所以 `pdftotext` 读不出来。我用 Windows 自带的 `Windows.Data.Pdf` 把每页渲染成 3825×5409 的 PNG 后逐页看图阅读，并对 §IV-A/§IV-B 段落和 Table I/II/III 按原分辨率裁剪再核对。服务器很慢（约 7 KB/s），也不支持断点续传。第一次下载超时只拿到 3.47 MB，残片已改名为 `…\oscarsson2025_isi_FOI_TRUNCATED_first_attempt.pdf.partial`，没有使用。 |
| IEEE Xplore 页面 | https://ieeexplore.ieee.org/document/11201174/ | — | — | **没读到**：页面靠 JS 渲染，抓下来是空的。元数据改用 Crossref 核对：https://api.crossref.org/works/10.1109/ISI65680.2025.11201174 。标题一致；作者 Oscarsson、Brynielsson、Cohen（KTH）和 Kamrani、Limér（FOI）；会议为 2025 IEEE ISI，Hong Kong；pp.113–120；2025-07-12 出版；21 条参考文献。PDF 首页写明会期 July 12–14, 2025。 |
| 代码 | https://github.com/moscars/student-of-games（`git clone --depth 1`） | `C:\Users\n1rva\AppData\Local\Temp\claude\C--Users-n1rva--claude-spares-spare-T7S9v9\6a9e7026-d511-4ad0-b9f7-d36a25f22f9c\scratchpad\code\student-of-games` | commit `60fb516`（2024-06-11，“update README”）；MIT 许可；C++/LibTorch；约 4.4k 行 | 与规则、搜索、网络、训练、评估相关的源文件都读了 |

工具和中间文件：
- 本机没有 `pdftoppm`，Read 工具无法直接渲染 PDF 页面。
- 文本抽取用 xpdf `pdftotext 4.00`，结果在 `...\scratchpad\text\`。
- 论文内嵌图片用 `...\scratchpad\scripts\pdf_png_extract.py` 还原，输出在 `...\scratchpad\figs\thesis\`。这个脚本只解析 PDF 数据，不执行其中任何内容。
- 2025 论文的页面渲染用 `...\scratchpad\scripts\render_pdf_pages.ps1`（WinRT `Windows.Data.Pdf`），输出在 `...\scratchpad\figs\foi_pages\page01–08.png`，裁剪图也在同一目录。

页码约定：
- 硕士论文用**印刷页码**（p.）。正文部分 PDF 页 = 印刷页 + 12，例如印刷 p.25 就是 PDF p.37。
- 2025 论文用会议论文集页码 p.113–120，对应 PDF p.1–8。

---

## 1. Oscarsson (2024) KTH 硕士论文

基本信息：
- 标题：*Handling Uncertainty using Self-play Reinforcement Learning: A Study on the Scaling Properties of the Student of Games General Learning Algorithm*。
- 导师 Kamrani、Cohen、Brynielsson；host organization 是瑞典国防研究院 FOI（PDF p.3）。
- 研究问题：hidden information 的多少如何影响 SoG 的表现（§1.2, p.2–3）。
- 项目背景：FOI 想把 SoG 用在具有 “poker-like structure” 的反潜战（ASW）博弈问题上（§1.1, p.2；§6.4, p.40）。

### A. 游戏定义

**A1. TPLO（Turn Pot-limit Omaha），§4.1, p.25（PDF p.37）**

- 这是作者自定义的游戏，摘要称其 “derived from pot-limit Omaha”（p.i）。
- **街数与公共牌**：第一张公共牌就是 turn，所以只有 **3 个下注轮**，不是 4 个。
  - 论文正文没有直接写“公共牌一共 2 张”。这一点是按 §2.2（p.6）里 turn、river 各发 1 张的定义推出来的。
  - **代码确认了**：`numStreets = 3`（`src/settings.cpp:55`）；每个 chance 节点发 1 张（`src/tree/treeBuilder.cpp:178-203`）；摊牌时 board 正好是 `numStreets-1 = 2` 张（`src/game/equity.cpp:12,27`）。
- **牌堆**：限制为 **12 张，J–A 四个点数 × 三种花色**（p.25）。代码是 `{"Ah","As","Ad","Kh","Ks","Kd","Qh","Qs","Qd","Jh","Js","Jd"}`（`src/settings.cpp:8`），也就是没有梅花。
- **下注限制**：原文说 “As alluded to by its name, the game is pot-limit”（p.25）。
- **三个变体**：TPLO1/2/3 分别是每人 **1/2/3 张私有牌**（p.25）。可能的私有手牌数依次为 12 / 66 / 220（Table 4.3, p.30）。
- **成牌规则：私有牌与公共牌自由组合**，原文说 “similar to no-limit Hold'em”。
  - **没有**执行 Omaha 的“恰好用 2 张手牌”规则。作者的理由是：限制只能用固定张数的手牌，会“简化处理 hidden information 的那一面”（p.25）。
  - 代码确认：`handComp::strength` 直接把 board 和手牌合在一起数点数（`src/game/handComp.cpp:6-13`）。
- **牌型删减**：TPLO3 里去掉了 flush、straight、full house，理由是这几种牌型在 TPLO1/2 中不可能出现（p.25）。
- **人数**：heads-up 两人（§2.2 p.6；Table 4.1 注 |players| = 2, p.28）。
- **筹码**：
  - Table 4.3（p.30）写的是 TPLO1/2/3 “Blinds 100”、“Starting Stack 5000”。
  - 代码里这 100 叫 `ante`，**双方各投 100**（`src/settings.cpp:49-50`；`src/game/dealer.cpp:50`；`src/tree/treeBuilder.cpp:6`），没有 SB/BB 的不对称。
  - 因此初始底池 200，有效筹码 5000 = 50×100。
- **动作抽象**：所有 agent 只允许**一个 pot-size bet**（§4.3.1, p.27）。代码里：
  - `betSizing = {1.0f}`（`src/settings.cpp:6`）。
  - 下注后的总投入 = 当前最大投入 × 3，正好是 pot-limit 允许的最大加注；超过筹码时截成 all-in 5000（`src/tree/treeBuilder.cpp:205-235`）。
  - 最小加注检查为 `actingBet >= ante + maxBet`。
  - 面对下注时可选 fold/call/raise；双方投入相等时可选 check/bet（`treeBuilder.cpp:82-175`）。
  - 不限加注次数，直到 all-in；单独的 all-in 动作那几行被注释掉了。
- **行动顺序**（代码）：每条街都是 P1 先行动（`treeBuilder.cpp:190`，`dealer.cpp:48,104`）。论文没有讨论位置。
- **牌型**（代码，`src/game/handComp.h:9-15`）：只有 HighCard < Pair < TwoPair < ThreeOfAKind < FourOfAKind 五类。
  - **代码里根本没有 straight、flush、full house 这几个类别**。在 3 花色 × 4 点数的牌堆里，四条也不可能出现。
  - **[我的代码阅读]** 同花需要 5 张同花色，但每种花色只有 4 张；顺子需要 5 个连续点数，但一共只有 4 个点数。所以这两种本来就不可能。真正被“去掉”的只有 TPLO3（每人可用 5 张牌）里的 full house：三条加一对会被判成 ThreeOfAKind（`handComp.cpp:37-57`）。
  - **[我的代码阅读，论文未提及]** TwoPair 比较时**先比较较小的那一对**（`pairRanks` 按点数升序存入，见 `handComp.cpp:28-35,60-65,121-127`），并且**不比较踢脚**。
    - 在 TPLO2 中，由于公共牌是共享的，这不会改变胜负（我逐种情形检查过）。
    - 在 TPLO3 中会和标准规则不一致。例一：board {K, A}，P1 持 {A, J, J} 成 AAJJ+K，P2 持 {K, Q, Q} 成 KKQQ+A。标准规则 P1 赢，代码判 P2 赢。例二：AAJJ+K 对 AAJJ+Q，代码判平局。
    - 影响面可能很小，但说明 TPLO3 的牌力规则不是标准扑克排名。

**A2. Pot-limit Leduc Hold'em（只用于验证实现），§4.3, p.26；Table 4.3, p.30**

- 每人 1 张私有牌、牌堆 6 张、1 张公共牌（p.26）。
- Table 4.3：可能手牌 6 种，网络 50K 参数，Blinds 300，Starting Stack 1200。
- 下注轮数论文没有写。
- 公开仓库里的 `settings.cpp` 只有 TPLO1 配置，没有 Leduc 配置。只剩一个硬编码 6 张牌的随机情境生成器（`src/nn/dataGenerator.cpp`）。

**A3. 与标准 PLO4 的差距 [评估，基于上面的事实]**

| 维度 | 标准 PLO4 | TPLO1/2/3（论文 + 代码） | Pot-limit Leduc |
|---|---|---|---|
| 牌堆 | 52 张（13 点数 × 4 花色） | 12 张（J、Q、K、A × 3 花色） | 6 张 |
| 手牌 | 4 张 | 1 / 2 / 3 张 | 1 张 |
| 公共牌 | 5 张（flop 3 + turn + river） | 2 张（turn + river），没有 flop | 1 张 |
| 下注轮 | 4 | 3 | 未写明 |
| 成牌规则 | 恰好 2 张手牌 + 3 张公共牌 | 任意组合（Hold'em 式），明确**不**用 2+3 | — |
| 牌型 | 完整 9 类（含顺子、同花、葫芦） | 只有高牌、一对、两对、三条（四条达不到）；TPLO3 的葫芦按三条算；代码中两对的比较方式与标准不同 | 一对或高牌 |
| 私有手牌数 | C(52,4) = 270,725 **[我的计算]** | 12 / 66 / 220 | 6 |
| 下注 | pot-limit，尺寸连续可选 | pot-limit，但动作抽象只有一个 pot-size（即最大）下注，超过筹码时 all-in | pot-limit |
| 盲注 / 筹码 | SB/BB，常见 100bb | 双方各 100 ante（论文表里写 Blinds 100），筹码 5000 = 50 倍 | Blinds 300 / 筹码 1200 |
| 人数 | 2–9 | 2（heads-up） | 2 |
| 位置 | 按钮位翻牌前先动、翻牌后后动 | 代码中 P1 每条街都先动 | — |

结论 **[评估]**：
- TPLO 与 PLO4 只共享 “pot-limit” 这个名字和“多张私有牌”这个概念。
- 最能代表 Omaha 特征的“恰好 2+3”规则被作者有意去掉了。牌堆、牌型、街数、人数也都差得很远。
- TPLO 的结果**不能**当作 PLO 或 PLO4 的结果引用。

### B. 算法

**B1. 论文对 SoG 的描述（第 3 章）**

- **整体结构**：SoG = continual re-solving + 用 CFR 与 CFR+ 的混合来求解子博弈。具体是 linear averaging + regret matching+，但用 simultaneous updates（§3.5, p.19）。
- **GT-CFR**（§3.5.1, p.19–21）：
  - 子博弈按 MCTS 的方式逐步扩展。参数 s 是总扩展次数，c 是每次 CFR 迭代对应的扩展次数，CFR 迭代总数 = s/c。
  - 论文转述 SoG 原文的设置：chess 用 s=60000, c=10；no-limit Hold'em 用 s=10, c=0.1。
  - 扩展用 PUCT，其先验混合了 policy network 和当前 CFR 策略（p.21）。
  - 这些都是论文的转述；SoG 原文本次**没有读**。
- **Sound self-play**（§3.5.2, p.21–23；Algorithm 1–2, p.23）：
  - 自对弈中的网络查询按比例 q_search 进入 query buffer。
  - query solver 重新求解这些查询，得到 {PBS, CFV} 训练对。
  - 求解中产生的递归查询按比例 q_recursive 放回 buffer。
  - 自对弈策略和均匀策略按 ε 混合，用于探索。
  - 论文转述了 SoG 原文的收敛性定理（Schmid et al. 补充材料中的 Theorem 4）。

**B2. 本论文实际实现了什么**

- **论文声明的唯一改动：不用 GT-CFR 的动态增长树，改用固定大小的子博弈树**。
  - 理由是扑克的搜索树足够小，可以预先建好。
  - 为了抵消 GT-CFR 能非对称加深的优势，子博弈规模比 SoG 的 s=10 大约一个数量级（§4.2, p.26）。
- 因此 **GT-CFR、PUCT、policy head 都没有用到**。
  - 第 4 章只描述了 Counterfactual Value Network（CVN，§4.4），输出是双方每个信息状态的值（p.29）。
  - 代码里也没有任何 policy network 或 PUCT（`grep policy|puct|grow` 无结果）。
  - **[评估]** 实际实现更接近“DeepStack 式的深度受限 continual re-solving + SoG 的 sound self-play 训练数据生成”，而不是完整的 SoG。
- **代码细节 [我的代码阅读]**：
  - 子博弈从当前节点建到深度 `maxDepth+2`；深度 ≥ `maxDepth = 3` 的非 chance 节点用网络估值（`src/solving/deepResolving.cpp:13,105-121`；`settings.cpp:69`）。
  - 对手范围用 CFR-D 式的 re-solving gadget 处理（`deepResolving.cpp:229-277`）。
  - regret 下限截断为 1e-9，属于 RM+ 风格。
  - **平均策略是 warm-up 之后等权累加**（`deepResolving.cpp:215-220,289`），而不是论文 §3.3.3 写的线性加权 w_n = max(0, n−d)。只有 `pbscfr.cpp` 里的全树求解器用了线性权重。
- **CFR 迭代数**：TPLO 用 N = 200，warm start d = 100；Leduc 写的是 “varies”（Table 4.2, p.30）。代码里是 `CFRIter = 200`、`warmupCFRIter = 100`。

**B3. 网络输入与结构（§4.4, p.28–29；Table 4.1, p.28；Table 4.2–4.3, p.30）**

- **输入**：
  - 公共牌 one-hot，|deck| 维。
  - 行动者 one-hot，|players|+1 维（含 chance）。
  - 双方累计下注除以筹码，|players| 维。
  - 双方 range，即对所有私有手牌的分布，|players| × C(|deck|, |private cards|) 维。
  - 代码中 `networkInputSize = 12 + 3 + 2 + 2*numPossibleHands`（`settings.cpp:14`；`src/nn/inference.cpp:6-35`）。
- **MLP 结构**：
  - TPLO 用 3 个隐藏层 × 300。依据是 DeepStack 发现三层之后收益递减，以及 SoG 的隐藏层约为手牌数的 1.5 倍。Leduc 用 4 × 128。
  - 使用 LayerNorm（受 ReBeL 启发）、GeLU、Adam、Huber loss（p.29；Table 4.2）。
  - 网络参数量：TPLO1/2/3 = 200K/270K/450K，Leduc 50K（Table 4.3）。
- **代码补充**：
  - 结构是 fc→GELU→LayerNorm 重复 3 次，输出 2×手牌数。
  - 输出后再做零和修正：减去 range 加权和的一半（`src/nn/net.cpp:80-89`）。2025 论文 p.118 也写了这一点，硕士论文没写。
  - Adam 的 weight_decay = 1e-4（`src/nn/trainer.cpp:126`）。
  - 每个数据文件按 90/10 划分 train/validation（`trainer.cpp:44-56`）。
- **超参数**（Table 4.2，TPLO / Leduc）：

| 超参数 | TPLO | Leduc |
|---|---|---|
| batch size | 100 | 100 |
| 初始 LR | 1e-4 | 1e-3 |
| LR decay rate | 0.5 | 0.5 |
| LR decay steps | 5k | 3k |
| replay buffer | 30k | 15k |
| queries per search q_search | 4.5 | 30 |
| recursive queries per search q_recursive | 0.5 | 3 |
| uniform policy mix ε | 0.1 | 0.1 |

- 代码里 q_search 和 q_recursive 的实现方式是：每次网络查询以概率 0.0015×0.35 = 5.25e-4 被保存，query solving 时这个概率再除以 10（`inference.cpp:66-77`；`settings.cpp:66`）。我无法把这两个概率与表里的 4.5 和 0.5 一一对应起来。

**B4. 训练预算与硬件**

- 每个 TPLO 游戏各训练 **30 个 cycle**，每个 cycle 依次做 self-play、query solving、network training（§4.3.1, p.27）。三个游戏的 cycle 数相同（§5.2, p.33）。
- Figure 5.2（p.35）的横轴 “Batches processed” 大约是 0–5,400 **[图读数]**。
- **没有报告绝对训练时长**，只给了相对值：TPLO2 是 TPLO1 的 1.23 倍，TPLO3 是 1.77 倍（p.34）。
- 整个研究的计算耗电估计 < 100 kWh（§6.4, p.40）。
- 硬件（§4.6, p.30–31）：
  - Apple M1 Pro（MPS），以及 Intel Core i9-14900k 配 Nvidia Ampere GPU（CUDA）。
  - SoG 用 C++ 实现，网络用 Torch 实现。
  - 实现时参考了 DeepStack-Leduc 的开源代码。
  - 代码中 query solver 用 16 个线程（`src/nn/situationSolver.cpp:6`）。
- 训练种子数、每个 cycle 的自对弈局数：**都没有报告**。

### C. 实验条件、指标与结果

**C1. Leduc（用于验证实现）**

- **指标**：精确的 exploitability（mbb/g），看它随子博弈求解所用 CFR 迭代数怎样变化。query 求解也用同样的迭代数（§5.1, p.33）。
- **对比对象**：
  - Self-play Value Net：本实现 + sound self-play。
  - Unlimited Search Depth：continual re-solving 一直搜到终局，不用网络。
  - 参考线：uniform random 策略，以及 Random Value Net（随机初始化的网络）（p.33）。
- **Figure 5.1（p.34，对数纵轴）[图读数，约值]**，横轴点为 10/30/50/100/300/500 次迭代：

| 方法 | 10 | 30 | 50 | 100 | 300 | 500 |
|---|---|---|---|---|---|---|
| Self-play Value Net | ≈ 98 | ≈ 33 | ≈ 26 | ≈ 21 | ≈ 16.5 | ≈ 14 |
| Unlimited Search Depth | ≈ 115 | ≈ 40 | ≈ 28 | ≈ 27 | ≈ 14 | ≈ 12.5 |

  - Random Value Net 约 180–250，Uniform 约 1,000 以上。
  - 也就是说，迭代次数少时 self-play 网络比无限深度好；到 300 和 500 次时无限深度略好。
- **作者结论**：
  - 结果与 SoG 原文中类似的 Leduc 变体相近，作者认为结果可以 “replicate”（§6.1, p.37）。
  - 迭代少时网络更好的原因：网络学到的目标值，相当于“用固定迭代数求解”得到的值（p.37–38）。
- **另一个发现**：一开始用 DeepStack 式的**随机情境生成**来训练（而不是 self-play），效果显著更差。作者归因于 SoG 和 ReBeL 都不用 DeepStack 的扑克专用抽象（如 range bucketing），并引用了 ReBeL 的类似结论（p.38）。

**C2. TPLO1/2/3（主实验）**

- **TPLO 没有计算 exploitability**，因为在大游戏中无法在合理时间内算出来（p.27）。
- **指标**（§4.3.1, p.27）：
  1. 训练完成的模型对训练 10%、30% 时的快照的 win-rate，以及对均匀随机对手的 win-rate（mbb/g）。三个游戏的动作空间相同，所以均匀随机对手完全一样；所有 agent 只用一个 pot-size bet。
  2. 每个 cycle 用最新数据算出的 validation loss。
  3. 相邻 cycle 之间 root 节点策略的均方差。选 root 是因为 root 处的 range 恒定，便于比较。
- **方差缩减**：
  - 在摊牌处使用 imaginary observations（Bowling et al. 2008）：用 range 代替具体手牌，相当于对 O(|手牌数|²) 局取期望（§4.3.2, p.27–28）。
  - Table 5.1 称之为 “luck adjusted win-rate”，并给出 95% CI。
  - **[我的代码阅读]** `Dealer::playHand` 根本不发私有牌。双方从按 range 加权的聚合策略中抽样动作，终局按 range 对 range 计算期望。代码还额外累积了 AIVAT 风格的 chance 修正项和自身动作修正项（`src/game/dealer.cpp`）。Table 5.1 用的是哪一个结果向量（IO / AIVAT / FoldAndCall…），论文和代码都没说明。
- **基线**：只有均匀随机对手和自身早期快照。**没有**外部 bot、人类对手，也没有 best response 或 LBR。
- **评估局数**：论文**没有给出**。

**C3. 主要结果（Table 5.1, p.35；完整训练模型的 win-rate，mbb/g，±95% CI）**

| 对手 | TPLO1 | TPLO2 | TPLO3 |
|---|---|---|---|
| Uniform random | 2464 ± 149 | 1448 ± 137 | 469 ± 94 |
| 10% 快照 | 104 ± 55 | 147 ± 54 | 237 ± 41 |
| 30% 快照 | 38 ± 56 | 67 ± 55 | 63 ± 44 |

- 摘要说对均匀随机的胜率“约 5 倍”，就是 2464 / 469 ≈ 5.3 **[我的计算]**。
- **[评估]** 30% 快照那一行的置信区间大量重叠，TPLO1 的 38 ± 56 甚至包含 0。只有 10% 快照那一行显示出清楚的单调趋势。
- **训练时间**：同样 30 个 cycle，TPLO2 是 TPLO1 的 1.23 倍，TPLO3 是 1.77 倍（p.34）。
- **Figure 5.2**（p.35）：hidden information 越多，validation loss 越高。曲线末端大约是 0.45（TPLO1）、1.5（TPLO2）、2.6（TPLO3）**[图读数]**。
- **Figure 5.3**（p.36）：相邻 cycle 的 root 策略均方差。TPLO1 大约第 9 个 cycle 后接近 0；TPLO2 大约第 14 个 cycle 后接近 0；TPLO3 到第 26–30 个 cycle 仍在 0.01–0.04 之间 **[图读数]**。
- **作者的解读**（§6.2, p.38–39）：
  - hidden information 越多，同样训练量下学得越差、收敛越慢、需要的数据越多。
  - validation loss 更高，但要注意网络的输出维度也随手牌数增长。
  - TPLO3 的私有手牌数是 TPLO1 的 18 倍（220/12），CVN 的输入输出约大 18 倍，re-solving 中的 CFR 也要处理 18 倍的状态，但训练时间只多了 1.77 倍。
  - 作者把这归因于 Torch 张量运算的优化，并提醒实现细节会显著影响计算开销，而且开发重点是清晰和正确，不是性能。
- **结论**（§7.1, p.41）：
  - hidden information 的多少对 SoG 表现影响很大。
  - 信息越少，学得越好、收敛越快。
  - **每个 cycle 的计算需求**随 hidden information 次线性增长。
- **[我的计算 / 评估] 关于 “18 倍”**：
  - 摘要说 TPLO3 的 “extensive form game tree 18 倍大”，但正文里的 18 倍其实指私有手牌数之比 220/12，也就是 range 向量长度之比。
  - 如果数发牌组合（含 2 张公共牌）：TPLO1 是 12·11·10·9 = 11,880，TPLO3 是 220·84·6·5 = 554,400，约 47 倍。
  - 所以 “18 倍”应该理解为每个公共状态下信息状态数之比，而不是整棵树的大小之比。

### E. 论文自述的局限

- **§1.3（p.3）**：只做复现和分析，不尝试改进；实现只针对扑克。
- **§6.3（p.39）**：
  - 研究范围限于扑克变体。
  - 实验是为了**比较趋势**，不是为了给出算法一般意义上的收敛速度。
  - **具体数值对超参数高度敏感**。
  - 计算资源是一个重要限制（作为对比，ReBeL 用了 720 张 V100）。
- **§6.2（p.38–39）**：网络输出规模随手牌数增长，是一个混杂因素；计算开销的结论受实现方式影响。
- **§6.4（p.40）**：
  - 只在人类不玩的自定义游戏 TPLO 上实现，以降低被用来在真钱扑克中作弊的风险。
  - FOI 计划把 SoG 用于反潜战规划。
- **§7.2（p.42）未来工作**：
  - 扩展到更大的扑克游戏、用更多计算资源。
  - 在隐藏信息动态不同的其他游戏上验证（如 Scotland Yard）。
  - 研究更“分散”、无法枚举的隐藏信息。
  - 与 R-NaD 等无模型方法比较。

---

## 2. 代码仓库补充（moscars/student-of-games @ 60fb516）

- README 只说明这是一个 SoG 实现，用来研究 hidden information 的扩展性；依赖 LibTorch，支持 CUDA、MPS 和 CPU。
- 公开的 `main.cpp` 只是创建网络，然后让 `Dealer` 打**一手**牌（`main.cpp:23-31`）。
  - 30-cycle 的训练编排、快照对战、均匀随机评估的驱动代码**都不在公开仓库里**。
  - 因此代码只能核实各个组件，无法核实实验流程本身。
  - 公开 commit 是否就是实验所用的代码，也无法核实。
- `settings.cpp` 提交的是 TPLO1 配置：`handSize = 1`、`numPossibleHands = 12`、`hiddenSize = 300`、`stackSize = 5000`、`ante = 100`、`CFRIter = 200`、`warmupCFRIter = 100`、`numStreets = 3`、`maxDepth = 3`、`selfPlayEpsilon = 0.1`、`useMPS = true`。
  - 跑 TPLO2/3 需要手动改 `handSize` 和 `numPossibleHands`。`generateAllHands` 支持 1–3 张。
- 规则相关的结论见 §1.A1；搜索和网络相关的结论见 §1.B2–B3。
- DeepStack 式的随机情境生成器（`src/nn/dataGenerator.cpp`）硬编码了 6 张牌（Leduc）。这和论文 p.38 说的“一开始试过随机情境生成，效果显著更差”对得上。
- **[评估]** TPLO 的摊牌计算对所有手牌对做 O(H²) 双重循环（`src/game/equity.cpp:29-55`），只适用于很小的 H。

---

## 3. Oscarsson, Brynielsson, Cohen, Kamrani, Limér (2025)，*The Cost of Uncertainty in Self-Play Reinforcement Learning and Search*，IEEE ISI 2025, pp.113–120, DOI 10.1109/ISI65680.2025.11201174

页面结构：

| 页码 | 内容 |
|---|---|
| p.113 | Abstract；§I Introduction |
| p.114 | §II Background（A Poker、B Related Work）；§III-A Game Theory |
| p.115 | §III-B Re-solving；§III-C SoG 开头 |
| p.116 | Fig. 1；GT-CFR；§III-D Sound Self-play；Algorithm 1 |
| p.117 | §IV-A TPLO；§IV-B 实现；§IV-C 评估框架；§IV-D 方差缩减；§IV-E CVN 开头 |
| p.118 | CVN 续；Table I、II；§IV-F；§V-A；Fig. 2 |
| p.119 | Fig. 3、4；§V-B；Table III；§VI-A；§VI-B 开头 |
| p.120 | §VI-B 续；§VII Conclusions；Code Availability；参考文献 [1]–[21] |

### D1. 游戏和实验是否与 2024 论文相同

结论：**相同。2025 论文是硕士论文的会议浓缩版，没有新的实验、游戏或数据。**

- **TPLO 定义相同**（§IV-A, p.117）：turn 是第一张公共牌，3 个下注轮，12 张牌（J–A × 3 花色），pot-limit，TPLO1/2/3 = 1/2/3 张私有牌，TPLO3 去掉 flush、straight、full house。
- **Leduc 验证相同**（§IV-C, p.117；§V-A, p.118；Fig. 2）。
- **超参数相同**：Table I（p.118）与论文 Table 4.2 的数值完全一致，只少了 optimizer、normalization、activation 三行（这三项改在正文里写）。Table II（p.118）与 Table 4.3 完全一致。
- **结果相同**：Table III（p.119）与论文 Table 5.1 的数值完全一致（按原分辨率裁剪核对过）。Fig. 2/3/4 与论文 Fig. 5.1/5.2/5.3 目视一致。
- 训练时长比 1.23 倍和 1.77 倍也相同（§V-B, p.119）。
- **两个版本的文字差异**（我逐段对照找出的）：
  1. **2025 版 §IV-A 删掉了硕士论文中“私有牌可与公共牌自由组合、类似 no-limit Hold'em”这一句**。
     - §II-A（p.114）只说 Omaha 有 4 张私有牌、Hold'em 有 2 张，玩家 “combine their private and public cards to create the best five-card hand”，**没有提到 Omaha 的恰好 2+3 规则**。
     - 因此只读 2025 版无法确定成牌规则。应以硕士论文 p.25 和代码为准：自由组合，不是 Omaha 规则。
     - **[评估]** 结论部分又把 TPLO 称作 “a custom pot-limit Omaha variant”（p.120），读者容易误以为这是 PLO 的结果。
  2. **固定树的理由说法不同**。
     - 硕士论文说：为了抵消 GT-CFR 的优势，把子博弈建大约一个数量级（p.26）。
     - 2025 版说：这个限制 “should not significantly affect the performance in poker”，因为按 SoG 在 NLHE 上用的 s = 10，动态树足够浅，可以预先建好（p.117）。2025 版不再提“大一个数量级”。
  3. **2025 版新增一句**：在最后的线性层之后，强制网络输出满足两人零和性质（引用 DeepStack；§IV-E, p.118）。这和代码 `net.cpp:80-89` 一致，硕士论文里没有。
  4. **2025 版缺少的内容**：
     - 硬件信息和能耗。
     - 伦理部分。
     - Table 4.1 的特征尺寸表（2025 版改成文字描述）。
     - GT-CFR 在 chess 和 NLHE 上的 s、c 数值（2025 版只写迭代数 = s/⌈c⌉，p.116）。
     - Algorithm 2（query solver）。
     - 独立的 Limitations 小节。
     - 摘要里 “18 倍 game tree” 的说法。
  5. **动机写法不同**：2025 版更强调 serious gaming，即 defense 和 cybersecurity 中的 “fog of war”（§I, p.113）。
  6. **自我定位**：声称是第一个公开的 SoG 实现、也是 DeepMind 之外第一次复现（p.113）；结论称 “first public reproduction”（p.120）；代码链接指向同一个 GitHub 仓库（p.120）。

### D2. 主要发现及其成立条件（2025 版自述）

- **摘要**（p.113）：信息越少学得越有效；计算需求随 hidden information 次线性增长。
- **§VI-A**（p.119）：
  - Leduc 的 exploitability 与 SoG 原文以及 DeepStack 在 no-limit Leduc 上的结果一致，作者据此认为 SoG 的结果可以复现。
  - 迭代少时 self-play 网络优于无限搜索深度。
  - 随机情境生成的效果显著更差。
- **§VI-B**（p.119–120）：
  - Table III 中 hidden information 越多，对均匀随机的 win-rate 越低，说明同样训练时间下学不到同样程度。
  - 收敛更慢：Fig. 4 中 root 策略稳定所需的时间随 hidden information 增加。
  - 对 10% 快照的 win-rate 随 hidden information 增加；30% 快照的趋势类似但较弱。作者认为这说明训练效率更低、需要更多数据。
  - validation loss 更高，但输出维度也更大。
  - 私有手牌数是 18 倍，训练时间却只有 1.77 倍。作者归因于 Torch 张量运算，并说明实现细节会显著影响计算需求，项目重点是清晰性而非性能。
- **§VII**（p.120）：原文为 “computational demands per training cycle appear to increase sublinearly”。
- **成立条件**：与硕士论文完全相同。
  - heads-up TPLO：12 张牌、2 张公共牌、自由组合、只有一个 pot-size bet、100/5000 筹码。
  - 每个游戏 30 个 cycle，CFR 200 次（warm-up 100），3×300 的 MLP，只有一套训练配置。
  - 没有报告种子数、评估局数和绝对训练时间。
  - TPLO 上没有 exploitability，也没有外部基线。

### E（2025 版）. 局限

- 2025 版**没有独立的 Limitations 小节**。
- 文中只有这几处限定：网络输出随手牌数增大（p.120）；实现细节会显著影响计算需求，项目重点在清晰性（p.120）；未来工作是做更大的扑克游戏、用更多计算资源、在其他不完美信息游戏上验证（p.120）。
- 硕士论文里“超参数敏感”和“算力受限（对比 ReBeL 的 720 张 V100）”这两点，2025 版没有写。

---

## 4. [评估] 对 PokerLab（PLO4）的可迁移性

### F1. 可以借鉴的部分

1. **衡量“hidden information 扩展性”的实验模板**。
   - 做法：只改变私有牌张数，其他条件固定（牌堆、动作空间、隐藏层大小、cycle 数）。然后比较对固定弱基线（同一个均匀随机对手）的胜率、对自身早期快照的胜率、validation loss、root 策略的稳定性，以及每个 cycle 的耗时。
   - PokerLab 可以照此在同一个 PLO 引擎里比较 Hold'em 2 张、Omaha 4/5/6 张，或者在缩小牌堆的 Omaha 上（保留 2+3 规则）观察学习曲线怎样随手牌数变化。
   - 需要改进的地方：
     - (a) 用 exploitability（小游戏或 river 子博弈可以精确算）或 LBR，而不是只看对随机对手和快照的胜率。
     - (b) 跑多个随机种子。
     - (c) 用 wall-clock、样本数或 FLOPs 对齐计算预算，而不只是对齐 cycle 数。
     - (d) 网络容量要随 range 维度一起缩放。原文固定隐藏层为 300，而输出从 24 增加到 440，容量是一个混杂因素。
     - (e) 改变手牌数会同时改变牌力分布。比如 TPLO3 在自由组合下每手牌至少有一对。所以变化的不只是“信息量”。
2. **表示方式**。
   - PBS 由公共牌 one-hot、行动者、归一化投入和双方完整 range 组成；输出双方每手牌的 CFV，加零和修正层；损失用 Huber；网络用 LayerNorm 加 GELU。
   - 这些都是 DeepStack、ReBeL、SoG 通用的做法，可以作为 PLO4 value net 的基线接口设计参考。
3. **评估中的方差缩减**：imaginary observations（按 range 对 range 结算），加上代码里 AIVAT 风格的修正，对 PLO 这种高方差游戏直接有用。
4. **训练数据的生成方式**：作者报告 sound self-play（query buffer + recursive queries + ε=0.1 的均匀混合）在 Leduc 上明显优于 DeepStack 式的随机情境生成。这对 PLO4 的数据生成策略有参考价值，但证据只来自 Leduc。
5. **可读的开源参考实现**（MIT，C++/LibTorch）：可以拿来对照 continual re-solving、re-solving gadget、CFV bound 在街与街之间如何传递等细节。但它不是完整的 SoG。

### F2. 不能迁移、不能引用的部分

- **任何数值都不能当作 PLO 或 PLO4 的结果引用**，包括 Table 5.1/III 的 win-rate、“约 5 倍”、1.23 倍和 1.77 倍、“18 倍”、validation loss、Leduc 的 exploitability。原因是 TPLO 不是 Omaha：自由组合、只有 2 张公共牌、12 张牌、没有顺子同花葫芦、只有一个下注尺寸、只有两人。
- **也不能当作“完整 SoG 在扑克上的结果”引用**。实现里没有 GT-CFR，也没有 policy head 和 PUCT，实际上是深度受限的 continual re-solving 加 sound self-play。
- **“计算需求次线性增长”不能外推到 PLO4**。
  - 这个现象只在手牌数 12→220、网络不超过 450K 参数、特定实现、单次运行、只有相对训练时间的条件下观察到。
  - PLO4 有 C(52,4) = 270,725 种手牌；5 张公共牌发完后每人还有 C(47,4) = 178,365 种 **[我的计算]**，大约是 TPLO3 的 800–1,230 倍。
  - TPLO 代码的摊牌计算对所有手牌对做 O(H²) 循环。放到 PLO4 的 river 上，每个 board 大约要算 3.2×10^10 对 **[我的计算]**，必须换成排序加 blocker 修正的 O(H log H) 方法，或者做抽象。
  - TPLO 的牌力评估器是自由组合的，不能复用到 PLO4 的 2+3 规则上。
- **网络结构不能照搬**。按手牌逐一输出的完整 range MLP，在 PLO4 的 river 上输出层是 2×178,365。需要换别的结构，比如共享的逐手编码器、分桶，或者利用花色同构。PLO4 翻前的花色同构类有 16,432 个 **[我的计算]**。
- **人数**：原文是两人；PLO4 是 2–9 人。两人零和情形下的 safe re-solving 和 CFV bound 理论不能直接推广到多人。

---

## 5. 未核实或未能读取的项目

1. DiVA 记录页被 Anubis 反爬虫拦截，没有读到；元数据取自论文本身。IEEE Xplore 页面因 JS 渲染没有读到；元数据通过 Crossref 核对。
2. FOI 版 PDF 没有文字层，所以 2025 论文是看渲染图读的。表格按原分辨率核对过，正文目视阅读，引用的字句以页面图像为准。
3. Leduc exploitability、validation loss、root 策略 MSD 的数值都是我**从图上读的约值**，正文没有给出这些数字。
4. 两篇论文**都没有报告**：
   - Table 5.1/III 的评估局数；
   - 训练种子数或运行次数；
   - 绝对训练时间；
   - 每个 cycle 的自对弈局数；
   - 子博弈的确切大小（只有代码给出 `maxDepth = 3`）；
   - Table III 具体用的是哪一个方差缩减估计量（论文说 imaginary observations，代码里还有 AIVAT 风格的项）。
5. 公开的 commit `60fb516` 是否就是实验用的代码无法核实：30-cycle 编排、快照评估、LR 调度、replay buffer 的驱动代码都不在公开的 `main.cpp` 里。
6. 代码里 q_search 和 q_recursive 的实现（每次查询以 5.25e-4 的概率保存，求解时再除以 10），与表中 4.5 和 0.5 的对应关系没有核实。
7. Leduc 的下注轮数和加注结构论文没有写，仓库里也没有 Leduc 配置。
8. TPLO3 中两对的比较与标准不一致（先比小对、不比踢脚），这只是我读代码得出的；论文没有提到，它是否影响结果也不知道。
9. 2025 版没有写明成牌规则；“自由组合”来自硕士论文 p.25 和代码。
10. 论文转述的 SoG 原文设置（NLHE 用 s=10、c=0.1，chess 用 s=60000、c=10，以及 Theorem 4）没有对照 SoG 原文核实，本次没有读 Schmid et al. 2023。
11. 按要求没有运行任何代码。
