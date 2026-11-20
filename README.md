# PokerLab

A research workbench for heads-up poker. It solves no-limit hold'em postflop spots to equilibrium, builds a model of the opponent, and computes the exact best response to that model. The question behind it: how far should play deviate from equilibrium when the evidence about an opponent is limited and noisy?

> **Public snapshot / 公开版说明**
>
> This is a public copy of a private working repository; commit history is not included.
> Not included: private hand records and opponent notes, solver and research outputs
> (`outputs/`, about 180 GB), the vendored upstream engine checkout
> (`third_party/postflop-solver/`; check out the revision pinned in `Cargo.toml` and apply
> `third_party/patches/`), and scripts that downloaded third-party video data. A few passages
> in the docs that described real hands were shortened.
>
> PokerLab is licensed under the GNU Affero General Public License v3.0 or later
> (see `LICENSE`), the same license as the upstream engine, b-inary/postflop-solver.
>
> 这是私人工作仓库的公开副本，不含提交历史。没有包含：私人手牌记录与对手信息、求解与研究输出（`outputs/`）、
> 上游引擎源码（按 `Cargo.toml` 固定的版本另行获取并应用 `third_party/patches/`），以及下载第三方视频数据的脚本。
> 文档中涉及真实手牌的段落已删改。本仓库使用 AGPL-3.0-or-later 许可证（见 `LICENSE`），与上游引擎相同。

## Overview

- **Equilibrium solving.** Discounted CFR (DCFR) on full flop, turn and river trees, with every turn and river card and no card abstraction. The core engine is the open-source [b-inary/postflop-solver](https://github.com/b-inary/postflop-solver) (Rust), extended with a patch and an adapter.
- **Opponent models and exploitation.** Stackable behavioural traits, node locks and player profiles define the opponent's strategy at every information set. That strategy is frozen, and an exact best response is computed against it.
- **Opponent evidence.** A replay-checked hand-history format, a PokerStars/GG parser, and Beta-binomial posteriors with 90% intervals for 18 opponent statistics.
- **Review assistant.** An LLM assistant (Claude or OpenAI models) that may quote only numbers produced by the solver and statistics tools. Its private knowledge base, built from about 200 public strategy videos, is not included.
- **Heads-up pot-limit Omaha (paused).** A Libratus-style research prototype in `src/pokerlab/plo/`: an exact rules engine and hand evaluator, hand abstraction, a 20 bb Monte Carlo CFR blueprint, and agents that re-solve turn-and-river subgames at decision time.

## Checks and results

- Solver results agree with an independent linear program, closed-form test games and GTO Wizard, a commercial solver.
- A full flop tree with three bet sizes per street (11.1 million nodes, 3.46 billion action entries) was solved to 0.092% of the pot in about 2.6 hours on a 32 GB desktop PC, with a 13.9 GiB memory peak.
- In the Omaha prototype, solving turn and river jointly cut exploitability from 1.108% to 0.026% of the pot compared with solving each river separately. On a small game, a linear program matched the joint solve.
- These figures measure solution quality. They are not claims about playing strength.

## Status

The hold'em workbench and the review assistant are in active development. The Omaha line has been paused since October 2026. To start the workbench, run `python -m pokerlab.solver.server` and open http://127.0.0.1:8765; setup details are below, in Chinese.

AI coding agents (Claude Code, OpenAI Codex) wrote much of the code under my direction. `CLAUDE.md` and `AGENTS.md` are their instructions, and `docs/DECISIONS.md` records which decisions were mine. The rest of this README and the documents in `docs/` are in Chinese.

## 中文说明：本地翻后 Solver

当前为可运行的阶段 1 研究工作台：两人 Flop/Turn/River、可叠加特质、冻结完整对手策略、导出 Hero 信息集最佳回应，并查看组合与后续节点。完整需求见 [原文](Codex_Poker_Solver_Prompt.md)，实际数值与限制见 [进度](docs/PROGRESS.md)。原有数学代码与阶段 0 文档均保留。

## 本机启动

在当前项目根目录的 **PowerShell** 运行一条命令：

```powershell
python -m pokerlab.solver.server
```

浏览器打开 **http://127.0.0.1:8765**。计算自动调用已构建的 Ubuntu WSL Rust 引擎，不需要在 WSL 中启动网页服务。服务只监听本机；Ctrl+C 退出并取消所属计算任务。

本机已在 `C:\Users\n1rva\OneDrive\Desktop` 安装 `Pokerstudio.lnk` 和 `Pokerlab Solver.lnk`，目标、参数、工作目录及图标已读回核对，本轮再次确认两个文件存在。安装入口为 `powershell -ExecutionPolicy Bypass -File pokerstudio/install-desktop.ps1`；冷启动、重复启动复用后台及停止自有后台已有实测，实际 Windows 独立窗口的无地址栏视图尚未验收。关闭窗口保留服务和任务；端口占用、日志及显式关停说明见 [桌面启动](pokerstudio/docs/DESKTOP.md)，原命令行入口继续可用。

2026-10-08 本机8765后台已更新。界面使用 bb（大盲），目前底池和剩余筹码支持整数 bb；16 位压缩、自动安全花色同构和默认8线程保留。前端默认启用自动内存，旧示例未指定 `memory_auto` 时也启用，不再受其4096 MiB手动上限限制。显示 Windows / WSL 实时可用内存及安全预算；计算获得串行锁后再次测量。取消自动模式才使用手动上限。后端缺少 `memory_auto` 的旧保存请求与 CLI 仍按手动预算处理，不静默提高显式上限。导出配置位于侧栏顶部。

历史研究“SPR20 多尺寸内存优化验证 - 基线未达0.1%”仍保留。其原测量使用压缩／自动同构、16线程、1800秒时限和自动预算；500次迭代未达到0.1%。冷启动约11分33秒，复用该基线后的完整固定对手流程约3分50秒。当前普通任务已取消自动超时，这里只保留原实测记录。新策略快照直接保存16位数据，避免重开时再次量化；旧格式仍兼容，bb界面没有重算或改写历史报告。

2026-10-13 已保存本次完整大树“**完整Flop 三街三尺寸3x · 0.1%达标 · 2026-10-13**”（研究ID `f79af0c4219441a284f16d34a7da9d39`）。打开桌面Pokerlab或上述浏览器地址，刷新页面，在“已保存研究”中选择该名称并点“打开”。已用真实Edge无头浏览器重开，耗时45.281秒：保留原0.1%目标、9h8h2c、203/449组合及三份完整策略，显示169个策略格、4个合法动作，无JS错误或过期标记。一次真实模型根节点查询完成，原生退出码0且已回收，没有重新CFR／BR；测试仅模拟外部助手状态／会话，使用隔离助手配置。证据见 [重开验收](outputs/performance-20261013-v2/completed-workbench-acceptance.json) 与 [实测截图](outputs/performance-20261013-v2/completed-workbench.png)。当前整数bb引擎把根下注取整为3／5／8bb，实际为底池37.5／62.5／100%；配置中的33／66／100%输入仍保留，不表示支持小数bb下注。

操作示例：

2026-10-13 用户选择日常探索优先：新建局面的均衡基线默认 **0.5% 起始底池**，可自定义。点击侧栏“新建日常局面”会以所选示例建立该默认配置；“载入示例”、导入和打开已保存研究仍保留其显式精度。已有助手持久化状态不会因刷新页面而改写。该目标只用于均衡基线，固定对手最佳回应的 response gap 仍单独测量；本次完整大树保持原定0.1%目标并已达标完成。启动期间的编辑／导入优先于迟到的默认配置，首次后台版本尚未读取时不会写回。

1. 保留默认“Flop 实际范围 + All-in Raise”案例：9h8h2c、底池100 bb、剩余有效筹码200 bb。
   左侧 **OOP 范围／IP 范围** 两份表格默认全部展开，IP 在 OOP 下方；点击“定位 IP 范围”可直接跳到 IP。单击一格选中，再点取消；悬停滚轮每次调5个百分点，按Shift调1个百分点，范围0–100%。默认按169种牌类均匀赋予各具体花色权重；“查看具体花色”可保留高级非对称范围。文本与网格同步，支持导入和导出；公共牌冲突组合保留但不计入有效范围。
   “翻前总范围 %”滑杆按1326个组合加权选择前X%，对子6个、同花4个、非同花12个；边界牌类使用所有花色相同的混合权重。70%对应928.2个加权原始组合；排序使用页面公开说明的翻前启发式模板，不是当前街GTO或实测Equity，不按公共牌重排。调整总范围会重建花色均匀的模板，可撤销；百分比包含公共牌冲突组合。
   三街尺寸可直接点击多选，蓝色按钮表示已选；下方输入框允许自定义，最多三个尺寸。
2. 点击“求均衡基线”。查看目标精度、实际精度与停止原因。
3. 选择组合特质预设或调整 Station、Overbluff、连打后放弃的轻／中／重强度和适用街道，生成对手预览，再冻结并计算最佳回应。高级参数 1／2／3 对应上述强度，不是百分比或已校准人群统计。只比较 River give-up 时，第三项只勾 River，其他输入保持不变。
4. 结果网格按真实动作概率分色，上方显示图例与全范围加权频率；点击 AA 查看具体花色组合、行动概率、Equity、逐行动 EV。鼠标悬停网格可看该格频率；斜纹表示零到达。通过动作按钮和公共牌进入后续节点，切换基线／对手模型／最佳回应。进入对手节点可看“基线 → 固定模型”实际频率变化，两列使用当前模型相同的条件范围权重。
5. 保存研究，再从已保存列表重新打开。修改输入会标记旧结果过期。保存包含全树最终策略；不包含 CFR regret 或断点续算状态。

Node Lock 操作：进入决策节点（包括 Turn/River）→ 在具体组合表中点一行或选择“当前网格手牌组／当前 Filters 选中的组合／全部合法组合” → 输入完整动作分布、点“100% 某动作”，或用“按总频率锁定”填目标频率 → 保留节点锁 → 第 3 步冻结对手只优化 Hero，或第 4 步只锁这些节点、双方重新求解。第 4 步会显示锁定前后的频率和 EV，Hero 节点的锁只在第 4 步生效。锁列表可定位、删除，范围恢复模板可批量解除；撤销／重做支持最近 100 步输入编辑。模型特质改变不会删除锁；改变局面或尺寸后旧锁会明确拒绝，须恢复局面或主动移除旧锁。

“命名范围库／玩家特质库”可保存本机档案；玩家库只保存可跨局面复用的特质，节点锁随研究保存。可导出／导入配置 JSON 复制模型。节点分析提供 Equity 分布，组合表支持按 EV、Equity、收益变化排序／筛选。“模型敏感性”串行运行轻／中心／重三个冻结模型，分别报告同模型提升和根 Hero 行动反转；不是三份结果共用一个对手。

已用本机 Edge 的 Playwright 无头浏览器实际走通上述流程及取消任务；不是人工浏览器验收。截图：`outputs/workbench-flop.png`。

重新构建：`powershell -ExecutionPolicy Bypass -File scripts/build.ps1`。新环境安装 Python 包：`python -m pip install -e '.[dev,solver]'`；浏览器测试另装 `.[browser-test]`。当前使用 Rust 1.75 / Ubuntu WSL；引擎固定为 b-inary/postflop-solver commit `9d1509fe5077d019825f833eed04b16d342dfda1`，AGPL-3.0-or-later，另有已记录的 [完整花色分支补丁](third_party/patches/README.md)。构建脚本核对整个补丁；原始源码可由固定 commit 恢复。项目根目录没有 Git 仓库，没有自动提交或推送。

原 CLI 仍可用：`python -m pokerlab.solver examples/river.json --output outputs/my-river.json`；已存在输出不会覆盖。CLI 默认保存配置和报告；工作台另保存完整策略。

## Pokerstudio 本地剪辑与 Agent

详见 [Pokerstudio](pokerstudio/README.md)。在仓库根目录运行 `python -X utf8 -m pokerstudio.server`，打开 http://127.0.0.1:8770 。支持手牌/字幕/动态叠加、真实 MP4 导出、现有 solver 适配和订阅/API agent；实际验收和限制以其文档为准。独立分析入口为 `/analysis`，原工作台运行方式保留。

## 原 Solver 工作台内的助手

助手已直接接入8765的原 Solver 工作台。它有自己的配置、会话、认证及Solver业务工具，运行时不依赖8770服务或Pokerstudio实例；复用双provider协议实现。订阅入口为正式 Sign in with ChatGPT，也可明确选择现有CLI认证；API需单独配置key并明确允许付费，订阅限额不会自动回退到API。

助手只操作Solver配置、真实任务、结果、节点查询和取消。配置修改检查版本，迟到的回复和工具事件不能回退已同步的局面；并发冲突时保留表单编辑，需点击“同步当前局面”确认。完成的数值来自真实报告；输入改变后结果标记过期。数据默认保存于 `outputs/agent/`，独立应用认证位于 `%LOCALAPPDATA%\Pokerlab\agent`（可用 `POKERLAB_AUTH_HOME` 指定）；API key与付费授权不持久化。

本轮已通过此独立入口的真实订阅验收：`existing_cli` / `gpt-6.1-sol` 将公开小型River底池从25改为20 bb，实际调用读取配置、修改、启动、查询任务和读取报告，任务完成。双方根EV为13.3332891464 / 6.6667108536 bb，实测exploitability为0.00932455063 bb（底池0.0466227531%），达到0.05%目标；复用缓存基线，记录的530次迭代不是本次新迭代。原生退出码0且已回收，API未配置也未调用；证据见 [真实验收](outputs/solver-agent-acceptance-20261008/acceptance.json)。Firefox中已实际读取报告和助手回答，主8765页面的单位、登录状态与双方169格已查看；本机 `existing_cli` 配置已持久化。首次SIWC本人授权和收费API仍无本轮真实验收。

## 离桌复盘助手（2026-10-29 起的主任务，第 1 阶段）

启动方式不变：在普通 PowerShell 里运行 `python -m pokerlab.solver.server`，打开 http://127.0.0.1:8765 。

- **Claude 订阅**（助手默认）：
  - 第一次使用前安装依赖：`python -m pip install "claude-agent-sdk>=0.2.174"`。
  - 在终端运行 `claude`，用 `/login` 登录你的 claude.ai 订阅账号。
  - 本应用不读取、不保存凭据。每轮先检查凭据来源，必须是订阅登录；额度用完或进入额外付费时停止，不会改为按量计费。
  - 服务进程的环境里如果有 `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL` 等变量，会拒绝发起请求。不要在 Claude Code 会话内部启动服务。
- **"手牌与对手"面板**：
  - 粘贴 PokerStars/GG 格式手牌，代码解析并重放校验，通过即计入统计。
  - 现场手牌直接在助手里用文字描述，助手整理成统一格式提交，你在面板里核对后点"确认计入统计"。
  - 玩家档案列出 18 项统计的样本数、原始比例、后验均值、90% 区间和倾向分（0–10，即高于人群水平的后验概率 × 10），以及标签、摊牌记录和备注。可以合并别名、设置 Hero 名字。
- **数据**：在 `outputs/coach/`，不进 Git；可用 `POKERLAB_COACH_HOME` 改位置。手牌修订只新增文件，确认和备注写入追加日志。
- **HHP 视频资料**：
  - 私人使用，放在 `outputs/knowledge/hhp/`，不进 Git；可用 `POKERLAB_KNOWLEDGE_HOME` 改位置。
  - 助手用 `search_hhp` 检索 200 个视频的字幕，用 `read_hhp` 读取原文，以及这段时间里从画面整理、通过重放校验的手牌记录（目前 24 个视频共 408 手）。
  - 助手用 `find_hhp_hands` 按牌型、位置、筹码深度、底池类型、牌面和行动线查这些手牌，也能用你记录的手牌找最接近的视频手牌。
  - 视频手牌有教学场景，也有讲解人分析的真实牌局（notes 开头写明），都不计入对手统计。
- **当前限制**：
  - 人群先验是未校准的占位值。
  - 统计到对手特质和 Node Lock 的校准是后续阶段。
  - PokerStars/GG 解析只用合成手牌验证过，还没用真实导出验证。
  - 只用于离桌复盘。

测试与真实验收：

```powershell
python -m pytest tests/test_coach_hands.py tests/test_coach_store.py tests/test_claude_provider.py tests/test_solver_agent.py tests/test_instructions_consistency.py -q
python scripts/coach_claude_acceptance.py
```

真实验收会用你的 Claude 订阅额度跑两轮短请求，结果写到 `outputs/coach-acceptance/<时间>/acceptance.json`。

## 输入、计价与边界

内存超限诊断（先按上文构建最新引擎）：在 PowerShell 运行 `python scripts/diagnose_tree.py "配置文件路径.json" --storage --output outputs/storage-diagnostic.json`。输出文件必须尚不存在。该模式保留游戏配置，比较同构／压缩四种存储方案，使用真实数组结构计数，不分配完整树；峰值余量仍是估计，不冒充实测。不加 `--storage` 则显示旧粗估及明确标注的缩树对照，仅用于诊断，不修改原配置。WSL 诊断子进程上限为 2GiB、每项 60 秒。

普通求解、CLI 和节点读取不再设置自动超时，旧配置中的 600 秒也不会终止任务。任务持续到精度达到目标、明确的迭代上限或主动取消；内存预算与进程回收保护仍然有效。显式测试／诊断可单独设置时限，不是工作台默认行为。

2026-10-16：已接通无硬锁压缩任务的合法组合稀疏存储，保留原16位量化及完整逻辑手牌顺序。当前203/449组合、SPR12.5、三街三个Bet＋3x树的精确预检从14.253降为13.231GiB，减少约1.022GiB数组；这是分配计划，尚非新版完整峰值。稀疏展开有速度开销，小型同案例对照见[进度](docs/PROGRESS.md)，不宣称此次同时提速。硬锁仍走原稠密路径，旧策略和CFR状态可读取，磁盘文件大小未优化。桌面Pokerlab启动入口不变。

用户确认本轮完整验收改用 **0.5% pot**（8bb起始底池对应0.04bb），新副本是 `outputs/performance-20261016-sparse/config.json`，原0.1%文件及研究保留。范围、SPR、每街尺寸、16线程和无限墙钟不变。后续用户释放资源后已实际尝试完整树，但13.231GiB需求仍高于当时11.073GiB安全预算，在分配前拒绝并回收，仍无新版完整耗时／RSS／实际精度。另减少稀疏临时复制，57项引擎、22项适配器与72项真实原生集成通过，小型速度变化约1%，不宣称宽树提速；资源充足后在项目根目录PowerShell执行以下命令，输出目录须尚不存在：

```powershell
python -X utf8 scripts/benchmark_config.py outputs/performance-20261016-sparse/config.json --cold --output outputs/performance-20261016-sparse/full-cold-02
```

2026-10-15当前引擎已启用DCFR临时缓冲复用，现有桌面／PowerShell启动入口不变。旧实现逐位回归和72项真实原生集成通过；SPR20历史树固定30次的迭代时间151.95→19.28秒，含精度测量的基线166.00→33.39秒，诊断峰值仅增加4.8MiB。该历史树不是当前203/449组合、每街三尺寸的目标树，30次也未达到目标精度。当前目标树新引擎验收因可用内存不足尚未完成，不将历史树的7.9倍迭代加速外推成全流程保证。完整配置、测试命令和证据见最新[进度](docs/PROGRESS.md)。

同日用户关闭游戏后，原树重试仍在分配前被14.253GiB需求／11.149GiB安全预算拦下，没有新的完整求解结果。资源探测现用WSL启动后的Windows可用内存，预留不变；通用异常取消保持串行锁直到监督器完成回收，取消等待不是求解超时。57项预算／回收测试和4项真实原生回归通过，详见上述进度。

2026-10-13完整三街三尺寸配置的受控预检由16.264降为14.253GiB：主要是明确限制分配器／线程开销并校准余量，同时将模型访问集合改成位图；不是实测内存已减少2GiB。另有快照分块读写与BR子树并行，保持原策略精度与求和顺序。任务 `4c8e056088c848b7bc7d573d7df67aa8` 已完整跑完：保留203/449组合、SPR12.5、三街各三个Bet尺寸和3x普通Raise，未设超时或降低原0.1%目标。冷启动全流程 **2小时34分54秒**，原生RSS峰值 **13.8494GiB**，1060次迭代实测 **0.0921778381% pot**；停止原因为达到目标，原生进程正常退出并回收。内存验收通过，五分钟速度目标未达到。同轮基线首次低于0.5%耗时41分57秒，这不是另跑0.5%的全流程时间。命令、分阶段耗时及数值核验见最新[进度](docs/PROGRESS.md)。

未收敛且正常到达迭代上限的基线会另存 `PLCFR001` 累积策略／regret 状态；提高最大迭代数后，同一树可从已保存迭代继续，界面区分历史迭代与本次新增。旧 `PLPOL002/003` 最终策略不能续算；主动取消、进程崩溃时尚不保存正在进行的状态，已收敛的旧基线要求更严格目标也可能需要重算。CFR 状态会额外占用磁盘，不能把保存耗时当作迭代速度。

公共牌旁的“图形选牌”打开按四种花色排列的 52 张牌，支持选择 Flop／Turn／River 初始牌面；求解后的发牌节点同样显示图形牌阵，只有合法分支可点击。策略网格按真实频率显示：Fold 蓝、Check/Call 绿、Bet/Raise 红、超过底池的进攻紫；恰好 100% 仍为红。同一节点、同一色系内，尺寸越大颜色越深，相同尺寸同色；按真实尺寸排序，不依赖动作排列顺序。图例、网格、动作按钮及具体组合频率条共用配色；颜色深浅表示尺寸，色块宽度表示概率。Raise 的比例为额外加注额除以跟注后的底池，All-in 按实际比例判断。最佳回应可能是纯策略，不会为彩色效果伪造混合频率。

- 输入 3/4/5 张公共牌自动选择起始街道；范围按 OOP、IP 排列，支持 `AA,AKs`、具体组合及权重、文本导入。Hero 可选双方，根节点始终 OOP 先行动。
- 原Solver工作台的pot是当前底池，stack是双方有效剩余筹码，新UI输入单位为bb，可以填小数（精确到0.01 bb，`chip_scale`=100）；EV和精度同为bb。新UI及独立助手的配置记录可选metadata `amount_unit="bb"`，一个原生数值单位对应1 bb；native执行前剥离此展示字段，计算和兼容字段 `target_unit="chips"` 保持原协议。旧报告没有该metadata时显示“原筹码单位”，不自动贴bb或换算金额。载入旧研究保留原始数字，须核对计价基准后再明确当前输入单位。Pokerstudio手牌的chips/USD仍按其独立适配规则验证。没有未来抽水、非等筹码边池或三人支持。
- 三街分别设置下注与加注尺寸，默认双方共用；“按位置配置尺寸／Donk”可给 IP 独立尺寸及 OOP Turn/River Donk。下注支持 `33%`、`10c`（bb模式为10 bb，原筹码模式为10筹码）、`a`；加注支持 `2x` 及更大倍数、`60%`（加注额 ÷ 跟注后底池，与 GTO Wizard 相同）、`a`。每类每街每位置最多3个尺寸，SPR上限20（设了每街加注次数时为40），超限拒绝，不静默缩树。加注报告为Raise-to，尚不支持任意绝对Raise-to输入。
- Preflop 行动线：`outputs/gtow-preflop/` 下有文件时，页面顶部可以选深度（100bb、150bb、200bb、400bb，默认 150bb；$800 = 160bb，最接近 150bb。模型是 8max straddle、cEV、7bb 开池），按座位点 action。手牌格和卡片显示当前座位的全部动作和频率（Raise、Call、Check、Allin、Fold）；走到两人底池后自动填双方范围、底池和有效筹码，选公共牌后解算，解算前可以在左侧改范围和参数。全下、三人以上和翻前结束的线只显示说明，灰色按钮是没有记录的线。范围框也可以直接粘贴 GTO Wizard Ranges 页 Copy 的内容。这些文件不进 Git。
- 节点页：手牌格可切换 Strategy / EV / Equity / EQR / 范围高度 / 比较 EV，可合并尺寸，右侧有手牌、汇总、Filters、Equity chart、Ranges、Breakdown、Blockers，顶部显示整体动作频率。发牌节点可以生成这一街的发牌报告。工作区下方有多牌面报告。频率按组合数算，EV / Equity 平均按阻断调整后的权重算，与 GTO Wizard 相同（DECISIONS D34）。
- 下注树模板：快速（每街 1 个尺寸）、标准（每街 2 个尺寸）、完整（每街 3 个尺寸）、完整省内存（3 个尺寸，河牌不加注），都限制每街最多加注 2 次。实测和内存估算见 `docs/PROJECT_STATE.md` A2e–A2g。WSL 默认只用一半内存；本机已在 `%USERPROFILE%\.wslconfig` 写 `memory=28GB`。内存不够时可以勾选“允许占用闲置后台程序的内存”，电脑可能变卡。
- 完整保留所选树的合法公共牌与后续决策，无未来价值截断。2026-10-06 已跑通 240/290 组合、SPR20、多尺寸和普通加注的原配置：16 线程约 11 分 33 秒、峰值 RSS 7.15GiB。500 次迭代实际 exploitability 为底池的 0.4542%，未达到 0.1% 目标；不代表所有宽范围、多尺寸树性能达标。详细分阶段结果见进度文档。
- 根 EV = 回收原底池及对手新投入 − 自己新投入；旧投入为沉没成本，无抽水时双方根 EV 和为 pot。Equity 是摊牌胜率／平局份额，不是 EV。零后验概率下未定义值显示为空。
- 特质强度 0–6 是 logit 偏置，不是百分点或下注范围弱牌占比。按规则叠加后在动作类别及尺寸内归一化；Neutral 保留基线。模板均为研究假设，牌力分类较粗，未经真实对局数据校准。
- Flop/Turn/River 的对手节点均支持具体组合及批量完整分布锁定。`auto_suits=true` 且无手动锁时使用引擎可证明的花色同构；有手动锁时 `expand_suits=true` 保留所有公共牌分支，不串花色。加新锁后可能需要重建更大的基线。16 位存储不合并下注尺寸，有数值量化误差；原生重评容差未放宽。含硬锁快照查询使用 f32 保留保存的概率精度，查询内存可能高于压缩求解。
- Player Profile（Fish、Calling Station 等）是对手每个决策上的虚拟激励（% 底池），只影响决策，不计入 EV；和“对手特质”是两种模型。默认数字已按 GTO Wizard 的页面文字核对。河牌的解和它一致；翻牌和转牌默认激励作用所有街，它只作用当前街，可在“作用范围”切换。
- 锁定后重解可以选上游：不锁（默认）、锁全部、只锁该玩家，和 GTO Wizard 的三个选项相同，它默认锁全部。
- 仍未实现自由分支增删编辑器、任意当前行动者根节点、细化听牌／阻断牌特征、全部翻牌汇总报告、取消／崩溃时CFR检查点、MCP或三人。每街三尺寸与普通加注的当前宽树已通过完整流程内存验收，尚未达到五分钟速度目标；下一步验证临时缓冲复用等迭代加速，见最新进度。

## 验证与资源

```powershell
python -m pytest -q
$env:POKERLAB_NATIVE='1'
python -m pytest tests/test_solver_native.py tests/test_workbench_native.py tests/test_action_sizes_native.py tests/test_solver_continuation.py pokerstudio/tests/test_solver_native.py -q
$env:POKERLAB_BROWSER='1'
python -m pytest tests/test_workbench_browser.py -q
wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- cargo test --release
python scripts/benchmark_flop.py --allin-raises --combined-only
```

原生与既有完整求解浏览器集成使用上述开关显式启用；新增范围、可用性和配置竞态测试在安装浏览器测试依赖后直接使用本机 Edge，无需启动真实模型。2026-10-08 默认回归147 passed / 32 skipped（55.07秒，当时未收集新增竞态文件）；随后竞态／可用性／桌面／内存合集51 passed（11.23秒），原生三个测试文件34 passed（45.90秒），完整工作台浏览器闭环1 passed（46.70秒），JS语法检查全部通过。详细证据和范围见 [进度](docs/PROGRESS.md)。

2026-10-13 日常默认值与启动竞态回归：`python -m pytest tests/test_workbench_usability_browser.py tests/test_solver_agent_races_browser.py tests/test_solver_startup_browser.py -q`，**11 passed，24.15秒**（6项启动、4项配置竞态、1项可用性）；既有助手测试5 passed，JS／Python语法检查通过。浏览器配置回归使用真实Edge及隔离配置服务，不重新求解大树；完整原生基准与26项保存结果审计另见进度文档。

Windows 32GB；实测WSL上限约15.47GiB。自动模式的安全预算是Windows当前可用内存减2GiB、WSL当前可用内存减512MiB及24GiB上限三者的最小值；手动模式再取显式上限的最小值。页面测量用于显示，实际启动在跨进程串行锁内重新测量，WSL监督进程再检查并设置地址空间上限，普通任务无自动墙钟时限。读取资源失败如实报错；不会用Windows总内存代替WSL可用内存，也不削减系统余量、范围、尺寸或原生数组预检。主动取消或显式诊断超时会终止并回收原生进程组，清理未完成临时快照，不删除已完成结果。报告峰值为原生Linux进程RSS，非整台Windows／WSL峰值。

历史资源诊断（2026-10-08）：宽范围保存配置的pot20副本保留完整范围和尺寸，两次启动均在分配前被安全预检拒绝；当时峰值估计5.65GiB、引擎数组4.66GiB、任务预算3.99GiB，退出码1且进程已回收。当时未缩树或削减系统预留。该副本与当时截图5.37GiB估计不同，不称为截图的精确复现；这也不是本次SPR12.5三街三尺寸实测的结果。历史证据见 [拒绝记录](outputs/jobs/3538b9c4cc0847f89856ea11d1de99cb/usability-acceptance.json) 与 [内存诊断](outputs/memory-budget-diagnosis-20261008.json)。

基线缓存绑定引擎、适配器、展开分支选项、局面、范围、双方尺寸、Donk 及求解参数；只改特质／兼容的锁复用基线，不复用旧模型 EV。首次节点查询仍需重建评估；重复查询使用最终策略与输入标识绑定的缓存，最多 256 项或 128MiB。命名库位于 outputs/library，研究位于 outputs/studies。升级这次静态路由后请先 Ctrl+C 停止旧服务，再按启动命令重开。

## Heads-up PLO4 AI（主任务，2026-10-23 起；与上面的 Hold'em 工作台相互独立）

当前主任务是建立覆盖完整一手 HU PLO4、接近均衡的可训练、可评估策略基线，范围和验收标准见 AGENTS.md / CLAUDE.md 的共用段。当前里程碑是受控的 turn + river 联合求解。代码在 `src/pokerlab/plo/`。状态、真实验证结果和下一步见 [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)，决策见 [docs/DECISIONS.md](docs/DECISIONS.md)，论文与实现的对应见 [docs/RESEARCH_NOTES.md](docs/RESEARCH_NOTES.md)。

在项目根目录的 PowerShell 中运行。所有输出目录或文件必须尚不存在，程序不会覆盖已有输出：

```powershell
python -m pokerlab.plo status
python -m pytest tests/test_plo_betting.py tests/test_plo_blockers.py tests/test_plo_evaluator.py tests/test_plo_engine.py tests/test_plo_engine_fuzz.py tests/test_plo_session.py tests/test_plo_subgame.py tests/test_plo_turn.py tests/test_plo_evaluate.py tests/test_plo_cli.py tests/test_plo_river_agent.py tests/test_instructions_consistency.py -q
python -m pokerlab.plo solve-river examples/plo/river_small.json --output outputs/plo/run/river-small
python -m pokerlab.plo query examples/plo/river_small.json outputs/plo/run/river-small/checkpoint.npz --history check
python -m pokerlab.plo evaluate examples/plo/hu_river_solver_vs_baseline.json --output outputs/plo/run/hu-river-solver.json --decision-log outputs/plo/run/hu-river-solver.decisions.jsonl
python -m pokerlab.plo evaluate examples/plo/hu_baseline_vs_baseline.json --output outputs/plo/run/hu-baseline-control.json
python scripts/plo_verify_showdown.py --rows 2000 --output outputs/plo/run/showdown-rows.json
python -m pokerlab.plo solve-turn examples/plo/turn_tiny_lp.json --output outputs/plo/run/turn-tiny --eval-every 50 --lp-limit 6 --spliced-baseline
python -m pokerlab.plo solve-turn examples/plo/turn_small.json --output outputs/plo/run/turn-small --eval-every 30 --spliced-baseline
python scripts/plo_budget_diagnostics.py --output outputs/plo/run/budget.json
python scripts/plo_resource_profile.py --output outputs/plo/run/resources.json
python scripts/plo_reference_error_control.py --output outputs/plo/run/refctl
python -m pokerlab.plo solve-turn examples/plo/turn_sample600.json --output outputs/plo/run/turn-600 --iterations 20 --eval-every 10 --workers 4
python scripts/plo_turn_agent_demo.py --output outputs/plo/run/turn-agent-controlled
python scripts/output_manifest.py outputs/plo/run --output manifests/outputs-run.json
python scripts/plo_agent_reference_eval.py --output outputs/plo/run/agent-reference
python scripts/plo_abstraction_eval.py river --board paired_flush --output outputs/plo/run/abs-river-paired_flush
python scripts/plo_abstraction_eval.py turn --config examples/plo/turn_sample1500.json --mode v1 --iterations 200 --workers 4 --output outputs/plo/run/abs-turn1500-v1
python scripts/plo_blueprint_validate.py --output outputs/plo/run/blueprint-validate
python scripts/plo_blueprint_train.py --iterations 150000 --max-minutes 40 --output outputs/plo/run/blueprint-v0
python -m pokerlab.plo evaluate examples/plo/hu_blueprint_vs_baseline.json --output outputs/plo/run/hu-blueprint.json
```

- **下注抽象**：默认 1/3、1/2、2/3、1 pot 四档精确比例，另加最小合法下注/加注，以及 pot 尺寸或短码 all-in 两个边界动作，最多 2 次加注。pot-limit 公式 h + P + 2c 由引擎和求解树共用。
- **河牌子博弈**：报告给出 exploitability = NashConv/2，分母是起始底池，评估平均策略，只对该范围和尺寸树成立。
- **turn + river 联合子博弈**（`solve-turn`）：固定 4 张 turn 公共牌和显式 range，一次 CFR 同时优化 turn 和全部 48 张河牌下的 river 策略，每对不相交手牌的河牌概率为 1/40。小实例与联合 LP 核对；`--spliced-baseline` 另报拼接法（各 river 单独求解后拼接）的 exploitability 作对照。摊牌计算有稠密（小实例参照）和按河牌容斥（内存线性，可到每方数千手）两种，`--workers N` 按河牌分块用线程并行；只测了受控筹码（SPR ≤ 2），结论只代表该子博弈。
- **诊断脚本**：`plo_budget_diagnostics.py` 分开报告抽样 range 内的 exploitability 与对参考 range 的误差；`plo_resource_profile.py` 分阶段测时间、CPU/墙钟比和峰值内存。
- **HU 对局 agent `river_solver`**：
  - 前三街用固定基线 `baseline-v1`。
  - 河牌先由公开动作用 Bayes 推出双方 range，再求解并按求解策略行动。决策日志记录 range 来源、求解配置和延迟。
  - 这是独立河牌求解，不是全局安全重解，也不宣称达到 PLO 均衡。
- **HU 对局 agent `turn_river_solver`**（2026-10-25）：翻前、翻牌用 baseline-v1（临时基线）；第一次 turn 决策时求解一个联合 turn + river 博弈，river 直接读同一个解，不独立重解；树外动作的处理和所有 fallback 都写入决策日志。
- **手牌抽象 v1**（2026-10-25，`pokerlab.plo.abstraction`）：信息抽象、收益精确。river 按胜率 × 阻断牌特征分桶；turn 按胜率 × 各河牌下价值变化 × 阻断牌分桶，river 桶细化 turn 桶，保持 perfect recall。效果在原参考游戏里用最佳回应评估。
- **四街蓝图 v0**（2026-10-25，`pokerlab.plo.blueprint`）：20bb、有限尺寸、粗抽象（不保持 perfect recall）的外部采样 MCCFR，四街都参与训练。agent `blueprint_v0` 四街都用蓝图；`turn_river_solver` 加 `early_policy` 后，翻前、翻牌和 range 模型也改用蓝图。
- **对局结果**：只用于功能验证和基线比较，不代表职业水平或实战盈利。
- **版本**：本地 Git 仓库（2026-10-25 建立），报告记录 commit；大型输出不进 Git，`manifests/` 记录路径与 SHA-256。
