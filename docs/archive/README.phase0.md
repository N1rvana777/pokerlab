# PokerLab 本地翻后 Solver

当前是**阶段 0 的可运行原生验证版本**，不是完整工作台。沿用原 pokerlab
根目录；赌场数学 Python 代码保留，旧开发指令已归档。最新需求见
[产品需求原文](Codex_Poker_Solver_Prompt.md)，实际状态见 [进度](docs/PROGRESS.md)。

## 本机启动

在本目录 PowerShell 中运行：

```powershell
python -m pokerlab.solver examples/river.json --output outputs/my-river.json
python -m pokerlab.solver examples/station_overbluff.json --output outputs/my-response.json
python -m pokerlab.solver examples/flop_barrel.json --output outputs/my-flop.json
```

当前已在本机 Ubuntu WSL 中构建 `target/release/pokerlab-solver`。
Python CLI 自动调用该二进制；若以后构建 Windows 原生 `.exe`，优先使用它。
只在本机计算，无远程服务、账号、订阅、GPU 或 Pio 依赖。
结果同时输出为 JSON；输出文件已存在时拒绝覆盖。保存的是配置和报告，**不是续算状态**。

重新构建：`powershell -ExecutionPolicy Bypass -File scripts/build.ps1`。
脚本核对引擎版本和未修改状态，使用 `Cargo.lock`。当前 WSL 编译器为 Rust 1.75。
新机器需要 Rust 与 C 链接器，或 Ubuntu WSL 中的 `cargo rustc build-essential`。
Python 安装方式：`python -m pip install -e '.[dev,solver]'`。
当前目录自身没有 `.git`；不会自动初始化、提交或推送。

候选源码位于 `third_party/postflop-solver`，固定版本
`9d1509fe5077d019825f833eed04b16d342dfda1`，原始 LICENSE 和声明保留。
新检出环境若缺少此目录，先 clone 官方仓库并 checkout 此确切 commit，再构建。

## 可用输入与输出

- board：3/4/5 张不同的牌；players：按 OOP、IP 顺序的范围文本。
  例如 `AA,AKs` 或 `AsAh:0.25,QhJh`；具体组合按较高点数在前。
- pot：当前已扣除既往抽水后的底池；stack：双方有效剩余筹码，整数筹码。
  当前只支持无未来抽水、根节点 OOP 先行动；hero 可为 0 或 1。
- bets：Flop、Turn、River 三项，同一街暂时双方使用相同尺寸。
  `50%` 为下注前底池比例；`10c` 为 10 筹码；`a` 为 All-in。
  可用逗号分隔最多 3 个尺寸。Raise 尚未通过适配层验收，会明确拒绝。
- mode：`equilibrium` 或 `fixed`；target_unit：`chips` 或 `pot_pct`。
  `0.05` + `pot_pct` 表示起始底池的 **0.05%**。
- 固定对手模式先跑基线、编译整棵合法树并冻结对手，再迭代 Hero，
  报告同一模型下的基线收益、回应收益、精确 BR 值和实际回应差距。
- 报告含根节点逐组合策略、Equity、逐行动 EV、raw reach、牌张排斥后的权重，
  全树覆盖计数、前 24 个规则解释样本、锁定摘要校验、时耗和内存。
  根 EV 以筹码计：底池所得 + 对手新投入 − 自己新投入，旧投入是沉没成本。
  无抽水时双方根 EV 和为 pot。内部引擎的零和 EV 已加回 pot/2。

特质参数目前是 logit 偏置，不是百分点或整体下注频率。
支持 station、overbluff、underbluff、weak_check、double_barrel_give_up、
delayed_aggression；strength 为 0..6，streets 用 [3,4,5] 表示适用公共牌张数。
零强度/Neutral 精确保留基线；有效特质允许用显式 1e-6 概率下限激活合法零频动作。
这些都是**研究假设**，不是用真实对局数据校准的模型。牌型条件目前较粗，详见架构。

`flop_barrel.json` 是**合成对手策略的真实 Hold'em 验收牌局**，不是日常玩家预设：
AsAh 对 KcKd，AcAd2h，Hero 所有后续公共牌都保持四条优势。
对手面对下注跟注一半；被 Check 后 Flop/Turn 总下注，River 以指定概率下注。
它用于独立核对跨街传值，不能代表常见 Flop 的性能或策略。

## 验证与基准

```powershell
python -m pytest -q
$env:POKERLAB_NATIVE='1'
python -m pytest tests/test_solver_native.py -q
Remove-Item Env:POKERLAB_NATIVE
wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- cargo test --release
python scripts/benchmark_solver.py --output outputs/my-benchmark.json
```

普通 pytest 会跳过需要原生引擎的集成测试。旧数学测试含完整五张牌枚举，约一分钟。
基准串行，含 River、Turn、完整 Flop，以及多尺寸较宽 River；不在普通测试里重复跑。
内存预算默认示例 2–4 GiB；CLI 保留至少 4 GiB 可用内存，最大 24 GiB。
建树前保守估算，随后检查引擎数据、锁副本、缓冲、报告的估计峰值；超限明确报错，
不会偷偷缩树。Linux VmHWM 是实测进程峰值 RSS，不是整台 Windows/WSL 峰值。

若出现 WSL Access denied，在普通用户 PowerShell 运行；Codex 沙箱需要批准 WSL 执行。
若出现精度 `iteration_limit` 或 `numerical_floor`，该结果未达到用户目标。
保证仅限当前范围、规则、离散树；小于底池 1e-6 的目标不宣称达成。

当前没有 UI、任务队列/取消、节点导航、手动锁、范围库、断点续算或三人求解。
下一步是锁定后的直接最佳回应策略提取、Raise 与非对称锁验证，然后构建 River 中文工作台。
