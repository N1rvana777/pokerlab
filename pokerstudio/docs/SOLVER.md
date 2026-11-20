# Pokerstudio Solver 接口与验收

Pokerstudio 仅转换和验证输入，全部扑克数值来自现有 `pokerlab.solver` 原生引擎。没有修改 Solver 核心、引擎补丁、原工作台服务或启动方式。

## 运行边界

Windows 后端复用 `pokerlab.solver.server.Jobs` 的单任务线程池和 `workbench.solve_cached`。实际调用已有 WSL Ubuntu 的 `scripts/native_worker.py`，执行现有 `target/release/pokerlab-solver`。Windows 可用内存保留 2 GiB，WSL 保留 512 MiB；跨进程 `engine.lock` 串行求解；地址空间预算、超时、取消后的 TERM/KILL 与进程组 wait/reap 保持原实现。

任务、完整策略和基线缓存仍在原仓库 `outputs/jobs`、`outputs/cache`。每个 Pokerstudio 求解另外记录 `studio_input.json`，含明确输入来源、手牌 id、筹码单位、根行动者与分析假设。最终策略快照不是 CFR 续算状态。

## Python 与 HTTP

`pokerstudio.solver.SolverAdapter` 提供：

- `start(config=None, hand=None, options=None)`：验证后提交真实异步求解，返回原生 job `id` 与状态、`solver_input`。
- `status(id)`、`cancel(id)`：查询进度或请求取消。取消请求后仍须等待终态。
- `result(id)`：只读取 `completed` 任务；失败、运行中、取消不返回成功报告。
- `inspect(id, path=[], variant='response')`：提交真实节点查询，支持 baseline/model/response。
- `close()`：取消本实例任务并等待线程和监督进程完成。

模块提供 `validate_config`、`prepare`、`config_from_hand` 和 `default_config(name)`。示例必须显式选择，不能用示例填补真实手牌未知信息。应用 HTTP 的 Solver 状态统一使用 `solve:<job-id>`：`POST /api/solver/start`、`GET /api/task?id=solve:…`、`POST /api/task/cancel`、`GET /api/solver/result?id=solve:…` 与 `POST /api/solver/node`。

## 实际支持与拒绝规则

支持 schema v1 两人 Flop/Turn/River、街开始 OOP 根、Hero 为 OOP 或 IP、有效剩余筹码、双方具体/类范围、三街最多三种尺寸、至少 2x 或 All-in 加注、SPR≤20。保留固定对手特质、完整 Node Lock、IP 独立下注/加注尺寸、Turn/River Donk。Node Lock 的树、牌面、动作签名由原生引擎最终验证；Flop/Turn 手动锁必须完整展开实际公共牌分支。

自动手牌映射要求明确 `amount_unit='chips'`、整数 `pot` / `effective_stack`、本街 3–5 张已知公共牌、两名明确 OOP/IP 玩家和双方明确范围；Hero 由 `options.hero=0/1` 指定。未知底牌可以保留 null；所有已知牌张检查重复与冲突。映射不根据不完整行动猜底池，不把摊牌底牌暗中当作整条对手范围，不转换美元或舍入小数筹码。没有自定义尺寸时，记录明确的 50% 三街下注、无加注默认研究树。

当前街已经发生行动时，自动映射拒绝；可以单独输入并确认本街开始配置，必须与已记录 board/pot/effective_stack 一致。这表示从明确局面重新分析，不能冒充复现任意中途决策。三人、边池、未来抽水、Preflop、IP 根、任意 Raise-to、未知必要字段和内部 runtime 路径拒绝处理。范围原文本保留，不删除其中与公共牌冲突的组合；有效组合、排序与范围重叠语义由原生引擎最终校验。

根 EV 为起始底池份额加对手未来投入减本人未来投入；旧投入是沉没成本。均衡报告的 exploitability 与固定对手报告的 Hero response gap 分开显示，不能互相替代。修改手牌后，保存的分析标记过期。讲稿引用必须保留范围、尺寸、模型和测得精度。

## 2026-10-08 实际验收

`python -m pytest pokerstudio/tests/test_solver.py -q`：24 passed。覆盖缺字段、重复牌、单位、三人/边池/抽水、范围权重、SPR、非法尺寸、Node Lock、双方独立尺寸、输入审计及失败/取消不得读取成功结果。

真实原生测试由根代理在获准的 WSL 环境执行：

```powershell
$env:POKERLAB_NATIVE='1'
python -m pytest pokerstudio/tests/test_solver_native.py -q
```

结果 **3 passed，5.70 秒**，只使用小型 River，没有大树并行基准。此前受限环境实际报错 `Wsl/Service/E_ACCESSDENIED`，使用获准执行环境后通过，没有绕过预算、锁或监督进程。

已知 `examples/river.json`：board 2c3d7h8s9c，pot20、stack30，OOP AsAh/QhJh，IP KsKh/TcTd，Bet10 无 Raise。真实 OOP EV **13.33328914642334**；独立 Python River 收益矩阵与线性规划 **13.333333333333334**；绝对误差 **0.0000441869099940817** 筹码。实测 exploitability **0.00932455062866211** 筹码，530 次迭代，目标 0.01，达到目标；双方 EV 和为20，监督进程 `process_reaped=true`。完整输入、预算与哈希见 `pokerstudio/data/solver_acceptance_equilibrium.json`。

固定 Station+Overbluff River：同一对手原 Hero EV **13.32844066619873**，BR **14.686494827270508**，提升 **1.3580541610717773** 筹码。由真实导出策略构造独立混合计划、Python 收益矩阵重评 **14.68649446964264**；对手摘要保持冻结。原生独立 sum-product 重评误差0、容差0.0004筹码。固定模型 response gap 0 不代表无限精度证明，也不替代基线 exploitability **0.009438872337341309**。完整输入与验证见 `pokerstudio/data/solver_acceptance_fixed.json`。另验证立即取消最终为 cancelled，不能取得成功结果。

未在本次适配器中扩展或重新证明所有 Flop/Turn 性能；原 Solver 最新测量和大树限制仍以根 `docs/PROGRESS.md` 为准。原引擎的 AGPL-3.0-or-later 与固定 commit 保持原许可条件；进程适配不产生闭源商业授权。
