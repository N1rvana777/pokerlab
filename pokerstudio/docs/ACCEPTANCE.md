# Pokerstudio 首版真实验收

日期：2026-10-08。本记录区分实际浏览器操作、真实文件/计算和单元测试。合成素材与手牌均明确标记 TEST ONLY；没有将它们当作真实扑克录像。

## A：启动

仓库根目录的 Windows PowerShell：

```powershell
Set-Location C:\Users\n1rva\projects\pokerlab
python -m pip install -r pokerstudio/requirements.txt
python -X utf8 -m pokerstudio.server
```

也可运行 `pokerstudio/start.ps1`。剪辑入口为 http://127.0.0.1:8770 ，独立分析入口为 http://127.0.0.1:8770/analysis 。本轮已启动、停止、重启，并恢复已保存项目/播放位置、分析配置与助手会话。

本机环境：Python 3.12.10、Codex CLI 0.162.0、FFmpeg/FFprobe 9.0.2。现有 Pokerlab/WSL 原生引擎保持原入口，未迁移或升级。Firefox 使用此前工作的 MCP 环境，未重新安装。

实际发现并修复 Windows 双实例同端口问题：现在独占绑定。启动第二个实例返回退出码1及 `WinError 10048`，提示使用 `--port 8771`，第一个实例继续工作。客户端刷新/离开产生的 `WinError 10053` 不再尝试向已断开的连接发送第二次错误响应。相关真实监听回归通过。

## B：剪辑、标注与保存

实际在 Firefox 中生成并导入两个8秒 H.264/AAC 合成视频，探测到960×540、30fps及音轨。项目为 `TEST ONLY - 浏览器剪辑验收`：

- 项目文件：`.data/projects/73505b1236874fb9b9ecd7dec28853c1.pokerstudio.json`。
- 素材A：`.data/demo/TEST-f995046a.mp4`；素材B：`.data/demo/TEST-13c75a41.mp4`。
- 浏览器切分、后移、调整入出点后的顺序：A素材3–8秒 → A素材0–3秒 → B素材1–3秒；项目总时长10秒。
- 编辑一手牌、两名玩家、未知对手底牌、行动、发牌锚点、三条SRT字幕和说明叠加。公共牌按项目时间逐步显示3/4/5张，底池按确认记录显示20/30/42。
- 保存后新建空白项目，再打开原项目，片段、手牌、字幕、叠加保持一致。服务重启后项目及播放位置也恢复。
- 实际播放跨片段和跨素材边界；暂停合成预览与播放透明叠加均可见。原素材没有覆盖、剪写或重新编码。

编辑自动原子保存，撤销/恢复和审计通过测试；撤销栈不跨重启。异步媒体探测、求解与旧 agent 请求不能在切换项目后修改新项目。缩略图按需缓存、Range流读取和代理接口已实现；长真实录像性能尚未验收。

最终界面截图 `.data/acceptance/studio-final.png` 已实际打开查看，能够读到中文控制、三个片段及9.5秒的动态叠加。

## C：真实成片

浏览器导出任务 `2181474eff4f44918725cc15aa43d985` 成功，输出：

`.data/exports/73505b1236874fb9b9ecd7dec28853c1-1791503450-7685de4e.mp4`

FFprobe 实测：10.005333秒、1280×720、30fps、H.264，AAC 48kHz双声道，2,168,466字节。浏览器实际打开该文件，定位0.5、5.5、9.5秒，视频帧解码成功。首次打开原生视频文档曾触发 MCP 的60秒 DOMContentLoaded 超时；随后视频元素正常播放/定位，不能把这一工具等待超时解释为视频解码失败。

另外解码并实际查看三张完整1280×720导出帧：

- `.data/acceptance/browser-export/export-1.png`：项目0.5秒对应A素材3.5秒，三张公共牌、底池20和第一条字幕。
- `export-2.png`：项目5.5秒对应A素材0.5秒，四张公共牌、下注10、底池30和第二条字幕。
- `export-3.png`：项目9.5秒对应B素材2.5秒，五张公共牌、下注12、底池42和第三条字幕。

同时间共享预览 `preview-1/2/3.png` 与成片的像素平均绝对误差为2.086、2.023、2.112（0–255，编码容差10）。中文、彩色花色、未知牌 `?` 与说明文字正常。解码1秒音轨，48,000个采样，频谱主峰440Hz，确认测试音轨保留。此项不是对真人讲解、口型或多音轨混音的验收。

`.data/acceptance/browser-export/verification.json` 的 `passed=true`。其中 `visual_review` 是自动验证器提醒，图片实际查看情况以本记录为准。复核命令：

```powershell
python -X utf8 -m pokerstudio.verify_export --project pokerstudio/.data/projects/73505b1236874fb9b9ecd7dec28853c1.pokerstudio.json --video pokerstudio/.data/exports/73505b1236874fb9b9ecd7dec28853c1-1791503450-7685de4e.mp4 --output pokerstudio/.data/acceptance/browser-export
```

浏览器另启动导出 `3be2566d8efe4fb78257b27417b06f64` 并点击取消，终态为“已取消 / 媒体任务已取消”，未显示成功文件。真实媒体测试也检查取消后进程回收、编码失败不发布、源文件哈希保持不变。较早的5秒专项成片在 `.data/acceptance/media-2095a4a6/TEST-export.mp4`。

## D：真实 Solver

适配器调用现有 `pokerlab.solver.server.Jobs` 与 WSL 监督进程，保留跨进程串行锁、内存预算、超时、取消/进程回收。结构化手牌自动映射要求两人、整数筹码、街开始OOP根、明确范围；完整配置可使用现有对手特质、Node Lock、尺寸等功能，未扩展引擎。

已知 River 样例：`2c 3d 7h 8s 9c`，OOP `AsAh,QhJh` 对 IP `KsKh,TcTd`，底池20，有效剩余筹码30，下注10，无加注。真实均衡根EV为13.3332891464 / 6.6667108536；独立 LP 的OOP EV为13.3333333333，差4.41869e-5筹码。测得 exploitability 0.00932455063筹码，即底池0.0466227531%，该小型样例530次迭代达到0.05%目标。这不证明其他大树达到精度目标。

固定对手 BR 专项也真实通过，并经独立 sum-product 重评；不将 response gap 写成均衡 exploitability。证据在 `data/solver_acceptance_equilibrium.json`、`data/solver_acceptance_fixed.json`。

浏览器“分析当前手牌”完成了自动映射样例；之后添加当前街行动时，旧报告标记过期，直接自动求解明确拒绝。独立分析页面的真实按钮和自然语言 agent 均成功求解/读报告。最新 agent 浏览器报告 ID `5779e3403f4a4e729c56c16998248225`，记录基线缓存命中，不能称为新的冷启动均衡计算。`.data/acceptance/analysis-final.png` 已实际查看；分析任务面板仅显示求解/节点查询。

## E：真实 Agent 与两种模式

本人 `existing_cli` 模式通过正式 account/read 使用现有 ChatGPT Pro 登录，模型 `gpt-6.1-sol` 已通过真实请求。没有读取或复制日常 auth.json、cookie/token，没有修改日常全局配置。app-server 启动/会话检查外部 MCP 工具数均为0，只暴露当前入口的业务工具。

- 实际浏览器自然语言请求调用 read_project、update_hand、update_subtitle，再回读核验。手牌标题改成 `TEST ONLY - Agent已更新`，第一条字幕改为 `Flop测试`，保留0–3秒范围及原牌局字段；界面与保存项目一致，审计来源为agent，支持撤销。
- 独立分析浏览器请求调用 read_project、solve_hand、get_task、get_solver_result，界面显示真实结果、精度和假设，未改剪辑项目。会话 `a1efcfe059944a9ea82dfead2875c712` 可在该入口恢复。
- 隔离后的真实脚本验收 `.data/agent-acceptance/1791503042/acceptance.json` 为 `passed=true`：项目底池120/字幕真实修改并保存重开；独立分析真实求解；两入口均记录外部MCP工具数0。这是另一个TEST项目，不是导出样例的底池记录。
- 浏览器取消请求终态“已取消”。直接分析已有当前街行动的手牌，真实工具拒绝；最终显示“失败”，原因：`当前街已经发生行动，无法自动映射为街开始 OOP 根；请单独填写并确认分析配置`，未伪造EV或成功。
- API模式没有配置凭据或授权付费。实际点击发送后终态“失败”，提示：`API 模式尚未配置或尚未授权付费调用；不会改用订阅或发起计费请求。` 没有发起收费请求，因此正式API接通仍尚未真实验证。
- 默认独立SIWC与隔离managed登录代码已实现，首次正式授权仍需本人；本轮没有将协议/认证单元测试写成已完成本人登录。切换/配置步骤见 `AGENT.md`。

## 回归与剩余限制

最终执行：

```powershell
python -m pytest pokerstudio/tests tests/test_solver_reference.py tests/test_workbench_api.py -q
```

结果 **75 passed，3 skipped，4.90秒**（转写依赖与兼容修复后的最终重跑）。3个 skipped 是显式启用的原生专项；它们已另行真实运行并通过（5.70秒）。4项真实媒体测试包含在回归中。JavaScript语法检查通过。单元/mock协议测试用于检查契约，不作为订阅/API真实接通证据。

早期本地转写真实任务缺依赖失败：`RuntimeError: needs_dependency: 未安装 faster-whisper；请使用SRT或手工字幕。安装是独立可选步骤`，没有误报成功。后续安装本地依赖/tiny模型并修复PyAV兼容错误后，完整参考音轨真实转写完成：256段、0–446.64秒、19.344秒，摘要 `.data/reference/audio/asr/summary.json`。模型词句仍有错误，没有人工听校，不能据此自动补填牌局数值。

实际浏览器8秒转写接口验收：`media:6d780d61e5c64299907528df06901211` completed，返回4条 `source_media_seconds` 字幕；点击按时间线导入后项目中实际保存4条、范围0–8秒。测试项目 `.data/projects/d220dbfe5c2e48e3b8bff2694d117236.pokerstudio.json`，界面截图 `.data/acceptance/asr-ui.png` 已实际查看。再启动并取消转写 `media:01a61637ef2044f381e40a1cb1ab1181`，终态已取消。手工字幕/SRT/烧录与本地CPU转写均可用，不使用收费服务或应用隐式下载。

参考视频视觉证据覆盖00:00–07:26，15秒基线、软件段2–3秒加密及原尺寸关键图实际查看，详细范围见 `VIDEO_WORKFLOW.md`；官方字幕条目为0，后续本地音频机器转写256段。官方字幕、画面烧录字幕与机器转写分别记录。

真实扑克短素材、长录像/VFR/HDR/旋转/复杂多音轨尚待素材验收。自动识牌、手机同步、AI封面/云配音、独立口播/BGM轨、定格与自动SRT手牌锚点未实现。多人solver不在本首版适配范围。不把参考视频按钮或作者介绍当成已验证能力。
