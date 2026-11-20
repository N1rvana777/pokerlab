# 实际进度（2026-09-21）

## 接管结论

工作区根目录没有 Git 仓库，未执行初始化、重置、清理、提交或推送。
接管时存在 CLAUDE.md、PROGRESS.md、pyproject.toml、core/math/games/sim/output、
测试及 C 枚举源码；不存在 README、AGENTS.md、ARCHITECTURE.md、plan.md、memory.md、docs。
`.claude` 只有本地设置，不含旧计划文件；未把其中可能的私人设置复制进文档。
旧规划是赌场数学/求职作品，与当前 Solver 目标不同；完整旧说明已归档，根入口更新。
旧代码及数据不改动。101 项旧测试实际通过，不能据旧文档把 Solver 视为已完成。

环境实测：Windows 11，Core Ultra 9 285K，24 逻辑 CPU，31.71 GiB 物理内存；
RTX 5080 专用显存 16303 MiB（约 15.92 GiB）。基准时 Windows 可用内存约 11.15 GiB。
Windows 原先无 Rust/C 编译器；现有 Ubuntu WSL 内已安装 cargo/rustc 1.75 与 GCC 13。
原生计算当前单线程 CPU，无 GPU 提速承诺。

## 已交付：阶段 0 原型

- 固定源码 commit 的 b-inary/postflop-solver，保留原 AGPL 文件，未修改上游代码。
- 根 Cargo 项目 + JSON CLI，可真正运行 River、Turn 和完整剩余街道 Flop 小树。
- Equilibrium 与 Fixed 分开；报告实际精度、单位、迭代、停止原因、同模型收益提升。
- 先基线、全树编译、冻结对手、优化 Hero；对手冻结前后摘要一致。
  处理同构节点重复访问，防止软偏置重复应用。
- Station 与 Overbluff 可叠加，另有四项特质雏形；Neutral 不平滑，
  活动规则允许激活合法零频动作；历史条件与每街成牌类别更新有测试。
- 根节点逐组合 Equity/EV、行动 EV、策略、raw reach/排斥后权重。
  有覆盖摘要与有限规则样本；不是完整节点浏览器。
- 双阶段内存预检、实际 Linux 进程峰值 RSS、串行基准、配置 SHA256、原子保存结果。
  不使用结果缓存，配置变更重新计算，因此当前不存在复用旧 EV 的缓存路径。
- 独立 Python reference：完整 kicker 排序、River 纯策略枚举 + LP、
  三街合成固定策略的解析递推，均不调用生产引擎计算参考值。

## 可核对的数值

River 示例的独立均衡根 EV 为 13.333333…；原生为 13.333293，
实际 exploitability 0.009044 筹码，即底池 0.045220%，目标 0.05%，530 次迭代。

跨街案例：AsAh 对 KcKd，AcAd2h，无 Raise，每街可下注 10，pot=20，stack=30。
对手面对 Bet 跟注 1/2，被 Check 后前两街下注概率为 1，仅改变 River 下注概率 q。
这是明确的合成验收模型，不冒充实战人口模型；生产引擎穷举完整合法后续牌。

| 起始街 | q=0 独立精确 BR | q=1 独立精确 BR |
|---|---:|---:|
| Flop | 45 | 50 |
| Turn（补 3s）| 35 | 40 |
| River（再补 4c）| 25 | 30 |

原生精确 MES 与各参考值误差小于 0.001；迭代回应与逐行动 EV 误差小于 0.025。
不仅断言变化，还逐行动比较正确值。固定对手 Check/Bet 双分支另以独立完整
纯策略枚举比较 BR，分别测试仅 Overbluff 与 Station+Overbluff。

## 验证记录

- 接管基线：101 passed，54.67 秒。
- 独立参考：10 passed，0.66 秒。
- 最终普通回归：111 passed，10 skipped，62.99 秒。10 项跳过为显式 opt-in 原生集成。
- 最终原生集成：10 passed，4.31 秒，包括 CLI 启动、保存和拒绝覆盖已有结果。
- Rust 编译器单元测试：2 passed，验证叠加/Neutral/零频、更新牌型与历史条件。
- 原生覆盖：LP 对照、完整三街传值、同模型收益、冻结、权重和 blockers、
  花色重命名、IP Hero、平局、输入拒绝、预算拒绝、精度不足停止。

最终真实基准保存在 `outputs/phase0-benchmark-final.json`，此前记录保留在
`outputs/phase0-benchmark.json`，完整配置/精度/时耗/硬件可复查。
最终基准（单次热环境、含 Python/WSL 启动）为小 River 0.097 秒，较宽双尺寸
River 0.090 秒，单组合 Turn 0.087–0.088 秒，完整单组合 Flop 0.645–0.656 秒。
Flop 原生总耗时 0.582–0.586 秒，实测原生峰值 RSS 约 14.89 MiB。
VmHWM 在最终 stdout JSON 编码前采样，不含整个 WSL VM、Windows 和 UI 占用。
**没有据此证明日常宽范围 Flop 的数分钟目标**；宽 Flop、多 SPR、大树矩阵尚待测量。

## 尚未完成与下一项关键工作

阶段 1 尚未交付：无浏览器 UI、13×13 范围编辑、节点导航、手动锁、undo/redo、
异步任务/取消/崩溃恢复、结果缓存、完整策略保存/续算、模型敏感性、MCP 或三人模块。
当前只开放 OOP 先行动、两人有效筹码、双方同街相同尺寸、无 Raise 的有限树；
不是完整无限注树编辑器。特质牌力分类较粗，未实现尺寸响应、阻断牌或 Equity 特征。

下一项关键工作：把精确 MES 价值对应的**信息集最佳回应策略**直接提取，替代
固定对手模式的多轮 DCFR；加入可查询的节点/组合报告及无复活 reach 验证，
随后验证 Raise、手动非对称锁，再做真实 River 中文工作台端到端流程。
三人明确后续里程碑是小型 River 固定两名对手 + 独立枚举，不使用两份单挑拼接。
闭源商业发布前的引擎授权/替换与完整第三方许可清单仍未解决，当前仅私人原型。
