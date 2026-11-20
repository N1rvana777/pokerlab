# PLO4 实现资料审读笔记：Abstraction Agent / PokerRL-Omaha / 商业 PLO solver

- 日期：2026-10-23
- 目标规则：标准 PLO4（Pot-Limit Omaha High，4 张底牌，摊牌**恰好 2 张手牌 + 3 张公共牌**，2–8 人）。
- 证据等级标记：
  - **【原文】**：我实际读到的文字（论文 PDF/TeX、代码文件、网页），附位置。
  - **【厂商自述】**：商业网页的自我描述，未经独立验证。
  - **【自验】**：我自己写脚本独立算出的结果。脚本只读自己生成的数据，没有运行任何下载来的代码。
  - **【评估】**：我的判断或建议，不是来源中的事实。
- 引用方式：全部为转述。代码标识符（函数名、变量名、单行表达式）按审计需要原样给出。

---

## 0. 实际读取的来源与方法；未能读取的内容

### 0.1 已读（本地副本均在 `scratchpad/papers/plo_impl/`）

| 来源 | URL | 读取方式 / 本地副本 |
|---|---|---|
| Abstraction Agent 摘要页 | https://arxiv.org/abs/2609.04303 | WebFetch（工具会摘要）。确认作者、v1 于 2026-09-03 提交、类别 cs.MA/cs.AI/cs.CL/cs.GT、代码链接；页面无 comments 字段 |
| Abstraction Agent 论文 PDF | https://arxiv.org/pdf/2609.04303 | `abstraction_agent_2609.04303.pdf`（1,782,820 B，24 页）。Read 工具无法渲染 PDF（缺 pdftoppm），改用本机 `pdftotext -layout` 抽成 `abstraction_agent_2609.04303.txt` 后**全文通读** |
| 论文 TeX 源码 | https://arxiv.org/src/2609.04303 | `aa_src_2609.04303/x/`。用来核对表格、花色符号和数学符号（PDF 抽取后这些会丢失）。注意 `sections/limitations.tex` 存在，但在 `main.tex` L141 被注释掉，**不属于正式发表的 PDF** |
| Abstraction Agent 代码 | https://github.com/lbn187/AbstractionAgent （commit `60a4fec4db13…`） | 用 GitHub API 取元数据、文件树和提交记录。用 raw 文件读了 `README.md`、`card_utils.py`、`game_configs/plo4_preflop.py`、`game_configs/hunl_turn.py`、`game_configs/rover_trials.py`、`examples/run_plo4_preflop.py`、`abstraction_agent/pipeline.py`（L600–740，其余部分 grep）；`agent.py` 和 `examples/run_rover.py` 只 grep 过 |
| PokerRL-Omaha | https://github.com/diditforlulz273/PokerRL-Omaha （commit `d48d0c8235211d87c63c751a0ed269274fe1a571`） | GitHub API（元数据、44 个提交、完整文件树、issues/PR 及评论）+ 49 个文本源文件经 raw.githubusercontent.com 存到 `pokerrl_omaha_raw/`。**未 clone，未执行任何代码**，二进制 `.dll/.so` 未下载 |
| 上游 PokerRL（用于对比） | https://github.com/EricSteinberger/PokerRL （commit `e02ea667…`） | 5 个文件存到 `pokerrl_upstream_raw/`，用 diff 区分哪些问题是 fork 继承的、哪些是 fork 新引入的 |
| GTO Wizard：How GTO Wizard Solved PLO | https://blog.gtowizard.com/how-gto-wizard-solved-plo/ | WebFetch + curl 取 HTML，再用自写 stdlib 解析器转成 `vendor_html/gtow_how_solved_plo.txt` 全文阅读 |
| GTO Wizard：PLO Upgrades | https://blog.gtowizard.com/plo-upgrades-custom-hu-solving-postflop-icm-nodelocking-more/ | 同上，`vendor_html/gtow_plo_upgrades.txt` |
| MonkerSolver | https://www.monkerware.com/solver.html | 同上，`vendor_html/monker_solver.txt`。另读了该页链接的 `compare.html`（abstraction 说明）、`faq.html`、`guide.html`、`trees.html` |

### 0.2 未能读取或未能验证的内容

- PokerRL-Omaha 的手牌评估器是**纯二进制**（`lib_hand_eval.dll/.so`）。fork 和上游的文件树里都**没有 C/C++ 源码**（已用 API 查过上游）。评估器的语义只能依据 Python 包装层 docstring（"7 张中最强 5 张"）推断。
- 按要求**没有运行** PokerRL-Omaha。因此 `np.empty` 实际会留下什么内容、LBR 在 PLO 下怎样失败，都只是静态阅读的推断。issue #6 里有用户报告的运行时报错可作旁证。
- PokerRL-Omaha 仓库 API 显示约 128 MB，而当前文件树里最大的文件只有约 75 KB。git 历史里有什么（例如是否曾经提交过模型）我没有查。
- GTO Wizard 文中的结果图（`extra-1.png`）没有做图像解读，只读了正文数字。文中引用的 "GTO Wizard AI Benchmarks" 和 "Frequency Locking 2.0" 两篇未读。相关文章 "GTO Wizard AI Custom Multiway Solving"（2026-02-03）只看到了推荐区的摘要。
- Monker 的 `viewer.html` / `views.html` 未读。MonkerSolver 软件本身未运行。
- Abstraction Agent 论文的图（pipeline_figure.pdf、hunl_zero_shot_bar.pdf）没有作为图像检查。Libratus subgame release 的原始数据没读，因此这两个 turn 子博弈的筹码深度和下注树都无从得知。
- Abstraction Agent README 自称是 EMNLP 2026 Findings 论文，未核实。

---

## A. Abstraction Agent（Boning Li & Longbo Huang, arXiv:2609.04303v1, 2026-09-03）

### A1. 方法概要【原文，PDF p.4–6 §4，Algorithm 1】

- 目标：在一个固定的 public state（扑克里就是公共牌）上，把 N 个 private type（底牌组合）映射到 K 个 bucket。CFR 在 bucket 层面求解，再 lift 回原博弈，同一 bucket 内的所有手牌共用同一动作分布。质量指标是 lifted strategy 的 exploitability（Eq. 1），用对**未抽象博弈**的精确 best response 计算，单位是底池比例（p.4 §3）。
- 流程分四步：
  1. LLM 根据自然语言 `GameConfig` 提出 M 个（通常 3–8 个）取值在 [0,1] 的连续特征。每个特征带名称、描述，以及 0 / 0.5 / 1.0 三个 calibration anchor。这一步只调用一次 LLM，temperature 0.7、高 reasoning effort。
  2. 批量打分：每批 20–30 手，temperature 0，3 次重试，输出无法解析时填 0.5。
  3. 特征筛选：丢掉标准差 < 0.10 的特征；对 |r| > 0.90 的特征对，丢掉方差较小的一个；剩下的按标准差缩放（不减均值）。
  4. k-means++ 聚类，10 次重启 × 50 次迭代。
- 全程不使用 hand evaluator、equity、rollout 或博弈树遍历（作者的主张）。

### A2. 与 PLO 相关的全部内容

**(a) PLO 规则描述【原文，App. A，PDF p.14】**
- 4 张底牌，恰好 2 张手牌 + 3 张公共牌，不能用 1、3 或 4 张手牌；牌型分 9 级。
- 下注规则只写了一句：pot-limit 的最大下注等于当前底池。【评估】这只覆盖了无人下注时的首注，没有写加注时的规则（最大可加到"跟注额 + 跟注后的底池"）。好在该论文的 PLO 实验只做 preflop 聚类、不模拟下注，所以对结果没有影响；但**不能把它当作规则规格**。
- 论文的 PLO 实验**只有 preflop**：手牌空间为 C(52,4)=270,725 个原始组合，经 suit isomorphism 后剩 16,432 个 canonical representative。

**(b) 手牌表示与 suit isomorphism【原文，App. B Table 5（p.15）、App. H（p.20）；代码 `examples/run_plo4_preflop.py` L30–53】**
- Table 5 给出的花色结构计数：double-suited (2+2) 3,081；single-suited (2+1+1) 7,098；triple-suited (3+1) 3,718；rainbow 1,820；monotone 715；合计 16,432。
- 【自验】穷举 270,725 手后得到完全相同的 5 个计数和总数 16,432（另得 2 张牌 169 类、3 张牌即 flop 1,755 类）。见 §E。
- 代码中的 canonical 化：把手牌里出现的花色依次映射到 0–3 的所有单射排列，取字典序最小的 (rank, suit) 有序元组作为 key，并 assert 结果为 16,432。每类取遍历中第一个遇到的具体组合作代表，用真实花色的文字（如 "Ah Kd ..."）交给 LLM。论文 App. H 的表格则用首次出现顺序标注的抽象花色 a/b/c/d 来展示。
- PLO 的 LLM 输入只是 4 张牌的字符串。**没有**任何数值特征（equity、nut 指标等），也**没有** postflop 的手牌表示。

**(c) PLO 特征【原文，App. E，p.19】**
- 保留的 5 个特征：RANK_AND_PAIR_STRENGTH、SUITEDNESS_AND_FLUSH_POTENTIAL、STRAIGHT_CONNECTIVITY、ALL_CARD_COORDINATION、NUT_POTENTIAL。
- 因相关性被剔除的 2 个：FLOP_VALUE_SHIFT_POTENTIAL（与 coordination 的 |r|=0.91）、DOMINATION_RISK_RESISTANCE（与 nut potential 的 |r|=0.97）。
- 【原文·代码】`game_configs/plo4_preflop.py` L35–60 的 PLO 规则文本里**已经直接列出了**"Key strategic dimensions"：SUITEDNESS、CONNECTIVITY、HIGH CARDS AND PAIRS、NUT POTENTIAL、CARD COORDINATION、DOMINATION RISK。
  - 【评估】论文所谓"发现"的特征几乎一一对应这些提示，所以 PLO 上的"特征与公认策略概念吻合"（§6 p.9）**接近循环论证**。
  - 论文 App. A 号称给出"完整的输入描述"，但其中的 PLO 段落并没有这串提示，与仓库中的配置不一致。实验时究竟用的是哪个版本，无法确定。
  - HUNL turn 也有同样情况：`game_configs/hunl_turn.py` L55–57 明确提示应包含 current strength、improvement potential、vulnerability、stability across final cards、blocker effects 这些特征维度，而论文 App. A 的 HUNL 段落没有这段。
- 另外，仓库的 PLO 配置把 "3+1" 和 single-suited 混在一起描述（L42），而论文 Table 5 把两者分开计数。属于小瑕疵。

**(d) PLO 上做了什么、没做什么【原文，§5 "Cross-game settings" p.6；§6 p.9；App. E Table 8 p.18；被注释掉的 Limitations】**
- **做了**：对 16,432 个 preflop canonical hand 跑一次 K=30 聚类，展示 30 个簇的代表手牌和人工标签（Tables 11–12，p.20–21）；报告 parse rate 100%（App. M）。
- **明确没做**：没有计算 exploitability（§5 原文直说）。Table 8 中 PLO 一行的 "Key Result" 只是 "PLO features"。没有与 EHS、PA 或任何 evaluator baseline 比较。没有 postflop（flop/turn/river）PLO 实验，没有求解 PLO 子博弈，没有多人 PLO。没有报告 PLO 跑了几个 seed，也没有聚类稳定性（ARI）数据。没有给出 PLO 的下注树。
- 【原文】被注释掉、因而不在正式 PDF 中的 Limitations 段也承认：除 HUNL turn 和 ROVER 外，其余跨游戏结果都只是定性的。
- 【评估】对簇表的质量观察：
  - 15 号簇标签是 "Unpaired"，代表手牌却有三条 Q999。
  - 正文说 10 号簇是 "low rundowns like 9876"，但列出的代表是 5443、7643；9865 类手牌其实在 24 号簇。
  - 9 个簇共用同一个泛化标签 "Low-rank suited coordination holdings"，其中包括 KT95ds 和 AT52ds。
  - 结论：这些标签很粗糙，作为 PLO 抽象质量的证据很弱。
- 【评估】论文称 EHS/PA 对 16,432 手"代价高"（§6 p.9），这值得商榷。按 Monte Carlo 粗算，16,432 × 10⁴ 次采样 × 2 名玩家 × 60 次 5 张牌评估 ≈ 2×10¹⁰ 次评估，在 C++ 快速评估器上是分钟级，并非不可行。

**(e) 成本描述存在内部不一致【原文 + 代码，评估】**
- 论文 §5 写每个 seed 约"一打"LLM 调用（约 10 个打分 batch）；§6 又以"约一打调用"作为能为 PLO 构建抽象的理由。
- 但仓库中 PLO 示例的 `batch_size=30`（`run_plo4_preflop.py` L79），16,432 手需要 **548 次**打分调用（batch 为 20 时是 822 次）。
- HUNL turn 的 N≈1K（Table 8），按 20–30 手一批也需要 34–50 批，同样和"约 10 批"对不上，除非按 reach 过滤后实际只剩约 200–300 手。论文没有给出过滤后的 N。

### A3. HUNL turn 子博弈主实验的条件【原文，§5、§6、App. D–E】

- **子博弈**：Libratus 公开发布的两个 turn endgame，作者称这就是该发布中全部的 turn 子博弈（App. D Table 7，p.17）。
  - SG1：7♠9♥9♣T♣，pot 500。
  - SG2：T♠6♥A♥7♣，pot 4780。
- **规模**：Table 8 中 N≈1K 个 holding。私有手牌按 reach probability 过滤，但**阈值未给出**。**没有给出**：筹码深度、下注或加注尺寸、动作树规模、信息集数量；river 节点是否沿用同一 bucket（abstraction 定义在 turn 的 public state 上，river 怎么处理没有说明）；两名玩家是否都做了抽象。
- **抽象预算**：K ∈ {20, 50, 100}（ROVER 用 {5, 10, 20, 30}）。
- **求解与指标**：DCFR（α=1.5, β=0, γ=2），交替更新，2,000 次迭代。对未抽象子博弈做精确 best response，指标为 lifted strategy 的 exploitability（底池比例）。每个条件 10 个 seed（每个 seed 都重新做特征发现），报告均值，以及 Agent/EHS 比值的 95% Student-t CI。主模型为 GPT-5.5，另用 Llama-3.3-70B 和 Qwen-2.5-32B 对比。
- **结果**（Table 1，p.8）：Agent/EHS 比值见下表。"最多降低 62%"指 K=100 时的均值约 0.38。

  | K | SG1 | SG2 |
  |---|---|---|
  | 20 | 1.30（比 EHS 差） | 1.25（比 EHS 差） |
  | 50 | 0.74 | 0.82 |
  | 100 | 0.36 | 0.40 |

- **与更强 baseline 比较**（Table 3，只有 K=50）：PA（EHS + √Var）在 SG1/SG2 上为 0.0053 / 0.0254，Agent 为 0.0142 / 0.0483。也就是说 **Agent 仍比 evaluator-based 的 PA 差 1.9–2.7 倍**，论文自述只弥补了约三分之一的差距。
- **模型依赖**（Table 2）：K=100 时 Llama 为 1.07 / 1.36，Qwen 为 1.96 / 3.70，都比 EHS 差。只有 GPT-5.5 有效。
- **可复现性**【代码】：发布的仓库**只有生成 bucket map 的流程**，没有 CFR 求解器和 exploitability 评估代码（`card_utils.py` 提到的 `src/Card.hpp` 不在仓库里）。因此 HUNL 和 ROVER 的数字无法用发布的代码复现。
- **代码中未在论文出现的选项**：`pipeline.py` 和 `agent.py` 里有可选的 `discriminative_target`（例如每手 equity），用于 equity-aware 的特征筛选和按相关性加权（注释称为 "fix A/B"），默认关闭。PLO 示例没有使用它；论文主结果是否用过，无法确认。
- **许可**：README 徽章写的是 CC BY-NC 4.0（**非商业**），但仓库没有 LICENSE 文件（GitHub API 返回 license 为 None）。

---

## B. PokerRL-Omaha 审计（commit `d48d0c8`，静态阅读）

### B1. 元信息【原文：GitHub API / README / LICENSE / issues】

- 创建于 2020-06-15。最后一次 push 是 2020-07-22。共 44 个提交，作者 Vsevolod Kompantsev。
- 用 compare API 查过：最后一个 "PokerRL Omaha release" 提交（`efdbe310`，2020-06-15）之后的 15 个提交，只改动了 `README.md`、`_config.yml`、图片和一个示例脚本 `examples/interactive_agent_v_agent.py`。**核心库代码自 2020-06-15 起再未改动。**
- 74 star，20 fork，2 个 open issue。它不是 GitHub 意义上的 fork，但 README 说明自己基于 Steinberger 的 PokerRL 和 Deep-CFR。
- **License：MIT**。LICENSE 文件里只有 "Copyright (c) 2019 Eric Steinberger"，fork 新增的文件头写 "2020 Vsevolod Kompantsev"。
- 依赖 `requirements_dist.txt` **完全不锁版本**（gym、ray、pytorch 等）。issue #6 显示用户在版本组合上遇到了问题。
- **维护状态**：
  - issue #6（2021-11，仍 open）：用户报告开启 LBR 评估后在 `MainPokerModuleFLAT2.py` 的 `pub_obses[:, 14]` 处和 `IterationStrategy.py` 处报错。维护者 2021-11-29 回复：公开代码大概率有 bug，他本地版本领先若干提交，而且他已放弃 Python、改用 C++ 重写成另一个项目，不打算修复。
  - issue #8（2022-08）：用户报告每个 strategy 网络都各存一份 LUT，导致内存暴涨。维护者回复对支持这份代码没有兴趣。
  - → **结论：事实上已废弃。**

### B2. 算法【原文】

- Deep CFR（`EVAL_MODE_AVRG_NET`，平均策略网络）和 SD-CFR（`EVAL_MODE_SINGLE`），见 `DeepCFR/EvalAgentDeepCFR.py` L21–23。
- 采样器为 `MultiOutcomeSampler`（`DeepCFR/workers/la/sampling_algorithms/MultiOutcomeSampler.py` L8–60）：`n_actions_traverser_samples=None` 等价于 external sampling，=1 等价于 outcome sampling，二者之间是混合。默认值为 3（`TrainingProfile.py` L61, L63）。
- 另有继承自 PokerRL 的 tabular Vanilla CFR / CFR+ / Linear CFR（`PokerRL/cfr/*`，只在 Leduc 上测试）以及 DDQN 等 RL 组件。
- PLO 示例 `examples/PLO_training_start.py` L30–92 的配置：
  - `game_cls=PLO`，`agent_bet_set=bet_sets.PL_2`（只有 0.5 pot 和 1.0 pot 两档），`n_seats=2`，start_chips=10000，blinds 50/100。
  - 只用 SD-CFR 模式；14 个 worker；`n_traversals_per_iter=150000`；`n_iterations=64`。
  - `eval_methods={"": 99}`，即**评估实际上被关闭**。
- README 自述的改动：dense-residual 网络（FLAT2）"在 PLO h2h 中显著优于原 NN"、GPU+CPU 分布式、Leaky ReLU 等，**都没有给出任何数据**。

### B3. 规则正确性审计

**(1) 手牌评估：没有强制"恰好 2+3"——这是严重错误**【原文】
- 调用路径：`PokerRL/game/_/rl_env/game_rules_plo.py` L85–90 的 `get_hand_rank` → `PokerRL/game/_/cpp_wrappers/CppHandeval.py` L46–73 的 `get_hand_rank_52_plo`。
- 它的做法：对 4 张底牌的 6 个两张组合，分别调用 Hold'em 评估器 `get_hand_rank_52_holdem(2 张手牌, 5 张公共牌)` 取最大值。按其 docstring（L42，上游同文），这个评估器返回的是 **7 张中最强的 5 张**。
- 后果：等价于在"至多用 2 张手牌"的所有 5 张组合里取最大，**允许只用 0 或 1 张手牌**。例如板面四张同花加手里一张同花算成 flush、板面顺子直接算成 straight、板面四条算成 quads、单张手牌成顺或成同花，全都会被高估。
- README L27 自己也承认这是在原评估器上"套 Omaha 组合"，又"naive and slow"。docstring 自报速度约 7k 手/秒。
- 【自验】用自写评估器复现这种语义（§E-3）：
  - 随机发牌（HU 20,000 局），**18.7% 的单手牌值与正确值不同**，**4.29% 的 HU 摊牌底池判给了错误一方**；6 人桌（3,000 局）为 5.97%。
  - 不一致的手牌中，绝大多数（7,076/7,473）只用了 1 张手牌，397 例是直接"板面成牌"（0 张手牌）。
  - 注意这是不含下注、所有人看到 river 的随机手牌，不代表实战频率，但足以说明问题的量级。
- 仓库自带的唯一 PLO 评估测试（`test/game/test_PLO_LUTs_evals.py` L97–102）用的手牌是 KcKh7d7s、板面 4h4cKdQsKs：两种算法都得到四条 K，所以**这个测试无法发现上述错误**（§E-0 已验证）。期望值 1240771 只是回归常数，没有独立来源。

**(2) 批量评估在 PLO 下用了 Hold'em 的维度**【原文，推断】
- `game_rules_plo.py` L76–83 的 `get_hand_rank_all_hands_on_given_boards` 直接调用 Hold'em 版本；`CppHandeval.py` L87 按 `HoldemRules.RANGE_SIZE`（1326）分配输出，而 PLO 的 `RANGE_SIZE` 是 C(52,4)=270,725（`game_rules_plo.py` L20）。
- LBR 在 `PokerRL/eval/lbr/LocalLBRWorker.py` L437–442 用 PLO 的 range idx（可达 270,724）去索引这个 1326 长的数组；L448 调用的 `PokerRange.get_card_probs()` 对 4 张底牌直接 `raise NotImplementedError`（`PokerRL/game/PokerRange.py` L27–38）。
- 【评估】**PLO 的 LBR 评估在静态阅读下不可用**，与 issue #6 的报错一致。另外 `LocalLBRWorker.py` L20 断言 `n_seats == 2`。

**(3) Pot-limit 最大下注：环境不强制**【原文】
- `PokerRL/game/games.py` L262–285：`class PLO(PLORules, DiscretizedPokerEnv)` 设了 **`IS_POT_LIMIT_GAME = False`**（L269）。上游根本没有 pot-limit 游戏，所有游戏这一项都是 False。
- `DiscretizedPokerEnv._adjust_raise`（`PokerRL/game/_/rl_env/poker_types/DiscretizedPokerEnv.py` L46–47）只取 max(min-raise, 请求额)，**没有上限**；超过筹码时再截成 all-in（`PokerEnv.py` L1054–1059）。
- 只有在 `uniform_action_interpolation=True` 时（默认 False，`TrainingProfile.py` L50），才会看 `IS_POT_LIMIT_GAME`（`DiscretizedPokerEnv.py` L69–75）。PLO 下这个值为 False，于是最大一档会**随机采样到 all-in**，即按 NL 处理。
- 所以 pot 上限**只靠所选的 bet set 隐式保证**：PL_2/PL_3/PL_6/PL_10 的最大一档都是 1.0（`bet_sets.py` L96–113）。如果误用 B_2 等含 100000.0（all-in）的 bet set，PLO 就会变成 NL。
- 好的一面：`get_fraction_of_pot_raise(1.0)`（`PokerEnv.py` L1516–1536）算出的 raise-to = 当前最大注 + (主池 + 边池 + 桌面所有注 + 跟注额)，与标准 pot-limit 的 pot raise 公式一致。preflop SB=50/BB=100 时 UTG 的 pot raise = 350（3.5BB），正确。【评估】antes/straddle 是否计入 pot-size raise 因平台而异，见 §C2。

**(4) Min-raise**【原文，`PokerEnv.py` L921–947，与上游 L803–829 相同】
- HU：增量 = max(两人当前注之差, BB)。
- 多人：增量 = max(最高注 − 第一个严格更低的注, BB)。
- 【评估】这是用"前两档当前注之差"推断的，没有跟踪"最后一次完整加注的增量"。多人底池里出现 incomplete all-in 后，min-raise 会被算小。例子：bet 100 后有人 all-in 110，下一位的 min-raise 只算到 120；而标准规则下（待按项目选定的规则书核对）应为 210。

**(5) All-in / incomplete raise**【原文，`PokerEnv.py` L806–819、L1041–1043、L1660–1676 `CappedRaise`】
- 低于 min-raise 的 all-in 只锁住**上一个加注者**，使他不能再加注；其他已经行动过的玩家（例如跟注者）仍可加注。`CappedRaise` 的 docstring 明确把这当作规则来写。
- 【评估】常见规则书（如 TDA / Robert's Rules）的通行做法是：不足额加注不为任何已行动玩家重新开放加注。这一点本任务没有读规则书原文，需按项目规则核对。

**(6) Side pots**【原文，`PokerEnv.py` L617–698 和 L499–577】
- HU 不建边池：把两人注额之差退回多注一方，其余并入主池。
- 多人：先退还最高注超出第二高注的部分；以未弃牌者中最小的注额建主池；之后循环按"下一个最小非零注"逐层建边池，用 `side_pot_rank` 记录资格。
- 静态阅读未发现分配逻辑错误，但**仓库没有针对 PLO 或多人边池的测试**。fork 修改了 `_pay_all_to_one_player`：在 `_step` 中先归池再派发，见 L893–902。

**(7) Split pot / 零头筹码：确认存在 bug（继承自上游）**【原文】
- `PokerEnv.py` L560–564 用 `shuffled_winner_idxs = np.arange(num_winners)` 生成赢家**列表内**的下标，然后执行 **`self.seats[p_idx].award(1)`**，把它当成**座位号**使用。结果零头筹码可能发给非赢家（例如赢家是 3 号和 5 号座，零头却给了 0 号或 1 号座）。
- 上游 PokerRL L507–510 有完全相同的代码。
- 零头按随机分配，而不是按庄位规则分配。
- HU 平分用 `main_pot / 2`（L514–517），可能产生浮点筹码；注释称 HU 底池总是偶数。
- 次要问题：L513 的 HH logger 在 1 号座获胜时传入的是 0 号座的手牌，只影响日志。

**(8) 人数**【原文】
- README L24 写的是 2–6 人。环境本身只断言 ≥2（`PokerEnv.py` L141）。
- 但 LBR（`LocalLBRWorker.py` L20）和 `AgentTournament_hu.py` L35 都断言恰好 2 人；示例也只用 2 人。
- **NN 的 preflop 掩码写死为 `pub_obses[:, 14]`**（FLAT2 L109、FLAT L96、CNN L90）。按 `PokerEnv._construct_obs_space`（L207–234、L271–299）的布局，round one-hot 从下标 10+2N 开始。所以下标 14 只在 N=2 时恰好是 `round_preflop`：N=3 时是 `p1_acts_next`，N=6 时是 `last_action_who_4`。
- → **3 人及以上时，preflop 分桶会被错误的特征触发。**

**(9) 手牌观测 LUT 使用未初始化内存：疑似严重 bug**【原文，推断】
- `PokerRL/game/_/look_up_table.py` L218、L225、L240：PLO 覆写版的 `get_range_idx_to_private_obs_LUT` 用 **`np.empty`** 创建 LUT 和每一行，只把 8 个（或 4 个）one-hot 位置设为 1，其余 60 多个位置是未定义值。基类版本（L40、L43）用的是 `np.zeros`。
- 【评估】喂给网络的私有手牌编码因此可能夹带随机值或其他手牌的残留位。具体效果未经运行验证。

**(10) "Preflop 分桶"并不是同构，而是丢掉花色**【原文，`look_up_table.py` L236–250；README L42–50；FLAT2 L104–110】
- preflop 时只编码 rank，花色位全部不设。这会把 double-suited 和 rainbow 合并成同一个输入。
- 【评估】这在 PLO 里会丢失关键信息，与 README 所说的"isomorphic 合并"不符：真正的同构应保留花色**结构**，参见 §D3。

**(11) 测试覆盖**【原文】
- 与 PLO 相关的只有 `test_PLO_LUTs_evals.py` 中的一个评估回归值。该文件的 `setUpClass` 实际构造的是 `DiscretizedNLHoldem`（L59），不是 PLO。
- `test_look_up_table.py`、`test_pokerEnv.py`、`test_rangeManager.py`、`test_tree.py`、`test_cfr.py` 都只覆盖 Hold'em 和 Leduc。
- 没有 PLO 环境、pot-limit、min-raise、边池或零头的测试。

**(12) 训练结果证据**【原文】
- 仓库里没有模型、日志或曲线。唯一的手牌历史 `HandHistory/AgentTourney.txt` 是一手 **NLHE** 牌局，不是 PLO。
- README 中关于 PLO 的性能说法没有任何数据支持。

### B4. 结论：可以作依赖吗？【评估】

**不应作为依赖，只能作反面参考。** 理由：
- 核心规则错误：评估器没有强制 2+3；pot-limit 不由环境强制；多人 min-raise 和 incomplete raise 处理不正确；零头筹码派错人。
- 网络输入层有 bug：观测 LUT 用 `np.empty`；preflop 掩码写死下标 14。
- PLO 下的 LBR 评估不可用。
- 二进制评估器没有源码；依赖不锁版本；作者明确放弃维护。

它可以借鉴的地方有：
- 4 张牌组合的索引 LUT：C(52,4) 组合序和 4 维反查表（`look_up_table.py` L269–295）。
- 以 C(51,3)=20,825 为宽度的"含某张牌的组合"反查表（L297–309）。
- SD-CFR / MO 采样的工程骨架。
- 它的错误本身可以作为本项目的**回归测试清单**。

---

## C. 商业 PLO solver（一律视为【厂商自述】）

### C1. GTO Wizard：How GTO Wizard Solved PLO（2026-05-12，"Behind the scenes"）

**自述方法**
- 先构建了一个"无 abstraction、无神经网络"的 PLO4 **tabular** 精确求解器。作者说它用于 preflop 或 flop 不现实，内存和时间都会大得离谱，但可以为 turn/river 生成"完美数据"。
- 再做 "selfplay reinforcement learning"：让求解器大量自博弈，生成"节点处双方 range → range 内每手 EV"的数据，用来训练神经网络。网络根据 public 信息（stack、pot、rake 结构等）和 ranges 预测每手 EV。
- 求解时 **street-by-street**：只解当前街，下一街的 EV 由网络给出。作者称这与其 NLHE 产品是同一套流程，单次求解数秒。
- 文中写了 PLO4 有 270,725 种手牌，约为 Hold'em 的 200 倍。【自验】C(52,4)/C(52,2)=204.2。

**自述精度**
- River：HU PLO4 到 river 时实时**精确**求解，无 abstraction、无网络，Nash distance 小于底池的 0.1%。
- Turn benchmark：
  - 从 6-max 预解库中随机抽 200 个 HU flop 场景（SRP/3BP/4BP…），假设 flop 正常进行，按到达概率抽一个 turn 节点。
  - AI 只给每方 2 个下注尺寸（50%、100%）和 1 个加注尺寸（100%）。
  - 测法：把一方**整个 turn 策略**锁进精确求解器，另一方在 turn+river 上任意最佳应对，测被锁一方的 EV 损失，再对双方取平均。
  - 结果：平均 **0.14% pot**，90% 的 turn 低于 0.33% pot。文中自己承认这个指标对 SPR、可选尺寸等很敏感。
- Flop：**没有测**（计算太贵）；作者称因为方法相同，"有信心"精度相近。
- 对 Monker 的描述是竞争对手的说法：类似 Monte Carlo CFR、每次采样一手、未来街使用 abstraction，并且"不提供 Nash distance 指标"。

**没有建立的东西**【评估】
- 神经网络结构、训练数据量、range 的输入编码（270,725 维）、是否用 suit isomorphism 或其他 card abstraction，全都没有说明。
- turn 指标只在限定的下注树内、被锁方 river 仍可重新求解的条件下成立。它衡量的是 turn 策略误差，不是全博弈 exploitability：树外尺寸没有覆盖，flop 只是外推。
- 没有置信区间（只有均值和 90 分位），没有第三方复现。图中数据我没有读取。

### C2. GTO Wizard：PLO Upgrades（2026-07-27，Patch notes）

**自述的功能范围**
- HU PLO 从 preflop 到 river 可完全自定义（rake、筹码深度、antes、下注尺寸、nodelock、profiles）。自定义两人求解仅限 Elite 用户。
- **多人 PLO preflop 目前都是预解、不可配置的**。
- Preflop 库：
  - HU 10–200bb，PLO50/PLO500/cEV，含与不含 limp 两版。
  - 6-max 20–200bb。
  - CoinPoker 6-max ante 20–200bb。
  - GG 7-max 20–200bb。
  - ClubWPT Gold 8-max straddle+ante，20–200 straddles。
  - MTT 6-max 5/10–100bb，分 ante 计入或不计入 pot-size raise 两种求解。【评估】这说明 pot-limit 的"pot"是否包含 ante **因平台而异**，规则引擎必须把它做成参数。
- Postflop ICM：在自定义的 postflop PLO 树中可选，支持 KO/PKO/TKO。Preflop ICM 仍在开发中。
- 引擎：PLO river 提速约 2 倍，"仍为 0.1% pot exploitability"；最大树尺寸已提高（未给具体数值）；NLHE 提速 3–6 倍。PLO5 仍在研究中。

**没有建立的东西**
- 没有绝对求解时间和硬件信息，没有新的精度测量方法。
- 文中的 "equity bucket" 只是展示用的 Breakdown 分组，不能当作求解时的 abstraction。
- "其他 PLO solver 都没有这些功能"之类属于营销说法。

### C3. MonkerSolver（solver/compare/faq/guide/trees 页面）

**自述**
- 支持 Omaha 和 Hold'em，可从任意一条街开始，任意人数。下注树可完全自定义（AUTO 尺寸、Add to 批量添加）。
- 需要 Win64 或 macOS，至少 8 GB RAM。程序是 Java（通过 `-Xmx` 设定内存）。可解的树规模随 RAM 增长。免费版标注为限于 turn 和 river；完整版 €499。
- **Abstraction**（compare.html）：把策略上相近的手牌并成同一 bucket，强制使用相同频率。PLO postflop 的具体让步：
  - **river 之前**只区分有成同花可能的花色；
  - **river 上**只区分板面有 ≥3 张的花色。
  - 页面自己举例承认，被合并的手牌在 blocker 意义上**并不等价**。
- guide.html 建议每条街 15–30 个 strength bucket；大型 preflop 树可能要几天；以节点数的 10 倍作为迭代数参考。
- trees.html 的 PLO 例子：6 人、100bb、只允许 pot 尺寸：
  - 只允许 BB flat：约 14.62 GB；
  - 允许 BB 与 BTN flat：约 36.93 GB。
  - 建议 postflop 用稀疏子树，尽量只让 2 人进入 turn。
- 精度方面：FAQ 承认**算不出完整策略的 exploitability**，并认为大部分 exploitability 来自 postflop abstraction。唯一的对比是 Limit Hold'em preflop 与 Cepheus 比较，给出的是若干"错误"的定性列表，以及对应的 game size 比例（1/19,000、1/395,000、1/1,150,000）。
- 在我读到的 Monker 页面中**没有点名算法**（"类 MCCFR"出自 GTO Wizard 文）。

### C4. 小结：厂商自述 vs 已独立验证

- **独立验证：无。** 本次读到的所有厂商精度数字（0.1% pot river、0.14% pot turn、Monker 与 Cepheus 的对比）都是厂商自己报告的。
- 我唯一能"验证"的是可计算的常数：270,725 和约 200 倍。
- 可以提取的工程共识【评估】：
  - (1) PLO river 精确求解可以做到。GTO Wizard 声称做到了，规模上也合理：每人 178,365 手。
  - (2) turn 及以前需要 value net 加逐街求解，或者 card abstraction。
  - (3) 多人 PLO 无论哪一家都大幅退化：GTO Wizard 是预解且不可配置；Monker 需要稀疏树和 bucket。

---

## D. 评估：对本项目的具体启示【全部为评估】

### D1. PLO4 手牌评估器

1. **必须枚举 6 个手牌对 × 10 个公共牌三张组 = 60 个合法 5 张组合取最大**，或者用等价的预计算方法。**绝不能**把"对每两张手牌做 7 选 5"当作 PLO 评估，原因见 §B3(1) 和 §E-3。
2. 5 张牌评估器要做**穷举自检**：在全部 2,598,960 手上核对 9 类牌型的数量和 7,462 个不同等级（我的脚本已通过，§E-1）。
3. **差分测试**：快速实现与慢速参考实现（60 组合暴力）在百万级随机局面上逐手比对。
4. 必备的边界用例：
   - 板面四张同花，手里只有 1 张同花 → 不成 flush；
   - 板面五张成顺 → 不能"用板"；
   - 板面四条 → 只能算葫芦或更低；
   - 单张手牌连上的顺子或同花 → 不成立；
   - A-2-3-4-5 wheel 和 steel wheel；
   - 完全平局的分池；
   - 手牌四同花，只有 2 张能用；
   - 手牌三条，同点数只剩 1 张在牌堆。
5. **性能目标**：river 每个板面要给 178,365 手各评估一次（每手 60 次 5 张牌查表），然后排序一次。需要 C++/Rust 加查表型 5 张牌评估器。PokerRL-Omaha 自报的 Python 实现约 7k 手/秒，远远不够。
6. **规则引擎**（与评估器分开实现，并逐条写测试）：
   - pot raise 的 raise-to = 当前最大注 + (所有池 + 桌面注 + 跟注额)；
   - min-raise 显式跟踪"最后一次完整加注的增量"；
   - incomplete all-in 不为已行动玩家重新开放加注（按项目规则书确认）；
   - ante/straddle 是否计入 pot 做成参数（GTO Wizard 两种都解）；
   - 零头筹码用确定性规则（例如离按钮最近的赢家），并从**赢家列表**取下标；
   - 每一步检查筹码守恒。

### D2. River/turn 子博弈的 range 表示与 card removal

- **规模**【自验】：每人 river C(47,4)=178,365 手，turn 194,580 手，flop 211,876 手。
  - 一个 float32 range 向量约 0.71 / 0.78 / 0.85 MB。
  - river 上一个 3 动作节点的 regret 加 strategy-sum 约 4.3 MB。
  - turn 子博弈要展开 48 张 river 牌，内存乘约 48 倍。这正是厂商采用逐街求解加 value net（GTO Wizard）或 abstraction（Monker）的原因。
- **Blocker 远比 Hold'em 重要**【自验】：river 上英雄的 4 张牌挡掉对手 **30.8%** 的组合（54,955/178,365），而 NLHE 只有 8.4%（91/1,081）。turn 和 flop 分别约 30.2% 和 29.7%。因此不能用"均匀 range 近似"或"忽略阻挡"。
- **容斥（inclusion–exclusion）**【自验，误差约 1e-10】：
  - 与英雄 h 不冲突的对手权重 = T − Σ_{c∈h} W1[c] + Σ_{pair⊂h} W2 − Σ_{triple⊂h} W3 + w(h)。
  - 只需单牌（52）、对子（1,326）、三张组（22,100）三个累加表，加上同一手牌本身那一项。每手查询 15 次。
- **Showdown 扫描**【自验】：
  - 每个 river 板面按牌力排序一次；维护"严格更弱"的四级累加器，赢的权重用容斥查询得到。
  - 平局按同牌力分组，用组内累加器查询，并加回 w(h)。
  - 复杂度 O(N log N + 15N)。朴素两两比较要 3.2×10¹⁰ 对。
  - fold 终局用同样的兼容权重公式。
- **风险**：3 人及以上时，不同对手之间也会相互阻挡，两两容斥不再精确，需要联合处理或明确的近似并量化误差。项目规格（`Codex_Poker_Solver_Prompt.md` L179）也要求处理三人的"联合牌张排斥"。

### D3. Suit isomorphism

- **Preflop**【自验】：16,432 类，5 种花色结构的计数与论文 Table 5 一致。preflop 表、预解库和缓存都应按这一 canonical key 建立。
  - 用"4 个花色各自的 rank 集合构成的有序多重集"作 key，**O(1)** 即可，并且与论文仓库里按排列取最小的做法等价。
- **Postflop 收益取决于板面的稳定子群**【自验，以 4 张私牌的轨道数计】：

  | 板面 | 化简倍数 |
  |---|---|
  | 彩虹 flop（点数各不相同） | 1.00× |
  | 对子彩虹 flop | 1.86× |
  | 两色 flop | 1.89× |
  | 单色 flop | 5.10× |
  | 四花色 turn | 1.00× |
  | 四花色 river | 1.00× |
  | 单色 river | 5.22× |

  → **turn/river 子博弈大多省不了多少**，主要收益在 flop 种类（1,755）和 preflop。
- **实现要点**：
  - 同一个置换要同时作用于板面、双方 range 以及按牌索引的历史。回写策略时用逆置换。
  - 板面稳定子群非平凡时，要选定一致的轨道代表并记录轨道大小作权重。
  - PokerRL-Omaha 那种"丢掉花色"的做法**不是同构**，属于有损抽象，应避免。
  - Monker 的花色折叠同样有损。

### D4. PLO 的 bucketing / abstraction

- 现有证据中，**没有任何一项给出过 PLO abstraction 的定量 exploitability**：
  - Abstraction Agent 在 PLO 上只有定性展示；
  - Monker 自己承认算不出 exploitability；
  - GTO Wizard 的方案根本不是 card abstraction。
- 建议：
  - (a) 以精确的 river 子博弈作为"金标准"测试台（规模可行），在其上用 lifted-strategy exploitability 比较各种 bucket 方案。
  - (b) bucket 特征优先用由正确评估器算出的量：对实际 range 的 equity 和 equity 直方图（potential-aware / EMD）、nut 与次 nut 的 flush 和 straight blocker 指示、成牌类别、听牌张数等。
  - (c) **单独保留 blocker 信息**，不要像 Monker 那样折叠花色。PLO 中 blocker 的影响约为 Hold'em 的 3.7 倍（30.8% 对 8.4%）。
  - (d) LLM 特征（Abstraction Agent）最多只能当作启发式假设的来源。它在 PLO 上没有任何定量验证，强依赖 GPT-5.5，PLO preflop 每个 seed 约 548 次调用，而且许可是 CC BY-NC。
- 若做 turn 子博弈：对比"逐街求解加 river 精确求解"与"river 用 bucket"两种方案，并按 GTO Wizard 的方法（锁 turn 策略、river 重新求解）测 turn 策略误差，同时也测全博弈 BR。

### D5. 主要风险

1. 评估器或规则的细微错误（如 PokerRL-Omaha）会无声地污染所有训练和评估。必须有独立参考实现做差分测试。
2. 4 张牌 range 的内存与计算量（turn 扩展约 48 倍）。
3. 多人联合 card removal。
4. 花色折叠或 bucket 合并导致 blocker 被利用。
5. 不同平台 pot-limit 细则不同（ante、straddle、不足额加注）。
6. 把厂商自述的精度当成基准。
7. 引入 CC BY-NC 代码的许可风险（Abstraction Agent 仓库）。

---

## E. 自行验证【自验】（脚本：`scratchpad/scripts/plo_checks.py`，输出：`scratchpad/research/plo_checks_output.txt`、`evaluator_selftest_output.txt`；seed 20261023；只用 Python 标准库，未读取任何下载文件）

- **E-0 手工用例**：板面四同花加 1 张同花、板面顺子、板面四条、单张成顺、单张成同花这 5 例，朴素算法都给出更高的牌型（错误）。PokerRL-Omaha 的单元测试手牌两种算法结果相同，说明该测试不敏感。
- **E-1 评估器自检**：全部 2,598,960 手的 9 类计数为 high 1,302,540 / pair 1,098,240 / two pair 123,552 / trips 54,912 / straight 10,200 / flush 5,108 / full house 3,744 / quads 624 / straight flush 40，共 7,462 个不同等级，与标准值吻合。
- **E-2 计数与同构**：
  - C(52,4)=270,725，C(51,3)=20,825，C(49,2)=1,176。
  - 2 张牌 169 类，3 张牌 1,755 类，4 张牌 16,432 类，花色结构 {1820, 7098, 3081, 3718, 715}。
  - 各板面的轨道化简倍数见 §D3。
- **E-3 朴素与正确评估的 Monte Carlo**：
  - HU 20,000 局：单手不一致 18.68%，判池错误 4.285%。
  - 6 人 3,000 局：单手不一致 18.46%，赢家集合错误 5.97%。
- **E-4 容斥与扫描**：river 板面 AsJhTs9d2c，随机 30,000 手带权 range，50 个英雄手。兼容权重的最大误差为 1.4e-10，赢和平局权重扫描的最大误差为 5.2e-11（与暴力计算对比）。

---

## F. 未验证或无法确认的事项清单

1. PokerRL-Omaha 二进制评估器的真实语义：依据 docstring 推断为 7 选 5，无源码。
2. PokerRL-Omaha 中 `np.empty` LUT 的实际内容和对训练的影响、PLO 下 LBR 的具体失败点：都未运行。
3. Libratus turn 子博弈的筹码、下注树和过滤阈值，以及 Abstraction Agent 在 river 节点如何处理 bucket。
4. Abstraction Agent 实验实际用的 GameConfig 文本：论文 App. A 与仓库版本不一致。PLO 跑了几个 seed、是否用了 equity target 选项，也无法确认。
5. Abstraction Agent 的 HUNL/ROVER 数字无法用发布的代码复现（缺求解器）。EMNLP 2026 Findings 的录用说法未核实。
6. GTO Wizard 的网络与数据细节、多人 preflop 预解的方法、精度数字的独立复现，以及结果图中的数据。
7. MonkerSolver 的具体算法（只在竞争对手文中被称为"类 MCCFR"）和任何 PLO 精度数字。
8. §D 中引用的"标准规则"（不足额加注不重新开放加注、零头按位置分配等）都没有在本任务中读规则书原文，需按项目选定的规则书核对。
