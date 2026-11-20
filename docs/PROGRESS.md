# 实际进度（更新至 2026-11-01）

## 2026-10-25（第二轮）参考解续算；实际 agent 小规模对照；手牌抽象 v1；四街蓝图 v0

- **参考解续算**：turn-1500 在总迭代达到 200 时停止（48.8 分钟，没有触及 60 分钟上限），exploitability 0.0081% pot，峰值 1.84GB。
- **实际 agent**：在 3 个极小参考游戏上，走 agent 自己的抽样和求解路径。
  - 默认 150 次抽样时，误差为 0.006–3.1% pot；k=N 控制等于单次求解的误差。
  - 混合对照既不是上界或下界，也不可相加。
  - 按用户意见修正了上一轮关于采样误差的结论。
- **手牌抽象 v1**：信息抽象、收益精确、river 细化 turn（保持 perfect recall）。
  - river 3 块牌面（含 held-out）：v1 为 0.68–1.00%，旧映射为 6.5–45%，rank 分组为 1.2–1.7%。
  - turn 2 个实例：v1 为 0.33–0.35%，只按胜率为 0.30–0.31%，turn 特征需要重新设计。
  - turn 1,485 手时，内存峰值降 71%，时间降 13%。
- **四街蓝图 v0**：20bb、有限动作、粗抽象（不保持 perfect recall）的外部采样 MCCFR。
  - identity 验证收敛：river 1.34%，turn + river 0.108%。
  - 训练 150k 次，17.6 分钟。
  - 一条行动线上，蓝图的 turn/river 策略离局部精确解 6.07% pot。
  - 新增 `blueprint_v0` agent；`turn_river_solver` 加 `early_policy=蓝图` 后，翻前、翻牌和 range 模型都用蓝图，离开蓝图树时回退并记录原因。
- **工程**：
  - `solve-turn` 增加 `--max-minutes` 和内存预检，并在启动时记录 git 状态；
  - 河牌评测改用容斥后端，约 1,950 手时快约 13 倍；
  - 多个长跑同时运行时要限制 BLAS 线程。
- **测试**：PLO 110 passed（148.5 s）。全仓库 355 passed / 39 skipped / 0 failed（227.9 s）。偶发的 Hold'em 浏览器测试这次通过，本会话累计 15 次、失败 5 次，没有改动它。Hold'em 引擎、vendor 和 Pokerstudio 都没有改动。

## 2026-10-25 参考误差定位；turn + river 容斥与线程；联合策略接入决策；Git 基线

- **Git**：建立本地仓库，基线 `9a806cd`；报告记录 commit；大型输出用 `manifests/` 记录 SHA-256（D21）。嵌套的引擎检出不纳入，它的本地修改等于已跟踪的 patch。
- **参考范围误差**：k=N 时经过同一映射，与直接评估同为 0.0220%。只换抽样 0.32%（未抽中的手牌用精确策略，不能代表 agent），只换映射 44.9%。在当前控制实例中，最近河牌排名映射是已确认的大误差来源；实际 agent 的采样及逐手重解误差尚未量化。替换实验不是可相加的分解（D19 更正）。
- **turn + river**：
  - 新增按河牌的容斥后端：稀疏 compat 加扁平索引 win，内存线性；稠密后端保留为参照。
  - 在加权、非对称案例上，两种后端的价值和最佳回应相差 5e-13，都收敛到 LP。
  - 598 手每次迭代 13.5 s → 8.7 s。`--workers` 线程：1,485 手时 4 个线程 1.63 倍，状态逐位相同，内存多约 2 MiB。
  - 1,485 × 1,480 短跑：30 次迭代后 0.84% pot。正式预算定为 200 次，尚未运行。
- **联合决策**：新 agent `turn_river_solver`，turn 与 river 读同一个联合解。受控 turn 局面的 6 个场景都核对过概率；fallback 都写日志（D23）。
- **NLHE 预算诊断**：约 11GiB 是启动时 Windows 可用内存减 2GiB 的结果；13.85GiB 成功的那次受 WSL 安全值 14,727 MiB 约束。没有调阈值。
- **测试**：PLO 104 passed（135.3 s）。全仓库 349 passed / 39 skipped / 0 failed（215.5 s）。偶发的 Hold'em 浏览器测试这次通过，本会话累计 14 次、失败 5 次，没有改动它。Hold'em 引擎、vendor 和 Pokerstudio 都没有改动。

## 2026-10-23（夜）主任务修订为近似均衡策略基线；turn + river 联合求解

- **指令**：主任务改为"覆盖完整一手 HU PLO4、接近均衡的可训练、可评估策略基线"。对手建模和剥削暂缓，baseline-v1 标为临时实现。AGENTS.md 与 CLAUDE.md 的共用段同步修改，一致性测试通过。决策见 DECISIONS D0′、D18–D20。
- **turn + river 联合求解**：
  - 新增 `subgame/turn.py`、`subgame/turn_reference.py`、CLI `solve-turn`、`examples/plo/turn_*.json`，以及 7 项测试。
  - 一次 CFR 同时优化 turn 和 48 张河牌下的 river 策略，河牌概率 1/40。
  - 6×6 实例与联合 LP 一致：求解值与 LP 相差 0.00029 筹码，exploitability 3.2e-5% pot。
  - 拼接法对照：60×60 上拼接 1.11%，联合 0.026%。
- **诊断与资源**：
  - 新增 `scripts/plo_budget_diagnostics.py`、`scripts/plo_resource_profile.py`。
  - 抽样 range 在样本内的 exploitability 约 0.1%，但放到参考游戏里误差为 8.7–19.1%。
  - PLO 求解器只用 1 个核（CPU/墙钟 ≈ 1），峰值不超过 1,146 MiB。
  - 判断现阶段不需要云资源。
  - 详见 PROJECT_STATE §4.9–4.11。
- **文档更正**：
  - 全范围 turn 的内存需求改为按实测节点数估算：约 42GB 到 14.5TB。原来写的"PB 级"和 libratus_notes 中"约 4GB"的粗估都不对。
  - 本轮文档里误写的日期 2026-10-24 改为本地日期 2026-10-23。
- **测试**：PLO 测试 95 passed（113.7 s）。全仓库 340 passed / 39 skipped / 0 failed（216.1 s）。原有的偶发 Hold'em 浏览器测试这次通过；本会话累计 13 次，失败 5 次，没有改动它。Hold'em 引擎、vendor 和 Pokerstudio 都没有改动。

## 2026-10-23（晚）主任务改为 HU PLO4 AI；河牌求解策略接入对局

- **指令**：主任务改为"可复现的 Heads-up PLO4 AI"。AGENTS.md 与 CLAUDE.md 共用同一段主任务描述，由 `tests/test_instructions_consistency.py` 检查两处一致；AGENTS.md 原有的 Hold'em 约束全部保留。
- **下注语义**：pot-limit 公式统一到 `src/pokerlab/plo/betting.py`（P/h/c，h + P + 2c），引擎和求解树共用。默认抽象改为 1/3、1/2、2/3、1 pot 四档精确比例，另加边界动作，最多 2 次加注。四个独立期望值已测。
- **验证**：
  - 新增非均匀、非对称 blocker 测试和 Kuhn 净值换算测试；
  - 新增 `scripts/plo_verify_showdown.py`，全范围完整分块对照，相对误差 2.1e-13；
  - PLO 批量排名改为按底牌对查表，全范围用时 0.024 s（原 3.9 s）。
- **决策接入**：新增 `baseline.py`（baseline-v1）、`public.py`、`river_agent.py`（`SolverRiverAgent`），评测报告增加决策日志摘要和深度标注。HU duplicate 对局能跑通，结果都不显著，详见 PROJECT_STATE §4.6。
- **测试**：PLO 测试 88 passed。全仓库为 332 passed / 39 skipped / 1 failed，唯一失败的是原有的偶发 Hold'em 浏览器测试（本会话 12 次中失败 5 次，首次失败在任何改动之前）。Hold'em 引擎、vendor 和 Pokerstudio 都没有改动。

## 2026-10-23 新增 PLO4 研究模块（独立包，未改动 Hold'em 引擎）

- **代码**：新增 `src/pokerlab/plo/`、`tests/test_plo_*.py`（63 项）、`tests/plo_rules_reference.py`（独立规则实现）、`examples/plo/`。
- **新增文档**：`docs/PROJECT_STATE.md`、`docs/DECISIONS.md`、`docs/RESEARCH_NOTES.md`、`docs/research/`。
- **同步修改**：`CLAUDE.md`、AGENTS.md（加了 PLO 指引）、ARCHITECTURE（加了 PLO 模块节）、README（加了 PLO 命令）。
- **独立审查**：确认 5 个问题并已修正。最严重的是有前注时结算崩溃；另有 duplicate 模式可能泄露信息、抽水按主池优先扣除、抽水浮点误差，以及树与引擎在底池小于最小注时不一致。修正后 60,000 手随机局与独立规则实现零差异。
- **测试**：修正后 PLO 测试 63 passed。全仓库最后一次为 307 passed / 39 skipped / 1 failed，失败的是已知偶发的 Hold'em 浏览器测试 `test_range_editor_browser.py::test_real_range_click_wheel_drag_percentage_and_undo`，本会话 7 次中失败 3 次，第一次在任何改动之前。本轮开始前基线为 245 passed / 39 skipped。
- **内容与限制**：实测结果、限制和下一步命令都写在 PROJECT_STATE。Hold'em 工作台的原生测试和浏览器验收本轮没有重跑。

## 2026-10-16 后续：减少稀疏临时复制，完整原树再次受宿主预算阻塞

用户释放内存后授权完整运行；保存的0.5% pot副本、范围/SPR/三街三尺寸＋3x、16线程、无限墙钟保持。正式命令 `python -X utf8 scripts/benchmark_config.py outputs/performance-20261016-sparse/config.json --cold --output outputs/performance-20261016-sparse/full-cold-01` 已实际执行。启动Windows可用13387MiB，扣除2GiB后任务预算11339MiB（11.073GiB）；WSL安全14709MiB。原树计划13.23086GiB，在完整数组分配前拒绝，exit1且process_reaped=true、无迭代样本。记录 `full-cold-01/benchmark-summary.json` 与 `native.stderr`。**没有完整耗时、RSS峰值或实际精度，失败诊断的短墙钟/采样RSS不能代替这些结果。** 后续资源快照仍约13.1GiB Windows可用；需约15.23GiB可用才满足现计划和预留。没有放宽保护或自动删动作。

本轮已接通两个热点改动：压缩regret-matching直接从稀疏i16和占位值初始化本来必需的完整f32策略，省去中间i16展开；BR概率归一化直接读取存储视图，省去另一份f32复制。保留全逻辑组合、原f64求和/f32归一化顺序、16位量化和scale。源码备份 `hotpath-before/`，旧二进制保留为candidate-solver-v2，当前candidate-solver-v3与桌面入口在串行锁内原子更新，SHA256 `49d2095c6e2aed2f80805e96195653d5e95fddd998e4313a52f5ab0d12ea0aa8`。累计vendor补丁与源码校验通过，无提交/推送。本项主要减少复制，原树常驻数组和13.23086GiB预检没有下降。

验证沿用上一节WSL release/单测试线程命令：vendor **57 passed / 4 ignored，12.54秒**；native **22 passed / 1 ignored，0.67秒**；相同四文件真实原生Python集成 **72 passed，39.46秒**。新增旧稀疏路径对照三街、1/4线程、DCFR折扣边界、全部word/scale/EV/finalize；直接概率读取另以全部65536个u16值、零质量、f32极小/大值逐位对照原复制流程。这是实现等价性测试，独立小型扑克参考继续由Python集成覆盖。

同一61/71组合SPR2小型Flop，各3次串行1000步：纯迭代中位数6.20057→6.12910秒，含测量基线7.06348→6.99044秒（约1.0%减少）；101个精度样本逐位相同。最大RSS48.21→48.59MiB。背景负载未隔离，改善幅度较小，**不称为稳定提速，也不外推到完整宽树**。证据 `hotpath-benchmark/comparison.json`。下一步若必须在当前约11.1GiB预算容纳冷CFR，需要另做累计策略无损编码/分块存储；少量旧最终策略采样仅支持研究该方向，不能证明训练全程峰值或宣称后端已实现。

另增加只读完整结果核验 `outputs/performance-20261016-sparse/audit_complete.py RUN目录`，区分均衡精度和BR gap，核对原完整树、0.5%目标、实际稀疏计数、冷缓存、进程回收及三份策略头。6项轻量测试通过（0.020秒），小型smoke被正确拒绝为原树证据；只读文件头不等同全策略重载验收。本轮未改界面/未浏览器验收，桌面入口不变。资源足够后重跑请使用新的 `--output outputs/performance-20261016-sparse/full-cold-02`，保留01失败记录。

## 2026-10-16 合法组合稀疏存储已实现；完整原树等待资源，未宣称新性能达标

用户明确本轮改用0.5% pot。新副本 `outputs/performance-20261016-sparse/config.json` 相对原 `outputs/performance-20261013-v2/config.json` **只有target从0.1改为0.5**，原文件SHA256仍为 `f38858b106f0413feb33da24f471208a37b393c0002ce601322998f9c6d8a360`。保留9h8h2c、203/449有效组合及权重、pot8/stack100（SPR12.5）、Flop33/66/100%、Turn/River33/50/75%、三街3x普通加注、16线程和完整合法后续。目标0.5%即0.04bb；无墙钟超时，最大迭代仍100000，不把迭代上限停止当作达标。

无硬锁压缩任务现按各canonical公共牌只保存合法手牌，并为每行动保留一个非法槽占位值，维持原16位量化scale。只改变物理布局，不删逻辑组合、公共牌或动作；共享原合法索引，无新增每节点指针。逻辑求解、模型、BR、节点查询均经过稠密视图；其独占临时缓冲池最多额外1MiB/线程，含在原256MiB余量内。缓冲归还保留已初始化长度，展开完整覆写。硬锁仍用稠密路径，公共API明确拒绝稀疏＋硬锁；bunching、上游bincode也不支持稀疏。PLPOL002/003和PLCFR001维持稠密逻辑文件格式，旧文件可加载，磁盘占用本轮未缩小。最终模型里非法槽可归并，合法word/scale不变，最终策略不能续算CFR。

### 原树精确计划与资源边界

新旧二进制对同一配置执行仅计数诊断，均未分配完整树：`outputs/performance-20261016-sparse/storage-comparison.json`。物理行动元素3,462,479,904→3,193,805,142；引擎数组及节点14,856,895,090→13,759,626,908 bytes，确切减少 **1,097,268,182 bytes（1.02191GiB）**。预检14.25277→**13.23086GiB**，原分配器/线程/瞬时余量不变。这是结构计数，不是RSS峰值。原独立计数的理想1.0618GiB没有计入保留量化所需的占位数据，不能照搬为实际节省。

本轮资源快照Windows可用约8.4–8.6GiB、安全预算约6.6GiB；WSL可用约14.85GiB、上限15.47GiB，无残留Solver/监督进程。用户明确回复“暂时不方便，先完成优化与验证”，因此**没有启动完整203/449组合原树**，新耗时、峰值、实际精度均为空，见 `acceptance-status.json`。并非WSL上限仍容不下：新计划已低于其安全上限，当前瓶颈是宿主可用量；按现预留需Windows可用约15.23GiB，实际启动仍复测。没有关闭用户应用、重启WSL或放宽预留/限额。

### 数值与工程验证

- WSL `RUSTFLAGS='-C target-cpu=native' cargo test --release --locked --target-dir outputs/performance-20261015/build -p postflop-solver --lib -- --test-threads=1`：**55 passed / 4既有ignored，12.18秒**。三街f32/u16的稀疏/稠密策略、regret、scale和EV逐位一致；Flop/Turn连续20步后另核验63/64/65、255/256/257、1023/1024/1025参数，不把此边界抽样说成1025步完整轨迹。覆盖同构/展开的计划与实际数组、零合法组合、嵌套借用、池上限及污染缓冲覆写。
- 同环境根 `cargo test --release --locked --target-dir outputs/performance-20261015/build -- --test-threads=1`：**21 passed / 1既有微基准ignored，0.67秒**。包括双向存储布局CFR续算、PLPOL002/003兼容、非法槽不同时合法word/scale保留、冻结策略及BR独立sum-product重评。
- PowerShell `$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_solver_native.py tests/test_workbench_native.py tests/test_action_sizes_native.py tests/test_solver_continuation.py -q`：最终二进制 **72 passed，40.85秒**。独立River矩阵/LP、解析跨街EV、纯策略枚举与牌张冲突等数值参考保持；API/缓存/取消测试不冒充独立数学参考。
- `python -m pytest tests/test_benchmark_config.py tests/test_benchmark_iterations.py tests/test_memory_budget.py tests/test_workbench_cleanup.py -q`：**73 passed，0.56秒**。新增完整冷启动入口 `--cold --output <新目录>`，基线/检查点/模型/BR文件全局部隔离，明确检查没有旧缓存复用；保留配置线程数，默认无限墙钟。
- 同一小型61/71组合、SPR2、每街单Bet＋All-in Raise案例的完整模型流程：稠密/稀疏根策略、逐组合报告、精度、覆盖和EV逐字段完全相同；同固定模型旧Hero EV64.47585297→BR79.03137970，独立重评误差0，见 `model-equivalence.json`。这是布局等价性验证，**不是用户完整宽树的性能验收**。
- 新冷启动入口已用上述小型案例真实跑通，cache_hit=false、resumed_iterations=0，三份最终策略存在、exit0/reaped。此前初版记录 `smoke-complete-cold/` 的80次基线达到0.0977292% pot、全流程3.1467秒/RSS51.17MiB，仅验证入口。

### 小型同树速度对照：节省内存伴随展开成本

`smoke-comparison.json` 记录同一61/71组合、SPR2、147公共/154610原生节点案例的旧稠密与最终稀疏二进制各3次串行1000步。原始配置和树统计相同，0到1000每10步共101个精度样本逐位一致，最终0.00151730% pot；这是固定迭代诊断，不是当前大树0.5%验收。

稠密→稀疏中位数：纯迭代 **4.81238→6.26258秒（增加30.1%）**，含精度检查的基线 **5.66147→7.13767秒（增加26.1%）**。三轮最大RSS50.29→48.03MiB，exit0/reaped、采样swap0。背景负载未隔离，不能把该比例外推到宽树；去掉重复清零仍未消除展开/散写开销，**本轮是存储节省，不是已验证的速度优化**。下一项可先让热点直接处理稀疏列，减少临时展开，再实测原树。没有拿此前临时缓冲复用的历史提速抵消或掩盖此次代价。

原生程序已在串行锁内原子替换，最终SHA256为 `a1daaba0b0bad1df8283bd2191cb8e4b5ef9cd7341c5161ab216bbac7b1bd43d`，桌面入口不变。源码/旧二进制备份在 `outputs/performance-20261016-sparse/before/`，中间/最终候选分别保留；累积vendor差异已更新 `expanded-suits.patch`，前版另存 `expanded-suits-v5-dcfr-scratch.patch`，verify_engine通过，无提交/推送。生产未启用的上游bincode特性尝试离线编译时因依赖未缓存而未执行，不宣称验收该特性；原生自有快照已实际验证。此次未改界面、未另做浏览器验收。

后续完整冷启动命令（项目根目录PowerShell、输出目录须未存在）：`python -X utf8 scripts/benchmark_config.py outputs/performance-20261016-sparse/config.json --cold --output outputs/performance-20261016-sparse/full-cold-01`。资源仍不足时会明确拒绝，不自动缩树。冷CFR的两份16位行动数组仍是主要开销，没有数GiB重复EV数组可直接释放；若必须在当前约6.6GiB预算运行，需另做无损分块编码或分块外存状态，先实测压缩率/I/O并维持监督，尚未实现。小幅节点压缩不能补足当前缺口。

## 2026-10-15 游戏关闭后复查：回收与资源探测修复，原树仍受宿主预算限制

用户授权继续后重新测量并实际重试原203/449组合、SPR12.5、三街三尺寸＋3x树的30次冷启动对照入口。保存配置SHA256仍为 `f38858b106f0413feb33da24f471208a37b393c0002ce601322998f9c6d8a360`，0.1%目标／无限墙钟／范围／尺寸均未改；该30次模式仅用于A/B诊断，不是精度验收。记录 `outputs/performance-20261015/full-original-30-recheck/`：预计14.253GiB，实际启动安全预算11.149GiB，在完整数组分配前拒绝，exit1、process_reaped=true、无迭代精度样本。因此仍没有本轮完整原树的新耗时、峰值或达标结果，不能将拒绝时的约11MiB诊断峰值当成求解峰值。

修复 `workbench.py` 的通用异常取消路径：写入取消标记后继续持有串行锁，轮询等待监督器退出；不再10秒后只杀WSL客户端，重复Ctrl-C也不能提前解锁。资源探测在读取WSL后重新测量Windows可用物理内存，避免冷启动前的偏高读数进入预算，成功快照增加测量时间与探测耗时；Windows 2GiB／WSL 512MiB预留和原生限额不变。没有证据表明当前不足由残留Solver引起；这些修复不宣称释放了几GiB内存。桌面／PowerShell启动方式不变，未修改原生数学或保存研究。

验证：`python -m pytest tests/test_memory_budget.py tests/test_workbench_cleanup.py tests/test_benchmark_iterations.py -q`：**57 passed，0.31秒**，包括真实轻量Python监督器／子进程回收，其余故障注入与预算边界明确是模拟。`$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_workbench_native.py::test_cancel_native_group_and_timeout tests/test_workbench_native.py::test_exported_policy_independent_evaluation_and_cache tests/test_solver_continuation.py::test_workbench_resume_matches_fresh_uninterrupted_native_run -q`：**4 passed，6.24秒**，包括真实WSL取消／显式测试时限、独立River策略矩阵重评及续算与连续求解一致；不是宽范围Flop验收。备份与汇总在 `outputs/performance-20261015/resource-followup/`。

另以独立只读计数器核算存储机会（`outputs/performance-20261015/memory-audit/`）：本树没有单动作决策节点，不能靠删除单动作缓冲节省内存。当前累计策略／regret共12.899GiB，节点0.662GiB，IP／机会CFV约0.272GiB；regret已原地复用为finalize后的逐行动CFV，并无额外完整EV副本可删。按36个Turn、1429个River同构代表牌逐一核算，后续公共牌冲突组合占策略／regret1,117,183,144 bytes，加IP CFV共可少存约1.0618GiB。独立行动／IP元素计数与引擎计划完全一致；计数器0.0585秒、RSS9388KiB，未建完整树或求解。**稀疏存储尚未实现**；理想扣除后预检仍约13.191GiB，且不含新索引开销，仍超过本次11.149GiB预算。后续改造必须处理稠密逻辑索引、同构、快照和压缩scale对量化的影响，不能直接删非法项后宣称数值不变。


## 2026-10-15 DCFR临时缓冲复用：数值一致，历史树迭代加速，当前大树受资源阻塞

已在原项目／原引擎实现拥有型线程局部缓冲池，用于DCFR的行动CFV、策略／reach、归一化分母、机会节点reach及f64累加区。取出缓冲即释放池借用，递归父子和Rayon任务独立持有；只借出精确capacity，所有MaybeUninit输出按逻辑长度切片。每线程闲置f32最多768KiB、f64最多256KiB，各最多32条（另有小量元数据），计入原256MiB临时余量。浮点归并顺序、16位量化、DCFR折扣／平均策略重置、机会概率、范围、树与停止精度未改。稳定版路径启用，原nightly custom-alloc路径保留。普通求解仍无自动超时，新局面默认0.5% pot不变，保存配置仍为原0.1%。

原二进制、源码及累积补丁备份在 `outputs/performance-20261015/before/`；旧／新诊断二进制分别为 `baseline-solver`、`candidate-solver`，均使用native CPU、thin LTO、单codegen unit。现有启动入口的 `target/release/pokerlab-solver` 已在跨进程串行锁内原子替换成通过验证的候选，SHA256见 `activation/result.json`。没有修改用户保存的范围／局面／研究，没有重置、清理、提交或推送。vendor新增源码均纳入 `expanded-suits.patch`（只使用intent-to-add使完整差异可记录），前版保存为 `expanded-suits-v4-single-player-mes.patch`；verify_engine另外拒绝未记录的src文件。

### 本轮真实数值验证

- `wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- env RUSTFLAGS='-C target-cpu=native' cargo test --release --locked --target-dir outputs/performance-20261015/build -p postflop-solver --lib -- --test-threads=1`：**47 passed / 4既有ignored，11.51秒**。新增12种实际小树配置覆盖三街、f32/u16、同构／展开、锁／零reach及1／4线程；逐次比较每个节点strategy、regret与scale原始位。River真实连续1027次；Flop/Turn连续20次后另测63/64/65、255/256/257、1023/1024/1025参数边界，共29次，后者不是1027次完整轨迹。MES／EV及finalize后CFV、根逐组合EV／Equity一致。冻结旧DCFR源码仅编译进测试，是实现等价性证据，不冒充独立牌力计算。补充借用冲突fallback后，过滤 `solver_scratch` 重跑 **6 passed，2.93秒**。
- 同一WSL构建的根 `cargo test --release --locked --target-dir outputs/performance-20261015/build -- --test-threads=1`：**19 passed / 1微基准ignored，0.26秒**，含CFR续算、BR和快照不变量。
- `$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_solver_native.py tests/test_workbench_native.py tests/test_action_sizes_native.py tests/test_solver_continuation.py -q`：**72 passed，42.95秒**，调用已更新的真实原生引擎。独立River矩阵／LP、解析跨街EV、固定对手纯策略枚举重评、牌张冲突、加注与退款、Node Lock、保存／加载及进程回收均通过；缓存用例与冷求解用例并存，不把全部72项称作独立数值参考。
- `python -m pytest tests/test_benchmark_iterations.py tests/test_memory_budget.py -q`：**45 passed，0.15秒**。诊断取消超过10秒仍保持锁等待监督器回收，重复Ctrl-C不会只杀WSL客户端后提前解锁。
- WSL `python3 -m unittest discover -s tests -p test_native_worker_diagnostics.py -v`：**3 passed，0.656秒**；合成小子进程验证显式二进制／资源记录、取消和失败回收，不是扑克数值测试。最终release构建与完整补丁验证通过。

### 同树速度对照的实际范围

当前目标树仍是 `outputs/performance-20261013-v2/config.json`：203/449有效组合、SPR12.5、每街三个下注与3x普通加注。30次旧引擎诊断在分配前被拦下：预计14.253GiB、当时安全预算11.459GiB；没有删动作、缩范围或放宽预算。记录 `full-original-30/`，进程退出并已回收。最新资源快照 `latest-resources.json` 为Windows可用13212MiB、安全11164MiB，WSL安全14473MiB；用户尚未回复本轮释放资源问题。因此**当前完整树的新引擎速度／完整峰值／达标耗时尚未测出**，2026-10-13的2小时34分54秒与13.85GiB仍是旧引擎完整验收记录。

补充对照使用此前已保存的SPR20历史树，不替代上述目标：9h8h2c、pot10、stack200、240/290有效组合；Bet为33/50/75%、66/33%、75/33%，Raise为3x/3x/All-in。7075006原生节点、1753041780行动元素；16线程、压缩／安全同构、受控glibc参数相同，冷启动固定30次，原0.1%目标字段不改但明确不按目标提前停止。两份原始配置SHA256、完整树统计和0/10/20/30次精度值完全相同。一次候选启动曾因临时安全预算5.68GiB被拒，之后资源恢复，重试成功；拒绝记录保留。

- 迭代本身：**151.947835秒 → 19.281925秒（7.880倍）**。
- 精度测量：14.043337秒 → 14.090087秒；本轮未优化此遍历。
- 基线阶段含测量：**166.004599秒 → 33.387617秒（4.972倍）**。
- 外层墙钟：171.608452秒 → 35.467706秒；不是完整模型／BR／保存流程。
- 诊断RSS峰值：7478435840 → 7483465728 bytes（6.96484 → 6.96952GiB），增加4.796875MiB；两次swap均0且exit0/reaped。未finalize的诊断没有触碰全部后处理存储，不能拿该RSS冒充完整流程峰值。
- 30次实际exploitability两者均为2.04485177994（20.44851875% pot），**均未达到0.1%**；这只是固定迭代性能诊断。
- 原生累计system CPU从1032.138降到101.655秒，自愿上下文切换从200315963降到16744937；支持减少分配等待的解释，但未逐一归因系统调用。单次顺序A/B，后台系统负载未隔离，不宣称统计置信区间。

复现命令：`python -X utf8 scripts/benchmark_iterations.py outputs/performance-20261015/historical-spr20-config.json --iterations 30 --binary outputs/performance-20261015/baseline-solver --output outputs/performance-20261015/<全新A目录>`；B改为 `candidate-solver` 和另一新目录，必须串行。对当前完整树只替换配置路径，仍需足够安全预算。脚本保存来源／二进制hash、每10次实际精度、迭代／精度检查耗时、RSS/VmPeak/swap、CPU和上下文切换；不载入基线／检查点、不生成巨大策略文件、不编译模型或BR、无自动超时。结果汇总 `outputs/performance-20261015/comparison.json`。另有50MiB左右的示例Flop 100次冒烟A/B，仅用于诊断协议与精度一致性，不作宽范围性能结论。

下一项：资源满足后对原203/449三街三尺寸树运行同样冷启动A/B及目标精度完整验收，测量实际收益；然后优化仍占14秒的精度遍历（须另保留旧评估参考），而不是先调低目标或减少精度检查频率。五分钟目标尚未证明达到。

## 2026-10-13 日常新局面默认0.5% pot

用户明确选择“0.5% pot：优先探索速度”。工作台新局面和无既存状态的独立助手采用该均衡基线默认值，增加“新建日常局面”按钮和单位／指标说明。载入示例、导入、保存研究、现有助手状态继续保留原目标，启动页面不自动写回。原生CLI、旧数值案例和完整基准配置未更改；完整大树保持原0.1%目标并已达标完成，见下节。

最终命令 `python -m pytest tests/test_workbench_usability_browser.py tests/test_solver_agent_races_browser.py tests/test_solver_startup_browser.py -q`：**11 passed，24.15秒**（6项启动、4项配置竞态、1项可用性）。使用真实Edge、隔离配置REST服务；外部助手provider与资源夹具均明确隔离，没有启动原生求解，也不代替完整大树数值验证。既有助手测试 **5 passed**，JS／Python语法检查通过；最终 `app.js`、`agent.js`、`integration.js` 三份JS语法检查通过。

修复的启动竞态：示例响应超过原助手的5秒等待时，迟到默认可能覆盖已恢复的旧配置；现等待实际初始化Promise。用户在加载期间的编辑／导入优先，示例按钮在数据就绪前禁用，示例加载失败仍恢复后台配置并显示错误；首次后台配置版本尚未取得时不写回。测试覆盖超过5秒的延迟、请求失败、真实输入及程序化导入，不再依赖事件的 `isTrusted` 判断用户变更。

前期usability运行因大树占用时安全预算为0而失败；大树完成后资源恢复并通过。随后一轮7 passed／1 failed暴露导入竞态，修复后获得上述最终11 passed。此前隔离快速验收的6个断言组只属于中间检查，不作为最终通过结果。测试服务和浏览器均已关闭，未重启生产服务。

## 2026-10-13 完整三街三尺寸实测完成：0.1%达标，速度未达标

用户释放资源后，使用保存的 `outputs/performance-20261013-v2/config.json`，PowerShell命令为 `python -X utf8 scripts/benchmark_config.py outputs/performance-20261013-v2/config.json --threads 16`。没有传入超时，0.1% pot（0.008bb）目标未更改。实际执行前复测Windows可用18026MiB、WSL可用15239MiB；监督限额15435120640 bytes（14.375GiB），保留原双系统预留。最终记录位于 `outputs/jobs/4c8e056088c848b7bc7d573d7df67aa8/`：`benchmark-summary.json`、`result.json`、`worker.json`、`acceptance-audit.json`。

实际配置：9h8h2c、pot8bb、stack100bb、SPR12.5；OOP/IP有效组合203/449，范围及权重逐字段保留。Flop Bet33/66/100%，Turn/River均33/50/75%，每街普通Raise3x；没有削减尺寸、限制加注次数或截断Turn/River。使用16位存储、引擎按对称范围证明的花色同构、16线程；无手动锁、无抽水。完整行动树8461公共节点，展开后11103650个原生节点（含7129035终局、12159机会节点）、3462479904行动元素。实际引擎分配14856895090 bytes，与分配前数组计划一致。

冷基线（cache_hit=false、resumed_iterations=0）第1060次达到0.007374227046966553bb，即 **0.0921778381% pot**，`baseline_stop_reason=target_met`。**完整墙钟9294.216秒（2小时34分54秒），原生RSS峰值14870650880 bytes（13.8494GiB），虚拟地址峰值13.9471GiB，监督采样swap=0；exit0、process_reaped=true。** 该配置完整流程内存验收通过，五分钟速度目标未达到。

原生分阶段：建树／初始化0.706秒、均衡基线8841.297秒、模型编译140.720秒、Hero BR5.711秒、策略重评32.055秒、报告7.956秒、策略保存合计65.787秒；原生总计9101.754秒。原生还有7.521秒未单列工作；外层墙钟另多192.462秒，包含但未分别计时的串行锁等待、资源探测、WSL／监督／启动／解析／退出与收尾，不能全归因于某一项。原生快照保存已计入原生总计，不能再加一次。

固定模型为Station2＋Overbluff2（三街）＋give-up3（仅River）。同一固定对手下，Hero原均衡策略EV4.3300881386bb → BR6.3134994507bb，增加1.9834113121bb；双方根EV和为8bb。导出BR独立sum-product重评同为6.3134994507bb，误差0≤0.00016bb容差；固定对手response gap为0，**不冒充均衡exploitability为0**。对手摘要在优化前后内部校验一致。模板仍是研究假设，不是真实对局实测的玩家结论。

同轮首次测量低于0.5%为第300次、2517.173秒（41分57秒）；低于0.3%为第360次、3016.513秒（50分17秒）；低于0.1%为第1060次、8841.295秒（147分21秒）。另有第200次首次低于0.1bb，1685.147秒；0.1bb在本局等于1.25% pot。这些是基线采样时间，**不是另跑各精度的全流程耗时**。900次附近平台及1030次重置后反弹均保留在原日志，没有按历史最低值伪造停止。记录见 `precision-milestones.json`。

26项保存结果审计通过：原配置与native echo、完整数组计划、冷启动、目标与实际精度、冻结校验结果、独立重评、进程回收、策略文件存在／PLPOL003头部身份。三份策略共19.492GiB；审计仅读文件头与大小，没有额外完整加载或全文件hash，不冒充第二次独立求均衡。

已通过现有8765服务保存命名研究“**完整Flop 三街三尺寸3x · 0.1%达标 · 2026-10-13**”，研究ID `f79af0c4219441a284f16d34a7da9d39`，位于 `outputs/studies/f79af0c4219441a284f16d34a7da9d39/`。配置仍为0.1%目标，三份策略文件均复制完成；另行保存约46.11秒，不计入上述原始基准墙钟。桌面Pokerlab刷新后可在“已保存研究”中选择该名称并点“打开”。真实Edge无头重开已通过，耗时45.281秒，原0.1% pot目标、9h8h2c及203/449组合均保留，停止原因仍为target_met；169个策略格、4个合法动作、0项JS错误，无过期标记。真实模型根节点查询 `9ff957115e6a4a3eb51010f78aaa3ae0` completed、exit0、process_reaped=true；没有新CFR／BR，仅外部助手状态／会话使用模拟响应，助手配置与生产隔离。证据为 `outputs/performance-20261013-v2/completed-workbench-acceptance.json` 及 `completed-workbench.png`，截图已实际查看。根下注金额按当前整数bb引擎取整为3／5／8bb，即实际底池37.5／62.5／100%；输入33／66／100%未修改，不宣称支持小数bb下注。

只读线程采样发现大量自愿上下文切换，短样本中user/system CPU约各半；临时Vec分配与两个glibc arena的竞争是候选瓶颈，Rayon开销尚未排除。数据及限制在 `runtime-observations.json`。未改变运行中的目标、线程、分配器或算法。下一步先验证归一化分母的有界线程局部复用，再考虑跨递归存活的CFV／策略／reach缓冲池；必须保留浮点归并顺序、逻辑切片长度、独立缓冲所有权与内存预算，并做相同树／迭代数的数值及性能对照。尚未实现此项加速，不预先承诺倍数。

## 2026-10-13 完整三街三尺寸：受控分配器、位图与速度优化

保留上一轮完整配置的9h8h2c、pot8 bb、stack100 bb（SPR12.5）、203/449有效组合、全部范围权重。Flop为33/66/100%，Turn/River均33/50/75%，每街3x普通加注尺寸；没有限制加注次数、删除尺寸或截断公共牌。Station＋Overbluff＋River give-up及0.1% pot目标保持。完整验证配置在 `outputs/performance-20261013-v2/config.json`：墙钟时限明确0，最大迭代由1500提高至100000，以精度达到目标为提前停止条件；提高上限不表示已完成这些迭代。

### 本轮已实现

- `native/memory.rs`与监督进程采用受控glibc分配配置：最多两个arena，mmap/trim阈值128KiB，mmap数量上限65536，Rayon每线程显式2MiB栈。只有Linux GNU、所有环境值匹配且无非空GLIBC_TUNABLES/LD_PRELOAD时，才对512MiB以上引擎采用按组成计算的余量；否则保留旧公式。父进程环境、Windows 2GiB与WSL 512MiB预留、RLIMIT_AS均未放宽。估计仍不是实际峰值或硬保证。
- 无手动锁压缩模型的访问HashSet改为每原生节点一bit的预分配位图，保持同构节点只编译一次；当前树的计划访问存储从95,098,944降至1,387,960 bytes。引擎两大u16数组仍完全保留，未改为更低精度。
- 快照读写采用16KiB共享缓冲块，PLPOL002/003格式与原scalar编码相同。移除载入基线／检查点之前的一次无用MES遍历，固定模式报告仅计算Hero MES；独立sum-product重评仍保留。
- Hero BR仅并行独立子树，按原行动顺序归并，原浮点求和顺序和tie-break保持。原始对手策略不变。
- 报告增加原生VmPeak，监督采样RSS、虚拟地址峰值和swap，便于后续对照完整运行开销。均衡迭代算法、每10次精度测量、目标与数值容差未改。

### 启动前预检记录（后续完整实测见上）

同一完整三街树的新计划见 `outputs/performance-20261013-v2/storage-plan.json`：引擎数组与节点仍为14,856,895,090 bytes（13.837GiB），受控预估峰值15,303,798,176 bytes（**14.253GiB**），原计划为16.264GiB。差额主要来自替换整树15%余量的估算法，并非实际占用已经减少2GiB。新模型另计128MiB arena、40MiB线程／主栈、40KiB大分配padding、misc/locks的15%及256MiB临时余量；位图则是真实分配结构变化。

该次预检时：WSL安全预算14694MiB，足以通过新预检；Windows安全预算仅164MiB。用户当时回复“暂时不能释放，先保留当前改动”，因此当时未启动完整大树或后台重试。此为历史预检状态；用户后续释放资源并授权的完整实测已完成，详见上节，不能将两次状态混为一谈。

### 已执行验证

- `wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- env 'RUSTFLAGS=-C target-cpu=native' cargo test --release -- --test-threads=1`：**19 passed / 1微基准ignored，0.34秒**。含原有续算、特质测试，新内存模型／环境冲突测试、快照黄金字节／旧格式／损坏数据，以及Flop/Turn×f32/u16×Hero双方的BR串并行逐策略word和EV完全一致；独立重评误差≤0.0002，对手word保持不变。
- 同一构建的 `cargo test --release -p postflop-solver --lib -- --test-threads=1`：**41 passed / 4既有ignored，10.78秒**。单席MES与保留的旧双席路径逐位一致；包含锁、零概率、机会与finalize前后。
- `python -m pytest tests/test_solver_continuation.py tests/test_memory_budget.py -q`：**66 passed / 1原生opt-in skipped，0.21秒**；首次沙箱临时目录权限错误，正常权限重跑通过。Python语法检查、固定引擎完整补丁验证、最终release构建通过。用户内存未释放，未重跑完整Python原生集成套件。
- 快照64MiB累计内存读写微基准：旧写0.036664→新写0.006687秒，旧读0.020070→新读0.004090秒；仅内存缓冲，**不是磁盘吞吐或完整Solver加速比**。
- 原`main.rs`和监督代码副本保留于 `outputs/performance-20261013-v2/before/`，上轮vendor补丁保留为 `expanded-suits-v3-interpreter.patch`；没有Git重置、提交或推送。

## 2026-10-13 多尺寸策略深浅配色

同一节点红／紫色系内按真实尺寸从浅到深排序，扩大深浅差异；不按动作数组顺序取色，也不循环使用三色。相同尺寸同色，100%仍为红，超过100%用紫色。旧节点没有尺寸元数据时只按金额排序，不猜测超池。图例同时显示尺寸与动作频率，网格、按钮和具体组合频率条共用配色；组合排序／筛选后仍保留颜色。深浅表示尺寸，宽度表示概率，没有修改策略或EV。

`python -m pytest tests/test_board_strategy_browser.py -q`：**5 passed，8.18秒**，实际Edge无头浏览器核对乱序／倒序、亮度单调、同尺寸同色、4／5尺寸不循环、Raise边界、网格及组合条频率和原始数组不变。JS语法检查通过。截图 `outputs/workbench-sizing-shades-20261013.png` 已实际查看，并标明合成UI验收夹具；本轮仅显示层修改，没有重跑原生大树。8765的只读HTTP检查确认新静态代码已生效；桌面Pokerlab入口不变，已有窗口刷新即可，无须重新求解。

## 2026-10-13 取消自动超时、图形选牌、动作配色和迭代续算

用户明确要求慢任务继续运行。因此普通工作台、独立助手、CLI 和节点查询不再有自动墙钟超时，旧配置的600秒不再用于终止任务；目标精度、明确的最大迭代和主动取消仍生效。测试可显式设置诊断时限。内存预算、RLIMIT_AS、串行锁和取消后的进程回收保留。8765无运行任务时通过所属桌面启动器正常重启，新后台已生效，8770保持原状。

本次截图对应失败任务 `1a801ab2776848acbb1635ae52724ef0`：约595秒，390次迭代，实际 exploitability **0.018853098 bb**，目标 **0.008 bb（0.1% pot）**；峰值RSS **6000246784 bytes（5.59GiB）**，预算约13.30GiB，故为超时而非内存耗尽。输入为9h8h2c、pot8、stack100，OOP/IP有效组合203/449；Flop三个下注尺寸33%/66%/100%，Turn和River各两个尺寸，Raise为3x/3x/All-in。当前保存状态与截图一致，但失败任务旧版本没有保存完整请求，不能断言其revision71与后续revision74逐字段相同。

### 实际实现

- 4×13图形牌阵支持初始Flop/Turn/River、替换、清空、确认／取消、撤销；求解后的Turn/River仅允许选择原生引擎返回的合法公共牌。具体花色保留，输入与牌面同步。
- 策略频率：Fold蓝、Check/Call绿、Bet/Raise红、超池进攻紫，100%仍为红。`action_details`来自真实行动后的投入差；Raise比例为扣除跟注部分的额外加注／跟注后的底池，All-in同规则。旧节点缓存失效，旧研究缺元数据时重新查真实节点；不人为混合纯BR。
- 三个按钮解释为双方均衡参考、特质对手预览、固定对手下Hero完整最佳回应；结果继续区分GTO精度和固定对手response gap。
- `native/checkpoint.rs`以PLCFR001保存未收敛且正常达到迭代上限的原始累计策略、regret、压缩比例与全局迭代数。提高上限后自动续算，不从第0次重启；精度／迭代上限不进入CFR状态身份，范围、树、实际同构、算法等必须一致。PLPOL003仅保存最终策略，不能续算。主动取消／崩溃暂不产生中途状态；已达旧精度的基线可能需重算更严格目标。状态文件会额外占磁盘，原子临时文件只按当前原生PID清理。
- 模型遍历用轻量解释器位置恢复替代每个子节点都从根回放；保持reach、公共牌置换、下注与缓存，保留后代策略修改。CPU构建使用本机指令集、thin LTO与单codegen unit，不改算法／精度／树。纯均衡结果共用一份基线策略文件，避免额外写两份相同文件。
- 查询或低于2GiB预算的任务限制glibc为两个arena，减少线程稀疏虚拟地址预留；不放宽地址空间／内存预算。修复了小树预估能容纳但分配器虚拟预留导致分配失败的问题。

### 早期性能诊断记录（后续完整实测见顶部）

保留当前宽范围／SPR12.5，补为每街三个下注尺寸（33/66/100%、33/50/75%、33/50/75%），三街均3x普通加注的诊断在 `outputs/performance-20261013/storage-plan.json`。压缩＋安全同构的预估峰值 **16.264GiB**，高于WSL约15.47GiB上限；这是分配计划，未分配完整树，不是实测峰值。没有偷偷删尺寸／限制加注层数／截断后街。

尝试用优化构建对截图树做30次迭代诊断，在分配前因6.89GiB预估大于当时3.96GiB预算被拒绝，记录 `outputs/jobs/af1ddcc93f394d67acc9fdb186d79944/benchmark-summary.json`。之后Windows可用短暂恢复至9GiB，完整浏览器验收通过；随后对截图的原500次／全部特质配置重新基准时，安全预算又降至0MiB，未启动原生分配，记录 `outputs/jobs/2c3a38f7e98044098308f9ec17be91d5/benchmark-summary.json`。未关闭用户程序或削减2GiB系统预留。**该早期诊断阶段尚无宽树速度、最终精度或峰值实测**；后续完整实测已经完成，见本文顶部，不以小型测试代替。

三街三尺寸树的实际存储计划中，累计策略和regret各6.449GiB，IP／机会CFV合计0.272GiB，节点arena0.662GiB。因此只优化缓存不能解决冷训练峰值。下一步须重点验证行动数组存储方案；训练后释放regret并按需计算节点EV能降低模型／查询内存，但不能冒充冷训练已能容纳。

### 真实测试与边界

- `python -m pytest -q`：193 passed / 35 skipped，77.08秒；该次收集后另加一项原生资源回归，见下，不累加为一次总测试。
- `$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_solver_native.py tests/test_workbench_native.py tests/test_action_sizes_native.py tests/test_solver_continuation.py -q`：71 passed，50.04秒（34项原生、37项轻量单元）。独立River LP／收益矩阵、跨街45→50、冻结对手重评和非对称锁继续通过。资源低谷曾导致测试被保护拦下，资源回升后上述整组通过。
- 最后 `tests/test_action_sizes_native.py`：3 passed，3.04秒。核对5x Raise-to50的实际比例为100%、6x Raise-to60为125%；额外384MiB预算的小型完整Flop成功分配与执行BR并重评。后者仅2次基线迭代、仓库小范围，**仅用于分配器回归，不是用户宽树性能证明**。
- 本机优化构建 `cargo test --release`：7 passed，含f32/u16续算原始字节对照；实际工作台18→31次与从头31次的策略、EV及精度一致。随后补充真实Flop／Turn机会树测试，`cargo test --release checkpoint::tests`：5 passed（0.22秒）；分别在f32/u16下验证3→7次跨DCFR折扣重置的原始数组与exploitability完全一致，每实例小于10MiB。两次测试集合有重叠。上游 `cargo test --release -p postflop-solver --lib`：40 passed / 4既有ignored，包含新增位置恢复、花色与CFV缓存验证。完整vendor补丁校验通过，旧补丁保留。
- UI独立测试、范围／可用性／竞态回归通过：此前合集9 passed；随后新增续算显示的专用3项通过，集合有重叠。图形与配色夹具明确为界面验证，不冒充真实Solver策略。
- 真实Edge全流程曾因硬锁Turn查询时预算降至0MiB失败（任务`6898659ac7e84f76808c667d4ca1ebd2`）。资源回升后，`$env:POKERLAB_BROWSER='1'; python -m pytest tests/test_workbench_browser.py -q` 最终 **1 passed，38.39秒**：完整覆盖真实Flop基线／模型／BR、策略权重独立核对、原生尺寸、蓝Fold／绿Call／紫All-in(167/166)、图形Turn3c→River4c→返回Turn、Node Lock编辑重算及查询、保存／重新打开、敏感性与取消。截图已实际查看：`outputs/workbench-board-picker-20261013.png`、`outputs/workbench-facing-bet-20261013.png`、`outputs/workbench-turn-20261013.png`；测试服务和原生进程已回收。该浏览器小范围闭环不替代用户宽树性能验收。

## 2026-10-08 bb、自动资源预算、范围编辑与独立Solver助手

本轮代码实现与实际验收分开记录。以下2026-10-06及更早性能、EV、精度与测试结果保留原记录，没有因界面改成bb而改写历史实测。

### 已落地的实现

- 原8765工作台的新输入以bb展示底池、有效剩余筹码、下注金额、EV与精度；目前pot/stack仅支持整数bb，EV仍可为小数。新UI及独立助手默认配置增加可选metadata `amount_unit="bb"`，native执行前剥离、报告保留，兼容字段 `target_unit="chips"` 不变。旧报告缺metadata时显示“原筹码单位”，不偷偷贴bb；历史研究原数字保持，不自动换算，由用户核对原始计价后明确当前输入单位。单位切换同时更新金额／尺寸帮助和结果展示，旧报告及节点metadata路径已回归；Pokerstudio手牌的chips/USD适配独立。
- `resources.py`读取Windows可用内存与Ubuntu WSL `/proc/meminfo`，分别保留2GiB和512MiB，取双安全预算与24GiB上限的最小值。前端默认自动模式，对没有 `memory_auto` 的旧示例同样默认true，忽略其旧4096MiB手动上限。后端未带该字段仍按manual处理，尊重CLI及旧请求的显式上限。
- `/api/resources`提供显示快照；实际任务获得跨进程锁后复测资源，WSL监督再检查并记录实际限额。读取失败如实拒绝，不猜测资源、不削减系统预留、不改范围／SPR／尺寸，原生数组预检、建树后校验、地址空间与时间限制仍保留。
- 范围单击选中／取消，悬停滚轮5个百分点、Shift1个百分点，0–100%；169牌类默认所有花色均匀赋权，保留具体花色高级非对称编辑。输入中的公共牌冲突组合不删除。
- 翻前总X%滑杆按1326组合加权，边界牌类同权重混合，公开启发式排序规则及限制。70%为928.2个加权原始组合，不是当前街GTO、实测Equity或经过人群校准的范围；百分比包含公共牌冲突，不按当街牌面重排。调整滑杆会重建均匀花色模板，可撤销。
- 8765自身新增独立Solver助手适配、HTTP接口与工作区上下文；运行时不依赖8770或Pokerstudio实例，复用provider协议代码。工具只处理Solver配置、真实任务／结果、节点查询和取消；配置更新检查revision，不能写入伪造EV。状态与会话位于 `outputs/agent/`，认证默认 `%LOCALAPPDATA%\Pokerlab\agent`，API key／付费授权不持久化。独立入口的真实订阅与界面证据见下。
- 助手HTTP回复与工具事件统一按revision接收，迟到内容不回退快照；并发后台修改保留未提交输入，冲突时要求显式同步。结果身份比较包含范围／树、特质、锁、模式、单位及精度参数；只改变内存／时间／线程上限不改变数值身份。缺省空加注与空overrides规范化，防止同一报告被误标过期；局面／动作Node Lock签名保持原语义。修改输入后旧失败任务的内存估计提示清除，不留作新局面的估计。

### 本轮实际验收与回归

- 独立订阅真实验收：[`outputs/solver-agent-acceptance-20261008/acceptance.json`](../outputs/solver-agent-acceptance-20261008/acceptance.json) 记录隔离18765、`existing_cli` / `gpt-6.1-sol`、公开合成River范围。任务 `4276ba107d9b4119a171623f84f42b28` 为completed，实际执行read_solver_config、update_solver_config、start_solver、get_job、get_result，将pot25改为20 bb，其他范围／尺寸／目标保留；配置revision2和会话实际落盘。API未配置、未调用，外部MCP业务工具数为0。
- 真实求解任务 `be149736d1fa4c6a809db3f40fe32350` completed；双方根EV **13.3332891464 / 6.6667108536 bb**，均衡exploitability **0.00932455063 bb = 0.0466227531% pot**，目标0.05% pot已达到。墙钟3.072秒，`baseline_hit=true`；530次是缓存基线的历史迭代记录，本次没有新增530次CFR。原生exit0、process_reaped=true；仅证明当前小型两人River树，不能代替宽范围Flop验收。
- Firefox18765真实UI再调用get_result，显示报告和助手回答。发现缺省空raises／profile.overrides曾误标旧结果，修正后实际报告对当前配置 `sameSolverInputs=true`，并追加空字段浏览器回归。`outputs/solver-agent-real-ui-20261008.png` 是修复前带该标记的截图，不能当作修后无过期标记的最终截图。主8765安装后截图 [`outputs/solver-agent-installed-20261008.png`](../outputs/solver-agent-installed-20261008.png) 已实际查看，显示单位、助手已登录与双方169格；8765后台已更新，existing_cli配置已持久化，18765测试服务／Firefox上下文已关闭，8770未改动。
- 本机真实headless Edge范围回归验证单击、拖动、滚轮5pp／Shift1pp、边界、具体花色、撤销和70%总范围；独立1326计权测试核对0／0.1／3／12.5／70／99.9／100%及花色均匀性。可用性浏览器验证bb／旧筹码单位、旧示例默认自动预算、实时资源显示、手动上限、旧失败估计清除、助手配置同步与冲突保留，没有请求8770。竞态浏览器走真实隔离config REST，只模拟助手事件传输，验证迟到工具事件／POST回复不使版本短暂或最终回退，未提交编辑只在显式同步后提交；这些模拟事件不充当真实模型验收。
- 默认 `python -m pytest -q`：**147 passed / 32 skipped，55.07秒**，该次尚未收集新增竞态文件。随后竞态／可用性／桌面／内存回归合集：**51 passed，11.23秒**；最新metadata回归：**29 passed**。所有前端JS语法检查通过。这些测试集合有重叠，不相加为单次总测试数。
- `$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_solver_native.py tests/test_workbench_native.py pokerstudio/tests/test_solver_native.py -q`：**34 passed，45.90秒**，无失败／skip。验证小型真实数值、元数据、缓存、预算拒绝、取消及进程回收，不代表5.65GiB宽树跑通。
- `$env:POKERLAB_BROWSER='1'; python -m pytest tests/test_workbench_browser.py -q`：**1 passed，46.70秒**。真实Flop编辑、均衡、特质BR、Turn锁、敏感性、保存／重开和取消闭环通过；测试的范围summary使用直接子节点定位，兼容新增嵌套排序说明。
- 桌面真实安装已完成：OneDrive Desktop下两个.lnk，COM读回目标pythonw、参数、工作目录、图标正确，本轮只读复核两个文件仍存在。先前桌面／服务器／workbench API相关18项测试通过（0.93秒）；隔离18770冷启动、重复启动复用PID45584和停止自有后台成功，已有8770服务复用并保留。Windows独立窗口无地址栏视图仍未实际验收。

### 完整宽树内存限制与剩余验收

用户先前保存的宽范围配置副本保留全部原范围、尺寸和后街，pot改20、真实预检用50次迭代，启用压缩与自动安全同构；两次启动均在完整树分配前被拒绝。最新 [`outputs/jobs/3538b9c4cc0847f89856ea11d1de99cb/usability-acceptance.json`](../outputs/jobs/3538b9c4cc0847f89856ea11d1de99cb/usability-acceptance.json)：峰值估计 **5.65GiB**、引擎数组 **4.66GiB**、任务预算 **3.99GiB**，0.343秒退出、exit1、process_reaped=true。之前相同保存配置计划的尝试为 `91dda0110f8346d0a51716ef799a17d3`；不是求解完成，也没有取得此树的新EV或精度。

[`outputs/memory-wide-pot20-storage-20261008.json`](../outputs/memory-wide-pot20-storage-20261008.json) 与 [`outputs/memory-budget-diagnosis-20261008.json`](../outputs/memory-budget-diagnosis-20261008.json) 保留实际数组计数、Windows／WSL测量和差异说明；storage诊断未分配完整树，峰值余量是估计。小型仓库范围的pot20存储估计约0.321GiB，不能用于证明用户宽树能装入内存。原截图5.37GiB和保存配置5.65GiB并非同一存储计划；当前未保存局面的完整配置尚未取得，不能称为精确复现。

用户已明确“暂时不能关闭，先保留完整树”。未停止其他程序、砍分支／范围／尺寸、削减Windows 2GiB预留或绕过原生预检。完整宽树在当前可用内存下仍未启动；没有重跑或改写下文历史SPR20基准。首次SIWC本人授权、收费API以及Windows无地址栏窗口视图仍未取得本轮真实证据；独立助手的真实取消／错误对话路径未以本次成功River任务代替验收。

## 2026-10-06 原树内存与 CPU 优化

- `br-policy-v4-memory`：压缩策略读写贯通 BR、快照和查询；自动同构仅用于无手动锁模型，具体范围对称性仍由上游判断。手动锁回到完整公共牌分支，含硬锁快照查询以 f32 保留保存概率。
- 分配前统计原生 arena/策略/IP/机会数组，建树后强制与实际 engine memory_usage 一致；弃用旧粗估作为硬门槛。计入锁／编译访问集合、15% 分配器余量和 256MiB 临时余量。系统保留预算与 RLIMIT_AS 未取消。
- 无手动锁压缩模型原位冻结，不复制完整 f32 对手锁；编译后不再 CFR，BR 仅写 Hero，对手摘要前后校验。缓存精确牌类，不缓存历史相关决策；减少逐组合字符串和短数组分配。没有改变下注尺寸、SPR 或合法加注。
- Rayon CPU 并行（界面默认 8，1–16 可选）；基线缓存隔离压缩、线程数和实际同构/展开布局。任务时限可设 1–3600 秒，默认 600；没有 CFR 续算。
- 工作台显示存储设置和预算，预算按钮请求至多 24GiB，仍按 Windows/WSL 可用资源下调；导出配置移至侧栏顶部。失败提示提取中文错误，不再显示整串阶段 JSON。

原配置完整实测：`outputs/jobs/0fbeefb0cb144c3a8fd7d997d0089823/benchmark-summary.json`。牌面 9h8h2c，pot=10，stack=200，SPR20，OOP/IP 有效组合 240/290；三街 Bet 分别为 33%/50%/75%、66%/33%、75%/33%，Raise 为 3x、3x、All-in。全部原始范围、特质、动作和精度目标保留；没有截断后街。公开行动树 5615 节点，实际同构树 7075006 节点（4424721 终局、11585 机会节点），策略元素 1753041780。

16 线程，500 次迭代，总墙钟 **693.03 秒**。目标 exploitability=0.01 筹码（0.1% pot），实际 **0.04542135447 筹码（0.4542135% pot）**，停止原因 `iteration_limit`，**未达目标**。引擎数组 7663234304 bytes，含余量预估峰值 9153983025 bytes（8.525GiB），实际峰值 RSS **7682031616 bytes（7.15GiB）**。旧 77796977664 bytes 是保守预检，不是优化前实测峰值，不能据此宣称实测内存降低某百分比。WSL 总内存约 15.47GiB，Windows/WSL 双重预算仍生效。

| 阶段 | 冷启动秒数 |
|---|---:|
| 建树准备与构造 | 0.485 |
| A 均衡基线 | 482.728 |
| B 完整对手编译 | 87.262 |
| C Hero BR | 8.570 |
| D 重评与验证 | 39.766 |
| D 报告 | 0.642 |
| D 三份策略保存（旧 f32 文件格式） | 72.609 |

同一冻结对手下原 Hero EV **5.049724579**，BR EV **10.868614197**，提升 **5.818889618** 筹码；对手摘要保持不变。独立 sum-product 重评报告误差为 0，容差 **0.0002 筹码**；这不表示均衡精度达标。实际宽范围是集成与性能证据；独立小型 River LP、收益矩阵和跨街 45→50 解析案例继续作为数值正确性依据。

最终策略写入改为 `PLPOL003`：压缩节点保留原始 u16，硬锁保留 f32；继续兼容旧 `PLPOL002`。小型缓存重开测试验证行动概率及 EV 完全一致。快照仍不是 CFR 续算状态。

原配置缓存复用实测：`outputs/jobs/ff9eae15352d42238fdfbede744574da/benchmark-summary.json`，同一命令再次运行，无须重新 CFR。总墙钟 **230.29 秒（3 分 50 秒）**，基线加载及重测 41.415 秒、模型编译 100.447 秒、BR 8.515 秒、重评 51.422 秒、报告 1.467 秒、两份新格式策略保存 24.249 秒；峰值 7680471040 bytes。模型及 BR 文件各 **3540386750 bytes（3.30GiB）**，原 f32 格式各约 6.55GiB。旧基线仍保持原文件。

该次兼容加载旧 PLPOL002 基线时会归一化并重新量化：基线 exploitability 为 0.04542052746 筹码，BR 为 10.868612289，与冷启动的 BR 相差约 0.000001907 筹码，远小于 0.0002 重评容差。不是特质改变实验，不能把此微小差异解释为策略收益。新 PLPOL003 原始 u16 缓存避免该重复量化。两次均未达到基线 0.1% 目标。

复现命令（PowerShell）：`python scripts/benchmark_config.py C:/Users/n1rva/Downloads/pokerlab-study-config.json --timeout 1800 --threads 16`。脚本只复制配置并设置存储／资源选项；不修改下载目录中的原文件。

已通过工作台同一保存流程建立研究 `5b908d4ecc6e4ceb97169a79a2f1ac2c`，名称“SPR20 多尺寸内存优化验证 - 基线未达0.1%”。重新读取该研究的完整 BR 快照、查询根节点成功：240/290 组合，Check/Bet(3)/Bet(5)/Bet(8)，960 个策略值，首次查询 **25.44 秒**（`outputs/original-tree-root-query.json`）。这是大树后端读取验证；完整浏览器流程由上述小型真实 Flop 用例覆盖。新节点查询仍须加载完整策略，首次查询延迟尚待优化；已查询节点有缓存。

最终回归命令与结果：
- `python -m pytest -q`：112 passed / 32 skipped，42.81 秒（原生及浏览器测试单独启用）。
- `$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_solver_native.py tests/test_workbench_native.py -q`：31 passed，28.78 秒。
- `$env:POKERLAB_BROWSER='1'; python -m pytest tests/test_workbench_browser.py -q`：Edge 无头自动化 1 passed，36.34 秒，覆盖真实 Flop、Turn 手动锁、保存／重开和敏感性；不是人工验收。
- WSL `cargo test --release -p postflop-solver --lib`：37 passed / 4 ignored；适配器 `cargo test --release`：3 passed。
- `python scripts/verify_engine.py`：固定 commit 与完整 vendor 补丁一致；JS 语法检查通过。

早期单线程原配置在 600 秒超时，最后精度采样为迭代 40、1.269593 筹码，峰值 6.96GiB，进程已回收。最终完整结果如上；不能把早期超时描述为已收敛。下一关键瓶颈是相同完整树下达到 0.1% 的收敛时间，以及 CFR 状态续算；大型手动锁仍会展开所有公共牌，不能承诺与无锁同构树相同内存。

## 2026-10-06 初始内存预检诊断（历史记录，后续优化见上）

新增原生 `--estimate` / 内部 `runtime.estimate_only` 入口及 `scripts/diagnose_tree.py`，只建公开行动树，不构造 PostFlopGame，不求解。逐街分解现有保守预检公式，报告有效组合数、公开节点、公共牌展开节点上界、普通 Raise 最大层数（不含 All-in）；原预算守卫及计算语义不变。诊断脚本对输入作副本对照，不落盘原始范围、不修改用户配置；旧二进制通过未知 runtime 字段安全拒绝，不会因忽略命令行选项而误启动完整求解。

已复现用户报告的 77796977664 bytes 预检失败；原树未尝试完整分配。当前诊断仍是旧公式的拆解，不是更精确的峰值估算，也未实现压缩存储或自动同构。下一步优先校准分配前估算和内存组成，再验证对称条件下的同构及压缩；禁止直接放宽守卫来宣称性能改善。

验证：release 构建成功；最终原生集成 13 passed（7.37 秒，含三项新增纯 Check 树诊断，独立核对公开节点及公共牌分支计数；保留原有独立 River LP 和跨街 EV 参考）。未运行完整用户大树，未测其均衡精度或实际求解峰值。

IP 范围可发现性修正：取消默认隐藏 IP 的互斥页签，两份 13×13 范围表格均展开，提供 OOP/IP 定位按钮。已在实际运行的 8765 服务用无头 Edge、1500/900 像素宽度验证双方各 169 格、IP 定位与点选、IP 配置同步、OOP 不变及无脚本异常；截图 `outputs/ip-range-live-1500.png`、`outputs/ip-range-live-900.png`。本次只改界面显示，未重跑原生求解数值测试。

最新交付见末尾“完整分支 Node Lock 与日常研究流程”。前面保留阶段 1 和 9 月 23 日的实际验证记录；当前能力／限制以最新交付与 README 为准。

阶段 1 已交付可运行研究工作台，沿用原项目与阶段 0 引擎。原文档保存在 archive；没有清空旧代码、修改 vendor、执行 Git 重置或推送。启动与操作见 [README](../README.md)。以下结果均限定于明确配置的离散树。

## 实际实现

- `native/response.rs` 导出全树、逐信息集与具体手牌的确定性最佳回应。先汇总隐藏对手牌的条件收益，再选动作；先优化所有后续决策再回传，不预知未来公共牌，也不对每个隐藏对手组合单独取最大值。
- 冻结对手后，用独立 sum-product 策略评估重新评估导出策略，并与 upstream MES 对比。容差为 pot × 2e-5；报告实际误差，不把浮点零误差说成无限精度证明。全树策略可以保存并按路径查询。
- 接通 Check/Bet/Fold/Call/Raise/All-in，多下注／加注尺寸；River 数值测试覆盖最小 2x、Raise-to、有效筹码、未跟注退款、终局收益。完整 Flop 基准包含三街 All-in Raise。
- 六种可叠加特质、街道筛选、真实行动历史条件、完整对手编译与冻结。Station 与 Overbluff 作用于不同情境，多尺寸按类别总概率调整后分配，避免重复加概率。支持零频合法分支；无规则处保留基线。展示覆盖计数及有限解释样本。
- 中文本地工作台：输入／范围导入、13×13 组合选择、特质强度、模型预览、BR、逐组合行动／Equity／行动 EV／同模型收益变化、节点与公共牌导航、任务状态／取消／错误、保存与重开、过期标记。River 手动完整动作分布覆盖优先于模板，支持恢复模板。
- 基线最终策略缓存，修改特质无需重新 CFR；保存 baseline/model/response 三份完整最终策略。非 CFR 续算；输入指纹不符拒绝加载。
- 本机监听、会话请求令牌、跨进程串行任务、Windows/WSL 双预算、地址空间限制、超时与进程组回收。失败／取消只清理未完成临时文件。

## 引擎与独立正确性证据

阶段 1 初始引擎：b-inary/postflop-solver，commit `9d1509fe5077d019825f833eed04b16d342dfda1`，AGPL-3.0-or-later；当时 vendor 未修改。初始适配器 `br-policy-v2`，模板编译器 `traits-logit-v2`。本轮引擎补丁及新适配器见末尾；Rust 1.75，CPU 单线程，无 Pio、GPU 或模型训练。

独立 Python River 纯策略枚举及 LP 的基线参考根 EV 为 13.333333…；测试与真实原生结果比较。新增测试从已导出的各节点策略恢复完整混合计划，用独立 Python 收益矩阵评估；与报告 BR 的误差要求小于 1e-4 筹码。

保留跨街解析案例：AsAh 对 KcKd，AcAd2h，pot=20，stack=30，无 Raise，每街可 Bet 10。对手面对 Bet 跟注 1/2；Hero Check 后 Flop/Turn 必 Bet，River Bet 概率 q。完整枚举合法未来公共牌。独立解析递推参考：

| 起始街道 | q=0 BR | q=1 BR |
|---|---:|---:|
| Flop | 45 | 50 |
| Turn（3s） | 35 | 40 |
| River（4c） | 25 | 30 |

本轮复现通过。此案例是合成策略正确性依据，单组合约 0.65 秒的旧成绩不作为实际范围性能证据。新增 Raise 测试：pot20、双方有效30，Bet-to10→Raise-to20→All-in30；对手 Fold 时根净 EV [40,-20]，Call 时 [50,-30]，独立筹码账目核对退款。

生产 sum-product 评估与 BR 是分开的遍历，但共享上游终局求值器；它不是完全独立引擎。Python 小型参考才是独立数值依据。HTTP／保存格式／浏览器测试属于集成验证，不能代替数学证明。实际范围 Flop 也是集成及性能证据。

## 实际范围 Flop

牌面 **9h8h2c**，pot **100**，双方有效剩余 **200**，Hero=OOP。牌张排除后 OOP **61**、IP **71** 个具体组合，均为单位权重：

- OOP：`AA-JJ,AKs,AQs,KQs,QJs,JTs,T9s,98s,87s,76s,65s`
- IP：`TT-55,AQs,AJs,KQs,QJs,JTs,T9s,98s,87s,76s,65s,54s`

这是含多类成牌、听牌、超牌的明确研究范围，尚非所有位置的宽范围默认策略库。配置 [flop_research_raises.json](../examples/flop_research_raises.json)：每街分别 Bet 33%／66%／75%，每街 Raise 仅 All-in。根 OOP 行动，双方尺寸相同，无抽水；保留全部合法 Turn/River 与后续行动，不截断或恢复后街 GTO。

树规模：147 个抽象公开行动树节点；展开后 154610 个规范节点（含终局 93321、机会 617），策略概率 8588976 个浮点数。机会节点使用上游花色同构压缩，统计不是所有牌面排列的未压缩数量。

目标 exploitability 为 pot 的 0.1%；实测 **0.08294057846 筹码 = 0.08294057846% pot**，90 次 CFR，达到目标。冷基线记录见 `outputs/flop-study-1790117869330241900/summary.json`；最终编译版本复用基线后重复核验同一精度，见 [最终完整记录](../outputs/flop-study-1790123067169041400/summary.json)。

| 阶段 | 实测秒数 |
|---|---:|
| A 冷基线 CFR（90 次） | 6.17747 |
| 冷基线原生总计（含构建、报告、保存等） | 7.63790 |
| 后续任务复用基线并重测精度 | 0.46920 |
| B 完整对手模型编译 | 1.30029 |
| C 导出完整 BR | 0.03927 |
| D 策略评估 | 0.38699 |
| D 报告生成 | 0.10948 |
| D 策略保存 | 0.81840 |
| 修改模型后的原生总计（含建树等） | 3.20437 |

冷基线峰值 RSS 83.72MiB；最终叠加模型峰值 **103.78MiB**（108818432 bytes）。这些是单次原生计时和进程 RSS，不含整个 WSL VM、Python／浏览器内存或全部服务往返。主机 285K、31.71GiB RAM；WSL MemTotal 16609603584 bytes（约 15.47GiB），swap 4GiB。Windows 可用内存会波动，运行时重新检查。

同一固定对手下，原 Hero 基线 EV **64.47947693**，导出 BR 重新评估 **79.77104187**，收益提升 **15.29156494** 筹码。BR 导出值、重新评估值与 MES 在当前 f32 报告精度下误差为 0，允许容差 0.002 筹码；这是固定模型回应质量，不是均衡 exploitability。

只增加 River give-up（Station=2、Overbluff=2 保持三街不变，give-up=3 且只作用 River）：根 BR 从 **80.25474548 → 79.77104187**，根逐行动 EV 最大变化 **1.01643372**；7c6c 的根最佳动作从 Check 转为 Bet。收益下降是对手少送钱的自然结果，没有强造增益或反转。

另完成无 Raise 树的分项对照，`outputs/flop-study-1790115625884518500/summary.json`：Station 单独 BR=75.6005478，Overbluff 单独=78.5416336，二者叠加=84.8273010，再增加仅 River give-up=83.0957184。所有模型都有各自同模型旧 Hero 收益；不同对手下的 BR 数字不能当成同模型策略提升。最初一轮因 Windows 保留 4GiB 导致预算拒绝，错误记录保留；调整为保留 2GiB 后完成上述运行，未静默缩树。

## 真实测试记录

在根目录 PowerShell：

- `python -m pytest -q`：**112 passed, 15 skipped，60.39 秒**。跳过的是 14 项需原生引擎的集成及 1 项浏览器集成，均在下面显式运行。
- `$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_solver_native.py tests/test_workbench_native.py -q`：**14 passed，16.45 秒**。
- 最后补充未完成临时快照清理后，`$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_workbench_native.py -q` 再次验证：**4 passed，8.53 秒**，包含超时和进程回收。
- `wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- cargo test --release`：**3 passed**（适配器规则测试，不宣称运行了上游全部测试）。
- `$env:POKERLAB_BROWSER='1'; python -m pytest tests/test_workbench_browser.py -q`：**1 passed，21.63 秒**；真实 Edge 无头流程：完整范围 Flop 基线→组合特质→预览→BR→169 网格／AA 具体组合→后续节点→保存→输入过期→重新打开→取消。无页面脚本异常，截图 `outputs/workbench-flop.png`。

测试还覆盖权重／牌张冲突、零到达不复活、非法机会牌、花色重命名、IP Hero、平局、冻结摘要、手动覆盖优先与冲突拒绝、模型顺序不变性、多尺寸概率、内存拒绝、精度停止、CLI 与缓存、同源接口限制、超时回收。

## 尚未完成与下一项关键工作

**现在可以从 Flop 开始研究 Station + Overbluff + River give-up**，在上述完整离散树和明确研究假设内成立。没有宣称整个原始产品需求全部完成。

当前限制：根必须 OOP；有效等筹码；无未来抽水；每街每位置每类最多 3 个尺寸；SPR≤20。特质仍是粗成牌／公共牌比较及历史条件，缺少细化 Equity、阻断牌、听牌强度与尺寸响应曲线。任意绝对 Raise-to 输入、自由分支编辑、转河牌汇总报告、Constrained 模式、CFR 续算、MCP 与三人尚未实现。Flop/Turn 锁、撤销／重做、库与敏感性已在最新交付中补齐。

### 界面改进（2026-09-23，按用户实际试用反馈实施）

此前绿色网格仅表示有组合、范围和尺寸只能文本输入、特质参数缺少直观解释。本轮补齐下面的操作闭环；使用现有真实引擎，没有改动求解核心或模板数学规则。

- [x] 策略网格：按真实动作概率显示分色比例、图例、各尺寸和全范围加权频率；具体花色可展开。聚合使用节点条件权重，零到达单独标识。基线混合策略与可能为纯策略的固定对手 BR 如实显示，不为视觉效果制造混合。
- [x] OOP/IP 独立的可视化范围编辑器：13×13 点选／拖选、权重、具体花色、公共牌冲突提示、有效组合计数；与文本导入／导出双向同步。公共牌冲突不删除原输入；重叠文本条目遵循引擎的前项优先规则。
- [x] 三街尺寸选择器：常用底池比例、多选、自定义、加注倍数和 All-in；清楚展示当前树允许的尺寸、限制及更改后结果过期。
- [x] 特质可解释控件：中文行为说明、关闭／轻度／中度／重度、适用街道、保留高级数值；对手节点展示实际频率前后变化。两列按当前模型相同条件权重汇总，可筛选手牌格；含手动覆盖。预设是研究强度，不冒充经数据校准的玩家类型。
- [x] 浏览器验收上述编辑→真实 Flop 求解→模型预览→BR→节点查看→保存重开闭环；额外用 Python 核对网格聚合与引擎原始频率一致。

本轮浏览器使用 61/71 组合案例，将 OOP 的 AA 权重通过网格设为 50%，Flop 尺寸增加为 33%、50%，Turn/River 仍为 66%/75%，三街保留 All-in Raise。实际生成 235 个公开行动树节点；首次基线达到 0.070975 筹码 exploitability（目标 0.1 筹码，90 次迭代），CFR 9.268 秒，峰值 126.7MiB。这是编辑后真实计算的单次观测，不替代完整性能矩阵。

代码：新增 web/range.js（范围解析与无损权重序列化）、web/controls.js（编辑器、尺寸／强度控件与策略分色），更新原网页及本机静态文件路由。界面验证截图在 outputs/workbench-strategy.png、outputs/workbench-range-editor.png、outputs/workbench-flop.png。当前只验收桌面 Edge，触屏拖选未验收；仍无编辑撤销／重做。

本轮最终验证：PowerShell 中 `$env:POKERLAB_BROWSER='1'; python -m pytest tests/test_workbench_browser.py -q`：**1 passed，32.83 秒**。除上述流程外，还检查 Fold／Call／All-in 三种实际动作分色、范围区间与重叠权重、非法范围拒绝、文本导出、尺寸上限、取消及页面无脚本异常。`python -m pytest tests/test_workbench_api.py -q`：**1 passed，0.63 秒**。本轮未修改原生数学核心，未重复运行上一阶段全部原生和旧数学测试。

后续仍需扩展更宽范围和不同 SPR 的性能矩阵，优化首次节点加载、模型编译与保存，细化特质语义；不能据单个案例承诺任意树几分钟。9 月 23 日列出的 Flop/Turn 非对称锁及重复节点查询缓存已在下面交付。

三人路线仍为小型 River 固定两名对手并独立枚举验证，再扩到 Turn/Flop、边池和联合牌张排斥；本轮未实现。许可清单与商业分发边界见架构，当前为本地研究原型。

## 完整分支 Node Lock 与日常研究流程（2026-09-24）

本轮实际完成：

- OOP/IP 明确页签，两个范围编辑器同等可见，不再把 IP 藏在长侧栏下面。
- Flop/Turn/River 对手 Node Lock：单组合、当前手牌格、全节点合法组合；完整动作分布、100% 动作快捷键、显式归一化、锁列表、定位、删除、恢复模板。手动锁优先于模板，保存研究会保留。
- Node Lock 的局面／牌面／动作签名校验，范围或尺寸变化不会让数字路径悄悄锁到另一节点；冲突会拒绝，并允许撤销恢复或主动清除锁。
- 最近 100 步局面、范围、特质、锁的撤销／重做；命名范围库、玩家特质库、配置 JSON 导入导出和模型复制。
- OOP/IP 独立下注／加注尺寸及 Turn/River Donk；默认仍可双方共用，全部配置纳入缓存和锁签名。
- 真实 Equity 条件分布图、组合 EV／Equity／收益变化排序与筛选、节点路径返回。
- 轻／中心／重三模型敏感性：软特质强度 0.5/1/1.5 倍（上限 6），手动锁不变，串行任务、复用基线、父任务取消传递；每个模型各自比较原 Hero 与 BR，输出根 Hero 行动反转，不声称全树稳定性。
- 最终策略节点报告缓存；相同结果反复访问无需再次启动引擎。缓存绑定配置、适配器、策略文件及路径，最多 256 项或 128MiB，保存的策略与研究不受缓存淘汰影响。

引擎基础 commit 不变，新增已记录的 `third_party/patches/expanded-suits.patch`。适配器为 `br-policy-v3-expanded`；工作台默认 `expand_suits=true`，先保留所有实际公共牌分支，再编译锁。没有用极小权重扰动范围来破坏对称，也没有修改终局牌力求值器。旧默认构造器不变，旧压缩策略仍按旧配置读取；不兼容的基线会新建。`scripts/verify_engine.py` 和构建脚本校验完整补丁，AGPL 原许可保留。

**独立数值验收**：保留四条胜两张 K 的合成案例。Turn 根的标准 EV 为 35；只在指定 River 4c 的 IP 节点锁定 Bet，EV 应为 `35 + 5/44`，4d 分支仍保留原 Check。Flop 只锁定有序的 Turn 3h、River 4c，根 EV 应为 `45 + 5/(45×44)`。测试分别以 0.0002、0.0003 筹码容差通过，锁不串到其他花色；导出策略重评也通过。另核对展开前后 Neutral 均衡、范围／牌张冲突、跨场景锁拒绝、IP 独立尺寸和 Donk 行动树。

### 新的实际范围 Flop 性能

命令：`python scripts/benchmark_flop.py --expanded --raise-multiplier 2x --combined-only`。
完整记录：[summary.json](../outputs/flop-study-1790252047462392500/summary.json)。

仍为 9h8h2c、pot100、stack200、前述 61/71 组合单位权重研究范围；三街 Bet33%/66%/75%，三街 **2x 加注**（合法筹码上限产生 All-in），无抽水。完全展开实际公共牌分支：公开行动树 251 节点，总节点 415988，其中终局 252750、机会 1528，策略浮点数 22613844。此项不含手动锁，用组合特质验证更复杂完整树。

| 阶段 | 实测秒数 |
|---|---:|
| 冷基线 CFR | 17.8271 |
| 冷基线原生总计 | 21.5759 |
| 复用基线并核对精度 | 1.2192 |
| 完整对手编译 | 3.1433 |
| BR 导出 | 0.0973 |
| 策略评估 | 0.7267 |
| 报告 | 0.2261 |
| 保存 | 2.2224 |
| 修改模型后原生总计 | 7.8047 |

目标 0.1% pot，实测 **0.078125% pot**，110 次 CFR，停止原因 target_met。冷基线峰值 223444992 bytes（213.09MiB），组合模型峰值 **278687744 bytes（265.78MiB）**。报告的预检 719978128 bytes，估计峰值 1162383424 bytes；不能因为实测 RSS 266MiB 就保证 266MiB 预算能启动。进程由共享锁串行执行，表中为原生阶段计时，不含等待其他任务的时间。

同一个固定对手下原 Hero EV=64.66748810，BR=80.16040039，提升15.49291229；重评误差在 f32 报告中为0，容差0.002。只增加 River give-up 时 BR 从80.25497437降到80.16040039，如实保留结果。没有由该局面推断任意更宽范围／更高 SPR 都已达标。

节点缓存小型 River 观测：[node-query-benchmark.json](../outputs/node-query-benchmark.json)，首次0.22165秒、重复0.00541秒，策略数组一致。这是后端查询，不是浏览器端到端延迟，首次大树加载仍有成本。

### 本轮验证与余项

- `python -m pytest -q`：112 passed、20 skipped，47.19秒。19项原生和1项浏览器单独运行。
- `$env:POKERLAB_NATIVE='1'; python -m pytest tests/test_solver_native.py tests/test_workbench_native.py -q`：19 passed，17.95秒。最后工作台9项再次通过（39.50秒，含等待串行基准），写出节点查询计时。
- `wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- cargo test --release`：适配器3 passed。
- `wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- cargo test --release -p postflop-solver --lib`：上游37 passed、4 ignored，5.62秒。忽略项为上游预设。最初带 --no-default-features 的包选择命令被 Cargo 拒绝；不带 --lib 时 file_io 示例需要未启用的序列化特性，故最后针对实际使用的库测试，不声称验证了这些示例。
- `python -m pytest tests/test_workbench_api.py -q`：1 passed，0.68秒，含命名库保存读取、无效档案及请求授权检查。
- `$env:POKERLAB_BROWSER='1'; python -m pytest tests/test_workbench_browser.py -q`：最终 **1 passed，84.09秒**，含独立 IP 尺寸／Donk 输入语义、真实编辑范围、多尺寸 Flop、Turn Node Lock、撤销／重做、定位、重新求解、命名库、保存重开、三个真实敏感性模型和取消。此前一轮106.81秒。另一次因 Windows 可用预算不足被拒绝，未缩树或关闭用户程序；资源恢复后重跑通过。最后仅修正尺寸说明文字，未修改求解行为。

这已是完整的两人固定对手研究主流程，**不是原始文档所有高级要求均完成**。仍缺任意 Raise-to／自由分支编辑、任意根行动者、精细听牌与阻断牌规则、转河牌汇总报告、Constrained 模式、CFR 续算和 MCP；三人及未来抽水仍后续。下一个最影响日常使用的工作是更宽位置范围／不同 SPR 性能矩阵、首次节点加载与模型编译优化，以及更精细、可解释的牌力特征。用户可直接按 README 的 Node Lock 流程使用，不需要重新创建项目。

## 离桌复盘助手第 1 阶段（2026-10-29）

主任务改为工作台内的离桌复盘助手（DECISIONS D26–D29），完整状态见 PROJECT_STATE A 节。
- **新增**：
  - `pokerlab.coach`：手牌统一格式与重放校验、PokerStars/GG 解析、18 项对手统计（Beta 后验）、追加式存储。
  - Claude 订阅接入：`solver/claude_provider.py`，走用户自己的 Claude Code 登录。
  - 助手新增 7 个复盘工具，界面新增"手牌与对手"面板。原有 Solver 工具、ChatGPT/Codex 订阅和 OpenAI API 接入不变。
- **测试**：
  - `python -m pytest tests/test_coach_hands.py tests/test_coach_store.py tests/test_claude_provider.py tests/test_solver_agent.py tests/test_instructions_consistency.py -q`：33 passed（验收修复后）。
  - 全量 `python -m pytest -q`：378 passed，39 skipped。
- **Claude 订阅真实验收**：共跑 4 次，详见 PROJECT_STATE A2。
  - 第 1 次（074027）：本机独立 Claude Code 登录已过期。
  - 用户重新登录后，又修了三处：盲注与按钮不一致没有警告、回答里回显工具调用格式、回答前出现草稿。
  - 最终一次 `outputs/coach-acceptance/20261029-075129/acceptance.json`（提交 `66ef4d4`）：8 项检查全部通过，两轮分别用时 16.7 / 18.0 秒。
- **现场笔记**（DECISIONS D30）：
  - 新增 $5/$5/$10 三盲、BP、按位置记录、未知位置暂定、未知牌、别名与观察备注，以及胜率计算。
  - 用户的现场笔记 8 手记录了 7 手（待确认），详见 PROJECT_STATE A2b。
- **第 2 阶段试点**：
  - HHP 字幕知识库：29 个视频、22.9 万词、970 段，助手新增 `search_hhp` 和 `read_hhp`。
  - 4 个讲解视频已抽帧，共 890 帧。
  - 4 个视频都读完了关键帧（82 帧），整理出 43 条完整手牌记录，重放校验 0 个错误。这些是教学用的假设手牌，只当知识条目。
  - 全频道字幕补全：202 个视频中 200 个有字幕，共 156.4 万词。
  - 缩略图测出 200 个视频共 117.4 小时，其中屏幕上有牌面 73.5 小时。全部读画面约合 $824 的 API 等价额度，逐个视频的列表见 PROJECT_STATE A2c。
  - 讲解/分析类前 20 个读完（2026-10-30）：新增 267 条完整、94 条部分记录，重放 0 个错误，其中 117 条是真实牌局。现在共 310 条完整记录。按 API 价格约 $165，实际占本周额度约 7 个百分点。
  - 按牌局检索（2026-10-30，提交 `5fed542`）：新工具 `find_hhp_hands` 按牌型、位置、筹码深度、底池类型、牌面和行动线查视频手牌，也能用用户手牌找相近的。JJ、squeeze、翻牌过牌加注、河牌跟注 4 项和原始动作数逐手一致，字幕检索前 20 条最多只命中 6 手。
  - 全片重读（2026-10-30）：第一遍只打开了约 10.4% 的牌桌画面。按牌桌变化抽帧后，已读的 24 个视频全部重读，共 1,926 张图。完整记录 310 → 408，部分记录 97 → 43，重放 0 个错误。按 API 价格约 $324，实际占本周额度约 16 个百分点（含试点）。
  - 视频手牌已接入助手（提交 `819d880`）：`read_hhp` 返回同一时间段的手牌记录，`search_hhp` 列出每段有哪些手牌。真实问答验证见 PROJECT_STATE A2c。
  - 详见 PROJECT_STATE A2c。

## Solver 成熟化与 GTO Wizard 对比（2026-11-01）

完整状态见 PROJECT_STATE A2d，决策见 DECISIONS D32–D34。
- **新增**：Filters、Equity chart、EV / Equity / EQR 手牌格、整体动作频率卡片、下注树模板、抽水输入、小数 bb、常驻节点查询、`%` 加注、Preflop 范围库。
- **速度**：每街 1 个尺寸、最多加注 2 次，0.5% 底池 19–45 秒，1.6–2.6 GB；每街 2 个尺寸约 4 分钟，6.9 GB。
- **对比**：4 个局面，Equity 和手牌分类完全相同；河牌 EV 差 ≤0.002bb；翻牌和转牌 EV 差 0.015–0.23bb；翻牌混合频率差到 24 个百分点，锁定 GTO Wizard 频率后该方 EV 只差 0.003–0.026bb。
- **Preflop**：8max straddle、cEV、7bb 开池，100bb 和 200bb 各 56 条线，共 112 条。
- **测试**：
  - `python -m pytest -q`：497 passed，40 skipped，3 分 53 秒。
  - 原生（`POKERLAB_NATIVE=1`，命令见 README）：76 passed，30 秒。
  - 完整浏览器流程（`POKERLAB_BROWSER=1`）：1 passed，25 秒。
  - `cargo test --release`：22 passed，1 ignored。

## Preflop 行动线（2026-11-01）

完整状态见 PROJECT_STATE A2e，决策见 DECISIONS D35。
- **新增**：页面顶部的 Preflop 行动线，从 UTG 点到翻牌，自动带入范围、底池和筹码，解算前可改。
- **深筹码**：加了每街加注次数时，SPR 上限 40。
- **没做到**：400bb 当时还没有补齐。
- **测试**：
  - `python -m pytest -q`：504 passed，40 skipped，3 分 51 秒。
  - 原生（`POKERLAB_NATIVE=1`，命令见 README）：76 passed，30 秒。
  - 完整浏览器流程（`POKERLAB_BROWSER=1`）：1 passed，26 秒。
  - `cargo test --release`：22 passed，1 ignored。

## 每街 3 个尺寸与内存预算（2026-11-01）

完整状态见 PROJECT_STATE A2f，决策见 DECISIONS D36。
- **修复**：解算刚结束时，WSL 已占但没在用的内存没算进预算，造成误拒绝。
- **新增**：完整和完整省内存两个模板。
- **实测**：3 个尺寸 3–6 分钟，5.8–10.1 GiB。200bb 单加注的完整 3 个尺寸要先调大 WSL 上限。393bb 单加注彩虹面超过本机物理内存。
- **没做到**：400bb 仍未补齐。
- **测试**：
  - `python -m pytest -q`：507 passed，40 skipped，3 分 49 秒。
  - 原生（`POKERLAB_NATIVE=1`，命令见 README）：76 passed，31 秒。
  - 完整浏览器流程（`POKERLAB_BROWSER=1`）：1 passed，26 秒。
  - `cargo test --release`：22 passed，1 ignored（引擎代码在这一轮没有再改）。

## 400bb 范围库与完整三尺寸（2026-11-01）

完整状态见 PROJECT_STATE A2g，决策见 DECISIONS D37。
- **400bb**：56 条线已补齐，全部和页面核对过，行动线的 400bb 已可用。
- **新开关**：允许占用闲置后台程序的内存，默认关。
- **实测**：193bb K72 完整 3 个尺寸 668 秒、18.97 GiB。真实 400bb K72 河牌不加注 487 秒、17.35 GiB。
- **测试**：
  - `python -m pytest -q`：510 passed，40 skipped，5 分 29 秒。
  - 原生（`POKERLAB_NATIVE=1`，命令见 README）：76 passed，33 秒。
  - 完整浏览器流程（`POKERLAB_BROWSER=1`）：1 passed，29 秒。
  - `cargo test --release`：22 passed，1 ignored（引擎代码在这一轮没有再改）。

## GTO Wizard 功能对照与补齐（2026-11-01）

完整状态见 PROJECT_STATE A2h，决策见 DECISIONS D38–D40。
- **新做**：锁定后重解、按总频率锁定、Player Profiles、Compare EV、Blockers、Breakdown、Ranges、发牌报告、多牌面报告、行动线调用范围库。
- **验证**：河牌玩具局面和手算一致；没有和 GTO Wizard 对比。
- **没做**：翻前整棵树（等用户批准），Coaching 视频不搬运（D40）。
- **测试**：
  - `python -m pytest -q`：519 passed，58 skipped，3 分 52 秒。
  - 原生（`POKERLAB_NATIVE=1`，README 的命令加 `tests/test_incentives_native.py`）：87 passed；`tests/test_flop_report.py`：10 passed。
  - 浏览器（`POKERLAB_BROWSER=1`，`tests/test_workbench_browser.py` 和 `tests/test_study_browser.py`）：7 passed。
  - `cargo test --release`：22 passed，1 ignored。
  - 引擎库（`cargo test --release --locked -p postflop-solver --lib`）：57 passed，4 ignored，含逐位回归。

## 翻前整棵树（2026-11-01）

完整状态见 PROJECT_STATE A2i，决策见 DECISIONS D41。
- **数据**：100、150、200、400bb 共 1267 个节点、4115 个动作，全部节点比例之和为 100%，组合数和页面最大差 0.036。
- **界面**：行动线显示每个节点的全部动作，默认 150bb。全下、多人、翻前结束显示说明。
- **验证**：闭合线的范围和之前记录的范围一致（163 条，每类权重最多差 0.005）。4bet 线和 squeeze 线在真实界面解成功。
- **没读**：低于 0.3 组合的线；第三名玩家入池后的后续（150bb 读到 98.45%，其他深度没读）。
- **测试**：
  - `python -m pytest -q`：539 passed，58 skipped，5 分 41 秒。`tests/test_preflop_library.py` 里有两条真实浏览器流程。
  - 浏览器（`POKERLAB_BROWSER=1`，`tests/test_workbench_browser.py` 和 `tests/test_study_browser.py`）：7 passed。
  - 原生和 cargo 这一轮没有重跑：只改了翻前库和行动线，引擎没动。

## Player Profile 默认数字核对（2026-11-02）

用户批准后，从 GTO Wizard 的 Player Profiles 列表读页面文字，没有提交表单，也没有选择或保存 Profile。
- **结果**：7 组里 6 组和代码一致。Calling Station 的 Check 原来记成 +3（来自低清截图），页面是 +2，已改。
- **影响**：按旧 +3 解过、存下来的配置，下次打开会显示为自定义 Profile，数字不变。
- **没做**：Profile 和锁定后重解还没有和 GTO Wizard 的解对比。

## Player Profile 和 Node Lock 对比（2026-11-02）

完整数字见 PROJECT_STATE A2j，决策见 DECISIONS D42。余额前后都是 500。
- **河牌**：Calling Station、Nit 每个节点差不超过 0.15 个百分点。三种 Node Lock 上游选项的 BB EV 差不超过 0.1 个百分点底池，锁定路线上的频率差不超过 0.2，旁支混合节点差到 1.2。
- **翻牌**：差距来自模型。GTO Wizard 一次解一条街，激励只算当前街。给引擎加 `streets` 后，BB 下注 13.91 对 13.9；默认的所有街是 21.24。
- **改动**：Profile 的作用范围、Node Lock 的上游选项、按总频率锁定的分配更锐利。
- **修掉**：Equity 舍入成负数时节点标注崩溃；宽范围的节点锁超过请求上限，页面只显示 Failed to fetch。
- **没对上**：按总频率锁定的逐手分配，它的规则没有公开。
- **测试**：
  - `python -m pytest -q`：540 passed，64 skipped，5 分 14 秒。
  - 浏览器（`POKERLAB_BROWSER=1`，`tests/` 下全部 7 个 `*_browser.py`）：28 passed。
  - 原生（`POKERLAB_NATIVE=1`，README 的命令加 `tests/test_incentives_native.py` 和 `tests/test_flop_report.py`）：100 passed，40 秒。
  - `cargo test --release`：22 passed，1 ignored。引擎库（`cargo test --release --locked -p postflop-solver --lib`）：57 passed，4 ignored，含不开激励时的逐位回归。
  - 原生和 cargo 跑在最后两处页面改动之前，这两处不涉及引擎。

## 知识库方法论层（2026-11-02）

完整状态见 PROJECT_STATE A2k，决策见 DECISIONS D43。
- **结果**：从 24 个 HHP 视频和 21 篇公开 Blog 提炼出 242 条，每条有信号、调整、原因、幅度、限制和证据，矛盾分开保留。
- **助手**：新增 `find_methods`、`read_method`，回答先讲方法，手牌只作例子。真实问答通过。
- **Solver**：验证了 8 条：3 条支持，3 条部分支持，1 条不支持，1 条没测出。其余 234 条只是经验判断。
- **测试**：
  - `python -m pytest -q`：549 passed，64 skipped.
  - 方法论相关（`tests/test_build_methods.py`、`tests/test_coach_knowledge.py`）都在默认测试里。这一轮没有改页面和引擎，浏览器、原生和 cargo 没有重跑。

## 真实手牌测试（2026-11-02）

完整状态见 PROJECT_STATE A2l，决策见 DECISIONS D44。
- **手牌**：只有 现场笔记的 8 手，没有真实导出。
- **结果**：10 题全部完成，6 个单挑题用了 Solver 和 Node Lock，胜率全部来自工具。60 项评分 56 项过，4 项部分，这是我打的，用户还没有盲评。
- **修复**：标签门槛、笔记手牌的统计口径、`calc_equity`、`find_preflop_ranges`、`lock_node`、`get_job` 等待、紧凑报告。
- **测试**：
  - `python -m pytest -q`：567 passed，64 skipped。
  - 浏览器（`POKERLAB_BROWSER=1`，`tests/` 下全部 7 个 `*_browser.py`）：29 passed。
  - 这一轮没有改引擎，原生和 cargo 没有重跑。
