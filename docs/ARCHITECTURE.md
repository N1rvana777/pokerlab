# 当前架构与引擎审查

## 模块和数据流

- `native/main.rs`：校验、建树预算、上游适配、DCFR 基线、完整对手编译／冻结、报告与节点查询。
- `native/policy.rs`：组合特质；只读取本人底牌、当前公共牌、已发生行动及参数。
- `native/response.rs`：精确信息集最佳回应策略导出；不运行固定对手 CFR。
- `native/snapshot.rs`：带版本与输入指纹的全树最终策略快照；没有 regret 续算。
- `native/checkpoint.rs`：独立PLCFR001原始累计策略／regret续算状态；只在模板和finalize之前使用。
- `native/memory.rs`：受控glibc布局的分项预检余量与保守回退；不是实测内存，不替代监督进程限额。
- 引擎 `solver_scratch.rs`：DCFR临时数组的拥有型线程局部复用；取出后不持有池借用，父子递归／Rayon任务各自独占缓冲。精确容量匹配、按逻辑长度初始化，闲置f32/f64合计最多1MiB／线程（另有小量元数据），包含在现有256MiB临时余量内；数学次序和原16位存储不变。
- 引擎 `sparse_storage.rs`（2026-10-16）：无硬锁压缩任务按当前 canonical 公共牌仅存合法组合，每行另保留一个冲突组合占位值，维持原 CFR 量化比例。`GameNode` 原始切片是物理布局；策略、regret、CFV 的逻辑读取须经 `dense_*` 视图，或明确使用合法索引的专用计算路径，不能按逻辑长度解释物理切片。共享已有合法索引，不增加每节点指针；临时展开池另限1MiB／线程，仍计入256MiB余量。闲置缓冲保留已初始化长度，展开完整覆写，避免重复清零。后续压缩regret-matching直接从物理i16及占位值初始化完整f32策略，再沿用原归一化顺序；BR概率直接读视图并进行原f64归一化，不再多复制f32数组。
- 稀疏布局在 prepare 后、build 前选择，建树计划必须等于实际物理数组。生产硬锁、非压缩路径仍用稠密存储；公共硬锁API拒绝稀疏实例，bunching和上游bincode也不支持此布局。PLPOL002/003、PLCFR001仍保存完整逻辑顺序，磁盘文件未缩小。旧最终模型的非法槽可归并，但合法16位值和scale必须保留；最终模型永远不能作CFR续算状态。
- `src/pokerlab/solver/workbench.py`：基线缓存、跨进程锁、任务目录、监督启动及查询。
- `src/pokerlab/solver/resources.py`：实测Windows／WSL内存、安全余量、自动或手动上限计算；显示快照与锁内启动复测分开。
- `scripts/native_worker.py`：WSL 内存限制、进程组取消回收、临时快照清理；仅显式诊断支持可选时限。
- `scripts/benchmark_iterations.py`：显式冷启动固定迭代A/B；可选旧／新原生二进制，双预算及串行锁保留，无墙钟时限。测量迭代／精度检查各自耗时和CPU／内存／上下文切换，不读取缓存、不编译模型或导出策略，不作为目标精度验收。
- `scripts/benchmark_config.py --cold --output <新目录>`：完整冷求解，基线、检查点和模型／BR快照仅写入该新目录，不读取共享缓存；记录目标／实测精度、分阶段耗时、峰值、退出回收及配置／二进制摘要。保持原线程配置，默认无墙钟时限。
- `src/pokerlab/solver/server.py` 与 `web/`：127.0.0.1 中文工作台、异步任务、输入过期、完整研究保存重开。
- `src/pokerlab/solver/agent.py`：原8765工作台的独立助手业务适配；自己的配置版本、Solver工具、会话与认证，复用provider协议，不创建Pokerstudio实例。
- `reference.py` 等独立 Python 验算：River 纯策略收益矩阵／LP、合成跨街解析参考。旧数学模块保留，不承担生产 CFR。

配置→构建完整离散树→求解或加载基线→编译全树对手→冻结→导出 Hero BR→sum-product 重评→报告和保存。预览在冻结之后停止，不声称已优化。首次节点查询载入所选 baseline/model/response 快照并评估；重复查询使用配置、版本、策略文件标识和路径绑定的缓存，最多 256 项或 128MiB。首次重建成本仍待优化。

## 2026-10-08 输入与独立助手入口

原Solver工作台的新输入以bb展示底池、有效剩余筹码、下注金额、节点EV与精度；目前pot/stack支持整数bb，报告EV可以为小数。新UI及独立助手配置记录可选metadata `amount_unit="bb"`，一个原生数值单位对应1 bb。发送严格native配置前剥离展示metadata，报告保留其计价声明；兼容协议仍使用 `target_unit="chips"` 和含chips的报告字段。旧报告没有metadata时显示“原筹码单位”，不把历史chips直接贴bb，不自动换算金额。载入旧研究仍保留原数字，由用户核对原始计价并明确当前单位；Pokerstudio的chips/USD手牌验证不由此展示约定替代。

范围编辑仍以具体组合权重保存，169牌类网格是输入视图。单击toggle、拖动批量赋权；滚轮按5个百分点、Shift按1个百分点调整0–100%，牌类操作均匀赋权，具体花色模式允许非对称。翻前总X%以1326组合计权，使用公开启发式排序，边界牌类全部花色同混合权重，精度受浮点表示限制。70%为928.2个加权原始组合；它不是当前街均衡或实测Equity，公共牌不参与排序；冲突组合留在输入中，仅在有效范围统计及求解中排除。调整总X%会重新生成均匀花色模板，而非保留先前非对称权重。真实Edge交互及独立计权回归已通过，结果见PROGRESS。

8765内的独立助手通过 `SolverAgent` 将配置、revision、任务与真实报告映射到read/update/start/get/inspect/cancel业务工具。配置更新要求刚读取的版本，嵌套patch合并、数组替换；保留用户未请求修改的特质和手动锁。工具上下文绑定独立Solver工作区，工具集不含视频、字幕和项目编辑。provider传输与认证协议类可复用 `pokerstudio.agent`，运行时不依赖8770服务或Studio实例。

`web/agent.js`对HTTP配置回复及工具事件使用同一个revision接收规则，拒绝低于当前快照的迟到内容。POST已真实提交但前端回复延迟时，较新工具事件保留，旧回复触发读取最新配置；后续未提交编辑不被覆盖。dirty编辑与远端更新冲突时保留输入并要求显式同步，而非自动把旧表单覆盖新局面。真实Edge竞态测试用隔离后端config REST控制回复顺序并记录版本文本，无真实provider调用。

`web/integration.js`的结果身份比较与Node Lock的局面／动作签名分开：比较实际局面、模式、单位、特质／锁、目标／迭代及存储设置；memory_budget_mb、memory_auto、time_limit_seconds和threads仅为资源限制，不改变已完成结果的数值身份。缺省空raises与profile.overrides规范化为等价空值；配置对象键顺序不造成误差。get_result呈现使用当前配置模式作为上下文，既不漏标真正旧结果，也不因同义空字段误标过期。旧失败估计在输入改变后清除，当前资源快照不能冒充已重新求解的树估计。

独立状态位于 `outputs/agent/solver-state.json`，会话在该目录下的sessions；独立认证默认 `%LOCALAPPDATA%\Pokerlab\agent`，`POKERLAB_AUTH_HOME`可覆盖。API key和付费授权仅保留内存；订阅/API明确分开、不自动回退。本轮此独立入口已用existing_cli／gpt-6.1-sol完成真实小型River配置修改、求解与读取报告，真实Firefox显示报告和回答；均衡0.0466227531% pot达到0.05%目标，缓存基线530次不是本次新增迭代，进程exit0并已回收，API未使用。证据位于 `outputs/solver-agent-acceptance-20261008/acceptance.json`；不沿用Pokerstudio账号验收，也不扩大为完整宽树、首次SIWC授权或收费API的证明。

## 固定引擎

b-inary/postflop-solver，commit `9d1509fe5077d019825f833eed04b16d342dfda1`，加上 `third_party/patches/expanded-suits.patch`。原审查日期 2026-09-21，上游当时标记 development suspended。Cargo.lock 固定依赖，Rust 1.75 可构建；现已启用 Rayon CPU 并行，工作台默认 8 线程，旧 CLI 未指定时仍为 1，允许 1–16。未使用 GPU。累计补丁包含完整花色构造、分配前存储计划及原位策略写入；构建前校验完整差异，原许可证不变。

- DCFR 由上游 `solve_step` 提供；regret／策略使用 f32。
- allocate_memory 后、finalize 前编译对手锁。BR 直接写 Hero 策略，之后统一 finalize；不重新训练对手。
- 对手冻结前后按规范遍历顺序计算浮点摘要并比较；这是回归校验，不是密码学安全哈希。
- BR 遍历先处理机会概率与对手 reach，在每个本人手牌／公开历史的信息集合并隐藏牌收益，再选最大动作。后续策略已递归优化；不对未知牌分别优化后取平均，也不预知未来公共牌。
- 导出策略以单独 `compute_current_ev` 的 sum-product 遍历复评，再与 `compute_player_mes_ev` 的Hero单席最佳回应对照；均衡仍用双席MES。BR只并行独立子树，保持原行动顺序归并和相同平局选项。共享终局求值器，因此还需要独立 Python 小型数值参考。
- 无约束均衡 exploitability 与固定模型 Hero response gap 分别报告。冻结后的双人 exploitability 不能冒充原始 GTO 精度。
- 内部零和 EV 加回 pot/2 后报告根收益；节点表另核对累计投入。没有后验权重时未定义收益返回 null。
- `expand_suits=true` 保留非对称锁所需的完整公共牌分支；新增 `auto_suits=true` 时，仅在无手动锁条件下使用上游按范围权重判定的同构。当前特质只依赖牌类及公共行动，具有花色置换不变性；具体底牌/公共牌映射仍由引擎负责。不得将未来不对称特质直接放入这条路径。
- `compression=true` 接通上游 16 位存储、BR 读写、快照读写与节点统计。无手动锁的压缩模型编译至对手现有策略缓冲，不另复制完整锁数组；从此只运行 Hero BR，不再运行 CFR，并重算摘要核验对手未变。Neutral 节点不重复量化。含手动锁时保留上游 f32 锁，查询其快照使用 f32 避免重新量化硬锁；内存需求可能更高。软策略的 16 位量化不等于无误差，不修改原重评容差。
- 分配前从公开树、实际同构系数及双方各自组合数计算 arena、动作、IP、机会数组；再计硬锁或编译访问位图（每个原生节点一bit，替代HashSet）。Linux GNU受控分配器、大于等于512MiB的引擎使用分项余量：两座arena的128MiB、每工作线程2MiB栈和主线程8MiB、五个大分配40KiB页对齐余量、misc/locks的15%及256MiB临时余量。小树或环境不匹配保留原15%整树加256MiB公式。建树后仍校验数组总字节与upstream memory_usage一致，RLIMIT_AS与Windows/WSL预留不变。原24 bytes/max-hands粗估仅用于诊断。预检不是实测峰值，RSS与VmPeak均采样记录；牌类缓存按精确牌张集合、有数量上限，不缓存历史相关策略。
- 新节点锁携带局面、当前公共牌、合法动作签名；变更范围、位置、尺寸或 Donk 后拒绝旧锁，防止相同数字路径指向不同动作。锁只属于对手；Hero 始终无锁优化。批量编辑展开成明确组合分布，优先于软特质；没有暗中归一化硬锁。
- 采用上游合法行动、最小加注、有效筹码、退款和收益规则。适配器开放倍数加注 >=2x 与 All-in；输入数值 Raise-to 尚未开放，报告明确标识 Raise-to。

## 特质合成 v2

基线为当前配置下 DCFR 平均策略，未收敛及零 reach 分支不能声称可靠 GTO。Neutral 精确保留基线。软特质按固定顺序累加 logit 偏置，同一玩家可叠加；优先级为手动完整分布覆盖 > 软特质 > 基线默认。

- Station：面对下注时偏向 Call。
- Overbluff／Underbluff：本人弱牌获得进攻机会时，提高／降低进攻倾向。
- Weak check：强成牌倾向下注，削弱 Check 范围保护。
- Double barrel give-up：Flop/Turn 弱牌进攻倾向，以及真实历史中本人前两街连续下注后，River 未改善弱牌偏向放弃。
- Delayed aggression：符合历史条件的延迟进攻倾向。

准确条件以 `native/policy.rs` 为准；strength 是 0–6 logit 参数，不是百分比。类别来自本人当前成牌与 board-only 对比，不包含对手底牌或未来牌。尚无完整 Equity／听牌／阻断牌分类。这些是可复现的研究假设，不是真实玩家数据结论。

合成首先在被动动作、Call、进攻类别之间归一化，再在进攻尺寸内保留基线相对分配；有效规则可通过显式 1e-6 下限激活合法零频尺寸。尺寸数量不重复放大同一手牌进攻总概率。相反偏置抵消时恢复基线。历史与手牌状态随街更新，范围通过之前策略及牌张条件传递，不每街重置。

完整树包括原基线零到达分支；未受规则影响的节点采用基线。coverage 中 zero_reach 指编译时前缀策略 raw reach，不是后验联合概率；报告最多 24 条解释样本，不能当作全树影响可视化。任意节点可另外查询最终完整动作分布。

## 缓存、资源和服务

基线 SHA256 指纹包含引擎／适配器、存储压缩、线程数、实际展开选项（含手动锁存在性）、牌面、范围、OOP/IP 尺寸、Donk 和精度／迭代配置，排除特质／具体锁分布；模型改变重编译、重评估。写入 PLPOL003，兼容读取 PLPOL002：压缩节点保存原始 u16 和 scale，避免重新加载时再次量化；硬锁保存 f32 最终概率。文件含校验元数据，原子临时写入后替换；最终策略不会用于继续 CFR。纯均衡结果的 model/response 引用同一基线文件，避免额外写两份相同策略；保存研究时仍能独立读取。旧压缩树快照依然按原配置读取，不会加载进展开树。不保证未来任意版本可移植。

2026-10-13 另加 PLCFR001：在未收敛且正常到达迭代上限时，模板编译／finalize 之前流式保存原始累计策略、regret、两个压缩比例和全局迭代数。指纹包含算法、树、范围、压缩、线程与实际同构布局，不含目标精度／迭代上限。提高上限后可继续；不加载超出所要求上限的状态，损坏文件明确拒绝。原子写入的临时文件由监督按当前 PID 清理。主动取消／崩溃尚无中途检查点；已达旧精度的状态不自动存储，严格目标可能重算。不能拿 PLPOL003 当 CFR 状态。

模型编译与摘要验证改用轻量解释器 checkpoint/restore：在当前节点编译后保存路径、实际公共牌／花色置换、reach、下注和缓存，访问子节点后恢复；不从根重复回放所有祖先，也不还原子节点的策略或锁。构建增加 thin LTO、单 codegen unit 和本机 CPU 指令集，算法／树／精度不变；需在目标机器重新构建，速度必须实测。

最终策略快照以共用16KiB缓冲块读写u16/f32，PLPOL002/003字节格式保持；原scalar编码作为测试对照。载入基线／续算后再测MES，避免先测一次随后丢弃的零策略；固定模式报告只计算Hero MES，保留独立sum-product重评和对手摘要验证。

普通工作台、CLI 和节点查询无自动墙钟超时，旧配置的 time_limit_seconds 仅兼容读取；可主动取消，精度与最大迭代仍是停止条件。测试可显式传独立时限。子进程限制glibc为两个arena，固定mmap/trim阈值128KiB和mmap数量上限65536；Rayon工作栈显式2MiB。受控模型还检查Linux GNU、所有环境值及非空GLIBC_TUNABLES/LD_PRELOAD冲突，发现冲突回退旧估计。不会增加允许的内存限额，也不修改父进程环境。

节点新增 action_details，由真实 play 后的投入变化计算：进攻额为新增投入减去需跟注额，比例分母为跟注后的底池。图形选择器直接使用 possible_cards；策略颜色依照真实频率与 is_overbet，恰好 100% 不属于超池。旧节点缓存通过 node_report=2 失效；旧研究根节点缺尺寸元数据时重新查询真实引擎。

`research.py` 保存本机命名范围和特质库；每次保存新记录，不覆盖旧命名条目。局面相关节点锁随研究而非通用玩家档案保存。敏感性按 0.5/1/1.5 倍软特质强度（上限 6）生成三个固定模型，手动锁不变，串行求解，每个子任务独立策略文件；取消父任务会传递到子进程。每个模型内比较原 Hero 与 BR；稳定性只报告根 Hero 行动，不冒充全树稳定性。

`web/research.js` 提供 OOP/IP 双范围展开与定位、最近 100 步输入撤销／重做、完整分布 Node Lock 与列表、范围／玩家库、配置复制、真实 Equity 条件分布、组合排序和筛选、敏感性实验。图表使用实际节点权重和 Equity，未按牌类抽象求解。

WSL总内存约15.47GiB。前端默认 `memory_auto=true`，载入未带该字段的旧示例时同样默认自动；后端缺字段仍为manual，保留CLI和旧请求的显式预算。自动预算取Windows当前可用内存减2GiB、WSL当前可用内存减512MiB与24GiB上限的最小值；manual进一步尊重 `memory_budget_mb`。读取失败不猜测资源，自动模式也不削减系统余量或原生数组预检。`memory_auto`只控制Python启动预算，发送严格native配置前与展示metadata分开移除；启动获得共享锁后复测，WSL监督进程再测并将最终限额写进报告。建树前与分配后预算检查及RLIMIT_AS保持，普通任务无墙钟时限。监督进程独立原生进程组，取消或显式诊断超时先TERM再KILL，wait回收。服务和CLI通过文件锁串行，避免多个任务分别通过预算而合计超限。

本轮实际资源验收包括用户宽范围保存配置pot20副本的两次完整树分配前拒绝。最新计划峰值估计5.65GiB、引擎数组4.66GiB，高于当时3.99GiB安全预算；原生exit1并已回收。完整范围、尺寸与系统预留保留，没有凭借减小合法树使其通过；用户已选择暂不关闭其他程序而保留完整树。存储诊断使用真实数组计数但未分配完整树，不等同RSS或求解验收。原截图5.37GiB计划与该保存配置不同，当前未保存配置未取得，精确复现仍有限制；具体证据与当前回归见PROGRESS。

HTTP仅绑定127.0.0.1，检查Host／Origin、跨站来源与会话令牌，限制请求体。求解仍在本机；可选助手按明确选择的正式订阅或API provider请求模型，不暴露远程Solver服务。停止服务关闭本入口助手并取消自身计算任务，恢复遗留状态时检查拥有者进程身份。精确性能与测试见PROGRESS。

## 节点显示、对比与范围库（2026-11-01）

`amounts.py` 是小数金额的唯一换算点：配置带 `chip_scale` 时，`scale_request` 把底池、筹码、绝对尺寸、`lines` 乘成整数给引擎，`scale_result` / `scale_node` 在返回时除回去。引擎和缓存键看到的都是整数，`chip_scale` 也进基线指纹。

`hand_classes.py` 给节点的每个组合标手牌、听牌和两档 EQ 桶，`server.py` 的 `with_classes` 在返回时加上，引擎不参与。类别和阈值按 GTO Wizard 的筛选项定义，听牌互斥。`web/node_view.js` 在前端按这些类别算筛选、汇总和 Equity chart。频率和占比按未阻断组合的 raw_reach 算，EV / Equity 平均按阻断调整后的权重算（D34）。

`NodeSessions` 在 `workbench.py` 里保留最多 3 个常驻 `pokerlab-solver --serve` 进程：第一行读请求并载入策略，之后每行一条节点路径、返回一条报告。载入在引擎锁和内存预算下进行，内存不足时先关掉其他会话再试；新任务开始前全部关闭。

`lines` 用 `ActionTree::add_line` 补 GTO Wizard 自定义树里固定尺寸之外的行动线。`solve_locks` 在 CFR 之前用 `lock_current_strategy` 固定某节点的频率，因此不能用稀疏存储；它用来检验频率差异值多少 EV，和复盘用的 Node Lock 是两回事。`scripts/compare_reference.py` 从 spot 文件解同一局面，打印和 GTO Wizard 页面相同口径的数字。

`mode=locked` 在 CFR 之前把 `profile.overrides` 用 `lock_current_strategy` 写进节点，没列出的组合和节点双方继续优化，缓存键含锁。上游选项在页面完成：`frozenUpstream` 取基线策略，把走到锁定节点的路线也写进 overrides。`profile.incentives` 经 `PostFlopGame::set_incentive` 进入 `Game::apply_incentive`（`streets` 限定作用的街），在 `solve_recursive` 里加到对手的动作价值上，所以只影响 regret 和上游决策；`compute_current_ev` 和最佳回应走不到这段。缓存键含激励，停止标准改为 Hero 的回应差距。`web/study.js` 放 Player Profile、频率锁、锁定对比和额外的查看页。

助手读 Solver 结果走 `solver/report_view.py`：去掉每手牌的数组，留节点概要和按牌型的表，指定的组合再给全量。网页收到 `get_result` 事件后用 `/api/jobs/<id>/result` 取完整报告。`get_job` 在任务结束前最多等 30 秒，省掉轮询占用的轮数。`lock_node` 从一个 `inspect_node` 任务里取行动方的组合，把范围锁成一个动作，配置改成 `locked`。

`coach/evidence.py` 的 `NEEDS_EVERY_HAND` 列出分母是全部手牌的统计，现场笔记不计入，其余观察带 `selected` 标记。

`coach/knowledge.py` 除了字幕和手牌记录，还读 `methods/methods.json`：`find_methods` 用 BM25 排序，中文按相邻两字切词。这个文件由 `scripts/build_methods.py` 从各批候选、合并计划和 Solver 验证生成，每条候选都必须被保留、并入或写明理由丢弃。

`preflop.py` 有两种数据。`raw/tree_<depth>.json` 是逐节点记录的树，`tree_<depth>_<part>.json` 只追加节点，`load_trees` 按深度合并；`walk_tree` 直接给出每个节点的动作和手牌比例，闭合时 `finish` 分流：两人线进 `lines`（范围由 `chained` 沿座位自己的动作相乘），全下、多人和翻前结束进 `ends`。有树的深度不用下面的库文件。

没有树的深度只读 `outputs/gtow-preflop/*.json`（schema `pokerlab-preflop-v1`），`walk` 把线拼成决策树，`/api/preflop` 返回，`web/preflop.js` 渲染行动线并填表单。节点频率 = 到达后的范围 ÷ 到达时的范围，`replay` 按座位顺序算出下一个行动的座位和每人投入。这些文件不进 Git；没有文件时界面只显示提示，其他功能不受影响。

## 离桌复盘助手（coach，2026-10-29）

```
PokerStars/GG 文本 ──pokerstars.py──┐
现场文字 ──助手 record_live_hand──┐ │
                                  ▼ ▼
                     hands.normalize + replay（逐步重放校验）
                                  │
                   store.py（outputs/coach/：修订文件只增不改 + events.jsonl）
                                  │ 只用已确认的修订
               evidence.observations ──► stats（Beta 后验、倾向分、标签、类型）
                                  │
     coach/tools.py（12 个工具）＋ Solver 工具 ──► SolverAgent.execute_tool
                                  │
      Claude 订阅（claude_provider.py） / ChatGPT-Codex 订阅 / OpenAI API（pokerstudio/agent）
```

- **`coach/hands.py`**：统一格式 `pokerlab-hand-v1` 与重放。
  - `Decision` 记录每次行动时面对的处境：要跟的金额、本街已有的下注次数、翻前已入池人数、本街第一个下注者、是否已过牌。
  - 网站手牌从严，现场手牌从宽并补记跳过的玩家（见 DECISIONS D29）。
- **`coach/situation.py`**：从重放算出一手牌的处境（牌型、位置、深度、底池类型、翻牌、行动线），用户手牌和视频手牌共用，`find_hhp_hands` 用它检索。
- **`coach/evidence.py`**：18 项统计的机会与成功定义（`DEFINITIONS`），以及摊牌记录（已知底牌加上该玩家的整条行动线）。
- **`coach/stats.py`**：
  - 后验 Beta(m·s + k, (1−m)·s + n − k)，m 和 s 来自 `priors_v0.json`（未校准）。
  - 倾向分 = round(10 × P(p > m))。
  - 标签需要 n ≥ 3 且概率 ≥ 0.85；类型需要 VPIP 样本 ≥ 15。
- **`coach/store.py`**：
  - 手牌按修订写成 `hands/<id>-<hash>/rNNNN.json`，用排他创建，不改写已有文件。
  - 确认、撤销、别名、Hero 名字和备注是 `events.jsonl` 里的追加事件，状态每次从事件重建。
  - 别名在统计时解析，所以后加的别名对历史手牌同样生效。
- **`solver/claude_provider.py`**：
  - Claude Agent SDK 会话设置：`tools=[]`，`setting_sources=[]`，`strict_mcp_config`，`permission_mode="dontAsk"`，只允许 `mcp__pokerlab__*`。
  - 每轮检查 init 帧里的 `apiKeySource` 和工具清单。
  - `RateLimitEvent` 被拒或进入 overage 时中断。
  - 会话可用 SDK 的 `resume` 继续。
  - 回答只显示最后一条助手消息的文字；工具调用之前写的文字记为 `progress_text` 事件。回答中回显的本应用工具调用格式会被删除，并记为 `text_cleanup` 事件。这两种情况都在 2026-10-29 的真实验收里出现过。
  - 登录状态只读 Claude Code `auth status --json` 里不涉及身份的字段。
- **界面**：`web/agent.js` 增加 Claude 订阅选项（默认）；`web/coach.js` 是"手牌与对手"面板，负责导入、确认或撤销、玩家档案、别名和 Hero 名字。手牌只能在这个面板里确认。

## PLO 研究模块（2026-10-23）

独立包 `src/pokerlab/plo/`，只依赖 NumPy、SciPy（LP 参照）和 psutil（资源测量），不链接 postflop-solver，没有 AGPL 代码。决策理由见 `docs/DECISIONS.md`，当前能力见 `python -m pokerlab.plo status`。

**规则层**
- `cards.py`：牌编码 `4*rank+suit`（与 fast_eval/引擎一致）、解析、冲突检查、组合索引、全手牌枚举。
- `evaluator.py`：标量参考评估器与 NumPy 批量评估器，PLO 恰好 2+3。批量 PLO 排名先按公共牌建立"每个底牌对的最佳 5 张"表，每手 6 次查表；保留逐组合的直接实现作对照。
- `betting.py`：pot-limit 公式（P/h/c），以及加注窗口和抽象尺寸的过滤、边界、去重。引擎和求解树共用这一份。
- `engine.py`：单手全状态 `HandState`（2–8 人、pot-limit、最小加注、不足额 all-in 重开规则、边池、平分零头、未跟注退回、可选抽水），以及 `observe()` 生成的 `Observation`。
- `session.py`：跨手 `reset`/`carry`、bust 策略、手牌记录（JSONL，模拟器真值，不给 agent）。
- `agents.py`：基线 agent（只用于功能检查）。
- `baseline.py`：`baseline-v1` 固定策略（按手牌向量化的类别概率），以及 `BaselineAgent`。
- `public.py`：用占位牌重放公开动作，还原每次决策的公开情境。
- `river_agent.py`：`SolverRiverAgent`。前三街用基线，河牌用 Bayes range 加子博弈求解，树外动作时重解，逐决策写日志。

**求解层（`subgame/`）**
- `tree.py`：两人单街 pot-limit 下注树（动作抽象）。
- `showdown.py`：稠密矩阵实现，以及按牌力排序、对 15 个子集做容斥的卡牌移除实现。
- `instance.py`：PLO 河牌实例（范围、指纹）和 Kuhn 校验实例。
- `cfr.py`：CFR/CFR+/LCFR/DCFR/ES-MCCFR、精确最佳回应与 exploitability、`.npz` 检查点。
- `policy.py`：`SubgamePolicy`（策略查询）和 `RiverResolver`（unsafe 重解）。
- `reference.py`：序列形式 LP 与逐手循环最佳回应，作为独立参照。

**评测与入口**
- `evaluate.py`：duplicate/session 对局报告，河牌子博弈对固定 bot 的精确评估。
- `resources.py`：时间、峰值内存、代码指纹。
- `__main__.py`：`status`、`solve-river`、`evaluate`、`simulate`。

数据流：配置 JSON → 规则/范围 → 下注树 + 摊牌预计算 → CFR 迭代（周期性精确 exploitability） → 检查点 + 报告 → `SubgamePolicy` 查询 / `evaluate` 对固定对手评估。

全局对局：`deal_hand` → agents（只看 `Observation`） → 结算 → session 账本 → 报告。

HU 决策接入：
1. `Observation` 先经 `public.replay` 还原公开情境。
2. 河牌开始时，用 baseline-v1 似然做 Bayes 更新，得到双方 range，再抽样。
3. 构造河牌子博弈并做 CFR 求解。
4. 按自己的实际手牌查策略，得到树动作，再映射为引擎动作（经合法性校验）。
5. 写入决策日志。

`scripts/plo_verify_showdown.py` 在全范围上核对容斥摊牌与精确求和。

### turn + river 联合求解（`subgame/turn.py`、`subgame/turn_reference.py`，2026-10-23）

**博弈结构**
- turn 公共牌 4 张固定；双方加权 range 显式给出；底池和筹码可配置；两街使用同一套四档精确比例和边界动作。
- turn 下注树就是 `BettingTree`。树中每个"双方都还在"的叶子（check-check 或 call）变成机会节点，枚举全部 48 张河牌，不做抽样。
- 每个叶子按它的底池和剩余筹码建一棵 river 树。全下的叶子直接摊牌。turn 和 river 的加注上限分别配置并写进报告。

**机会处理**
- 持有河牌 c 的手牌在 c 之下 reach 为 0。
- 任意一对不相交的手牌恰好剩 52 − 4 − 8 = 40 张可能的河牌，所以每张有效河牌的发牌概率是 1/40，手牌对的联合分布不随河牌改变。

**实现**
- 同一叶子下，48 张河牌的 river 树结构相同。因此 river 节点的 regret 和策略数组形状为（河牌 48, 手牌, 动作），Python 的开销按"节点"计，而不是按"节点 × 河牌"计。
- 摊牌和弃牌的质量由一个后端提供，接口都是 `turn_masses` 和 `river_masses`：
  - **稠密后端**：每张河牌一个 n0 × n1 的 compat/win 矩阵，用批量矩阵乘。只用于 n0·n1 ≤ 250,000 的小实例，作为参照。
  - **容斥后端**（2026-10-25）：
    - compat 写成两个稀疏乘积：E 把对手手牌映到它包含的牌子集，Q 把己方手牌映到它的子集并带上符号。这部分与河牌无关，turn 的弃牌也用它。
    - win 按河牌把对手的"子集事件"按（子集键, 牌力）排序后做前缀和。查询位置在建树时预先算好，存成扁平索引。
    - 内存与 range 大小成线性关系。
  - 后端只是计算方式，不属于博弈本身，所以不进子博弈指纹。`showdown: "auto"` 在 n0·n1 ≤ 250,000 时选稠密。
- `--workers N`：win 核按河牌分成 N 个行块，由线程池计算。
  - 每个行块做相同的逐行运算，所以 CFR 状态逐位相同，有测试覆盖。
  - regret 更新和稀疏 compat 仍是单线程，这限制了加速比（实测见 PROJECT_STATE）。
- 一次 CFR 迭代 = 对整个 turn + river 博弈各做一次全宽遍历（玩家 0、玩家 1 交替），然后折扣。turn 的取值通过联合优化的 river 策略回传，没有拼接独立解出的 river 策略。
- 检查点保存全部 turn 和 river 数组；平均策略写到 `average_strategy.npz`，附带 index。

**独立参照**
- 联合序列形式 LP：机会概率显式写进收益矩阵。
- 逐手循环的最佳回应：显式枚举每对手牌的有效河牌。
- 发牌概率的暴力归一化检查。

**对照：拼接法**
- `solve_rivers_with_prior_ranges` 用 turn 开始时的 range 单独求解每个 river 子博弈。
- `frozen_river` 冻结这些 river 策略，只优化 turn。
- 这条路径只用来展示拼接法离均衡有多远。

**规模估算**
- 设置：底池 10bb，四档尺寸加边界动作。表中是 48 张河牌合计的 river 决策节点数，实测于建树代码。

  | 筹码 | turn/river 加注上限 | river 决策节点 |
  |---|---|---|
  | 5bb | 1/1 | 3,360 |
  | 10bb | 1/1 | 13,440 |
  | 20bb | 1/1 | 38,976 |
  | 20bb | 2/2 | 94,848 |
  | 40bb | 2/2 | 326,304 |
  | 100bb | 2/2 | 1,167,936 |

- **下面的内存数字是"当前表示方式及对应配置下的估算"，不是理论下界。**
  - 当前表示方式：每个 river 决策节点、每张河牌、每手、每个动作存一个 regret 和一个累计策略，都是 float64（共 16 字节）；手牌维度保留全部手牌，包括持有该河牌的死手。
  - 估算公式：river 决策节点 × 每方手数 × 约 4 个动作 × 16 字节。稠密后端另加 48 × n0 × n1 × 8 字节 × 4；容斥后端另加约 48 × 63 × n × 8 字节 × 2。
  - 例：40bb、2/2、每方 1,000 手时约 22GB（regret 与累计策略 20.9GB，稠密矩阵 1.5GB）。
  - 全范围 turn（每方 194,580 手），同样的表示方式下：
    - 稠密矩阵合计约 58TB；
    - 换成容斥后端后，regret 与累计策略在 5bb、1/1 时约 42GB，10bb、1/1 约 167GB，100bb、2/2 约 14.5TB。
- **实测**（容斥后端，10bb，加注上限 1/1）：

  | 每方手数 | regret 与累计策略 | 容斥结构 | 进程峰值 | 稠密后端的摊牌矩阵（估算） |
  |---|---|---|---|---|
  | 598 | 331 MiB | 28 MiB | 454 MiB | 约 550 MB |
  | 1,485 × 1,480 | 821 MiB | 69 MiB | 1,029 MiB | 约 3.4 GB |

- **改变表示方式，这些数字也会变。** 例如 float32、去掉死手、压缩或只存必要的 regret、花色同构、牌力抽象、机会节点采样（MCCFR）、depth-limited 加叶节点估值。哪种方式或组合最合适还没有比较，不预先断定只有抽象一条路。
- 稠密后端的上限是 n0·n1 ≤ 250,000（约每方 500 手）；容斥后端没有这个限制，规模受内存和时间约束。

**向全街策略和蓝图扩展的路线**（规划，尚未实现；接口只写在文档里，代码中不放空壳，见 DECISIONS D13）

下一项开发是 flop/preflop 蓝图。拟定的接口：
1. `PublicState`：街、公共牌、下注历史、底池、筹码。由已有的 `public.replay` 生成。
2. `CardAbstraction`：`buckets(street, board, hands) -> 桶编号数组`。
   - 第一版：river 按牌力分位；turn 和 flop 按"河牌牌力分布直方图 + 阻断牌特征"聚类；preflop 用花色同构（16,432 类）。
   - 必须能导出"同一子博弈、无抽象 vs 有抽象"的对照。
3. `BlueprintTrainer`：外部采样 MCCFR（ES-MCCFR），交替更新。
   - `train(iterations, seed, checkpoint_every)`；状态按（街, 公共状态, 桶）索引。
   - 检查点续算逐位一致。
4. `BlueprintPolicy`：`probs(public_state, hand) -> 动作概率`，替换 baseline-v1 的 `own_probs`。
5. `RangeTracker`：按 `BlueprintPolicy` 对公开动作做 Bayes 更新，替换 `posterior_log_weights` 里的 baseline 似然。
6. `SubgameBuilder`：从 `PublicState` 和 `RangeTracker` 生成 turn + river 子博弈。现在这一步在 `turn_agent` 内部完成。

实现任务（按顺序，每项都有验收）：
1. **牌力抽象 v1 + 精确参照**（2026-10-25 已完成第一版，见下文"手牌抽象 v1"）：river 的阻断特征在 3 块牌面上都有效；turn 的特征不如只按胜率，需要重新设计。
   - 本轮发现"按最近 river 牌力复制策略"在参考游戏里误差达 44.9% pot，所以映射规则本身必须先验证。
2. **flop 层**：flop 树 + turn 牌机会节点 + 下层的 turn + river。先在很小的 range 下全宽求解，并与联合序列形式 LP 核对，做法与 turn 相同。
3. **ES-MCCFR 蓝图训练器**（2026-10-25 已有最小版本 v0，见下文"四街蓝图 v0"）：已在小型 PLO 子博弈上用精确信息集对照收敛，并在 20bb、粗抽象下训练整手。下一步是蓝图 v1：嵌套分桶、更多深度和尺寸，以及固定的局部评测集。
4. **接入**：agent 的 preflop 和 flop 改由 `BlueprintPolicy` 决策，turn 起用 turn + river 联合求解，range 来自 `RangeTracker`。
5. **safe/nested 重解**：需要蓝图的反事实值作为对手的替代收益（Libratus 做法）。turn 子博弈正好是"从 turn 解到终局"的单元。

**结论范围**：这个里程碑只代表给定的 turn 子博弈，即给定公共牌、范围、筹码、抽象和加注上限，不代表 flop、preflop 或完整 PLO 的策略质量。

### 联合策略接入决策（`turn_agent.py`，2026-10-25）

- **范围**：HU。翻前、翻牌用 baseline-v1（临时基线）；turn 和 river 用同一个联合解。
- **流程**：
  1. 第一次 turn 决策时，用翻前和翻牌的公开动作做 Bayes 后验。turn 动作不进后验，因为它们是联合博弈内部的动作。
  2. 每方做 `range_samples` 次固定种子的多项抽样，种子与本方底牌无关；本方手牌没被抽到就加进去。
  3. 从 turn 起点求解一个联合 turn + river 博弈，48 张河牌全部枚举。
  4. 沿 turn 树放置对手已经做过的动作，再按联合解里本方手牌的平均策略行动。
  5. 到 river 后，在同一个联合解里查（到达的 turn 叶子, 河牌, 本方手牌）的策略，不重新求解 river。
- **fallback**（全部写入日志）：
  - 对手的 turn 动作不在抽象里：从当前 turn 状态重解联合博弈。range 按前一个联合解在已走路径上的概率加权，下限 eps。
  - 对手的 river 动作不在抽象里：从当前状态做一次独立的 river 重解，range 取联合解沿实际路径的概率。之后这手牌不再按联合策略行动，日志写 `joint_strategy_in_force=false`。
  - 本方手牌不在抽样里：以权重 1 加入，日志写 `own_hand_added`。
- **日志**：每个决策写 `joint_solve_id`、本决策新做的求解（`joint_solves_this_decision`）、`strategy_lookup`（turn 路径、河牌、river 路径、手牌下标）、动作概率、fallback 和延迟。
- `joint_strategy_in_force` 只表示当前仍沿用同一份局部联合策略，不代表安全重解保证，也不是完整 PLO 的 GTO 认证。
- **局限**：range 是抽样的；对手模型固定为 baseline-v1；求解是 unsafe 的；不考虑抽水；要求前注计入 pot limit，或者没有前注。

### 手牌抽象 v1（`abstraction.py`，2026-10-25）

**类型：信息抽象，收益精确。**
- 同一个 bucket 里的手牌共享一组 regret 和一个策略。
- 收益、真实卡牌兼容、blocker 和发牌概率仍逐手精确计算：求解器照常按手牌算反事实值，再按 bucket 汇总 regret。
- 所以每手牌的策略就是它所在 bucket 的策略，解出来的就是原游戏的一个策略组合，可以直接在原参考游戏里用精确最佳回应评估。

**River 特征**（全部按对手在该子博弈里的 range 计算，含卡牌移除）
- eq：对对手 range 的摊牌胜率，即 win 质量 / 兼容质量。
- b_top：对手最强 20%（按权重，按 river 牌力排序）中，仍与本手兼容的比例，除以整个 range 的兼容比例。小于 1 表示本手更多地阻断了对手的强牌。
- b_bot：同样的比例，针对对手最弱的 30%。
- bucket = eq（按本方 range 等质量分成 q_eq 档）× b_top（3 档）× b_bot（2 档）。
- 只看摊牌牌力会丢掉 b_top 和 b_bot：本轮实测，牌力完全相同的手牌在均衡里平均总变差仍有 0.36，所以要按阻断牌把它们分开。

**Turn 特征**（表达不同河牌下的价值变化）
- eq_k：每张河牌 k 下的 eq，持有 k 的手牌除外。
- eq_turn = Σ_k win_k / Σ_k compat_k：按真实发牌概率发出河牌后的胜率。
- spread：各张河牌下 eq_k 的加权标准差，衡量价值随河牌变化的幅度。听牌和容易被反超的成牌大，坚果和空气小。
- b_top：turn 上的阻断比例，对象是对手按 eq_turn 排序的最强 20%。
- turn bucket = eq_turn（q_turn 档）× spread（3 档）× b_top（2 档）。
- 河牌 k 下的 river bucket =（turn bucket, eq_k 档, b_top_k 档），每张牌内重新紧凑编号。

**perfect recall**
- river bucket 细化了 turn bucket，玩家总记得自己的 turn bucket 和自己的动作，所以抽象博弈保持 perfect recall（`perfect_recall_holds` 检查）。单街的 river 抽象天然满足。
- CFR 的收敛保证适用于"收敛到抽象博弈的均衡"。这个均衡在原游戏里有多大可利用度，没有保证，必须测量。

**适用范围与查询**
- 子博弈两方 range 内的手牌都存有 bucket。
- `river_bucket_of_hand` 对任何不与公共牌冲突的合法手牌，用同样的特征和分界给出 bucket（rank 模式除外）。
- 如果某个 bucket 里没有 range 内的手牌，它没有被训练过，策略是均匀的。

**求解器**：`TiedRiverSolver`、`TiedTurnRiverSolver`，通过 `_rows` / `_sigma` / `_update` 钩子接入。钩子的默认实现逐位不变；identity bucket 能逐位复现不抽象的求解器。抽象求解暂不支持检查点。

### 四街蓝图 v0（`blueprint.py`、`blueprint_agent.py`，2026-10-25）

**博弈**
- HU，盲注 50/100，有效筹码 20bb。
- 动作：
  - 翻前小盲先行动：fold、call、加注到 pot。大盲面对 limp 时可以 check 或 raise（`PreflopTree`）。翻前最多 2 次加注。
  - 翻后：下注 1/2、1 pot，加注 1 pot，每街最多 1 次加注，另含 pot 尺寸或短码 all-in。
- 一街结束后接下一街，底池为 pot + 2 × 本街投入；有人 all-in 或 river 结束时摊牌。
- 规模：18 棵街树，决策节点依次为 6 / 28 / 52 / 66（翻前 / 翻牌 / turn / river）。

**抽象**（粗）
- 翻前：16 个 preflop 强度分位。
- 翻牌和 turn：棋面相对强度 8 档 × 同花听牌 × 坚果同花阻断。
- river：12 档 × 坚果同花阻断。
- "棋面相对强度"是本手最佳 2+3 牌力在该棋面全部存活两张组合中的分位，每块牌面一张表，同时用于分桶和摊牌比较。
- 每街独立计算 bucket，玩家可能忘记前一街的 bucket，所以**不保持 perfect recall**，MCCFR 的收敛保证不适用。

**训练**
- 外部采样 MCCFR，交替更新；regret 和平均策略线性加权，平均策略在对手节点累计。
- 每次迭代采样一次发牌：两手牌加 5 张公共牌，可以按 range 发。
- 检查点续算逐位一致。

**验证**
- 用 identity bucket（精确信息集）在两个已有 LP 参照的小子博弈上跑：river 8 × 8 手，turn + river 6 × 6 手。
- 训练出的表映射到全宽精确求解器的同一节点编号，用精确最佳回应评估。
- 树与精确 turn 求解器的树逐节点相同（有测试）。

**查询与 agent**
- `BlueprintPolicy` 把公开历史映射到树路径，树外尺寸取最近的同类尺寸并记录；用当前街的 bucket 取平均策略。
- `coarse_hand_buckets` 把分桶向量化，所以蓝图也能给 Bayes range 提供似然（RangeTracker 的雏形）。
- agent：
  - `blueprint_v0` 四街都用蓝图；
  - `turn_river_solver` 带 `early_policy=<检查点>` 时，翻前、翻牌的决策和 turn 起始的 range 模型都改用蓝图，turn 和 river 仍由联合求解决定。

**与精确求解器的关系**：turn + river 精确求解器继续作为参照和搜索组件。蓝图从 turn 起提供 range，联合求解在这个 range 上做局部的 unsafe 求解。

## 许可清单与分发边界

| 部件 | 许可 | 当前用途 |
|---|---|---|
| postflop-solver / Wataru Inariba | AGPL-3.0-or-later，原 LICENSE 保留 | 本地研究引擎 |
| serde / serde_json | MIT OR Apache-2.0 | JSON |
| regex / once_cell 等 | 版本见 Cargo.lock，各自上游许可 | 传递依赖 |
| SciPy / NumPy | BSD 系列 | 独立验算及旧分析 |
| psutil | BSD-3-Clause | 资源检测 |
| Playwright | Apache-2.0 | 可选浏览器测试 |

完整分发依赖清单尚未完成，本轮没有分发操作。独立进程边界不自动赋予闭源商业授权；将来商业化需另行解决引擎许可或替代实现，保留第三方声明。旧阶段 0 架构在 archive，仅供背景；当前实现边界以本文与 PROGRESS 为准。
