# 当前架构与引擎审查

## 模块

`native/main.rs`：输入校验、内存预估、候选引擎适配、基线求解、完整树遍历、
固定对手回应及 JSON 报告。`native/policy.rs`：纯策略编译，只有本人底牌、
当前公共牌、已发生行动及模型参数可见。`src/pokerlab/solver`：Windows/WSL
启动、资源预算、配置 SHA256、原子报告写入和独立小型验算。
原 core/card 复用于独立参考输入；旧边注模块不改动。

原生引擎 CPU 单线程（当前禁用所有可选特性），Python 不执行生产 CFR。
当前无 HTTP 服务、浏览器、云服务或 GPU 计算。JSON CLI 为后续任务和 UI 接口基础。

## 引擎审查（2026-09-21）

官方源：[仓库](https://github.com/b-inary/postflop-solver)、
[接口文档](https://b-inary.github.io/postflop_solver/postflop_solver/struct.PostFlopGame.html)。
本地具体源码 commit：`9d1509fe5077d019825f833eed04b16d342dfda1`，未经修改。
上游标记 development suspended；Cargo 版本号不能替代 commit。当前可在 Rust 1.75 构建。
直接依赖 serde 1.0.217、serde_json 1.0.138；传递依赖由根 Cargo.lock 固定。

- DCFR：`src/solver.rs` 的 solve_step；策略与 regret 为 f32。
- 锁生命周期：allocate_memory 后、finalize 前；finalize 后不能再 lock/unlock。
  本适配器在基线迭代后暂不 finalize，编译锁，再继续回应迭代，最后统一 finalize。
- 完整树访问：history/apply_history/available_actions/possible_cards/play。
  当前遍历所有合法机会和行动，包括基线零到达节点。
- 最佳回应：utility.rs 的 compute_mes_ev，先按信息集汇总对手 reach，
  再选行动，不能把每对隐藏手牌分别取最优。
- 锁定时 compute_mes_ev 尊重玩家自身的锁；因此固定模式仅使用无锁 Hero 的
  `MES_hero - current_hero`，不会把引擎锁定后的 exploitability 当作无约束 GTO 精度。
- 内部 current/MES EV 已减 pot/2，报告根 EV 加回该偏置。
- 花色同构：上游会合并机会节点。v1 仅接受花色对称的特质规则；再次遇到已有锁的
  同构节点时复用，避免对软偏置重复应用。手动花色锁尚不接受，不能静默合并。
- bincode 特性有序列化接口，但本原型**未启用、未验收**。存在文件接口不等于
  本产品已支持保存完整 regret 状态或断点续算；报告只保存配置与最终根摘要。

## 模型 v1

基线：当前配置下 DCFR 的平均策略；未收敛或零 reach 区域不得称为可靠 GTO。
Neutral 按位保留基线。活动软特质按 kind、strength 排序后累加 logit 偏置；仅在
实际应用规则时启用 1e-6 零概率下限。面对 bet 和主动进攻分别选择动作。
对手全树冻结后通过相同顺序遍历及 FNV 浮点摘要核对未改变；该摘要用于回归检测，
不是安全哈希。配置另有 SHA256。

类别每街根据本人底牌及已发公共牌重新计算；v1 只做成牌类别与 board-only 比较，
尚无 equity/阻断牌/听牌等级、尺寸曲线或强弱牌的完整语义。River give-up 使用
已发生的同玩家 Flop/Turn 进攻条件。示例参数不含真实玩家数据。
coverage 中 zero_reach 是**编译过的前缀策略**下的原始 reach，不是后验联合概率。
样本最多 24 条，不代表完整树可视化已实现。

固定模式仍运行锁定对手的 DCFR 并实测 Hero 差距；compute_mes_ev 给出精确 BR
价值，但尚未导出直接 BR 策略。因此大树回应性能优化仍是关键后续工作。

## 许可清单与商业化边界

| 部件 | 来源/许可 | 当前用途 |
|---|---|---|
| postflop-solver | Wataru Inariba，AGPL-3.0-or-later，原 LICENSE 保留 | 私人原型原生计算 |
| serde / serde_json | MIT OR Apache-2.0 | JSON 协议 |
| regex / once_cell 等 | 具体版本见 Cargo.lock，各自上游许可 | 引擎传递依赖 |
| SciPy / NumPy | BSD 系列，上游分发自带许可 | 独立验算；旧分析工具 |
| psutil | BSD-3-Clause | 本机资源检查 |

完整第三方发布清单尚未完成，当前没有发布操作。AGPL 是未来闭源收费的明确障碍；
模块或独立进程边界不意味着获得闭源商业授权。商业化前需相应授权或合适替代实现，
并审查完整依赖及其声明。不能删掉或改变上游许可。
