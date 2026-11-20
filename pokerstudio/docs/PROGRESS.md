# Pokerstudio 实际进度

更新时间：2026-10-08。完整任务来源：本会话用户粘贴的持续任务。

## 当前目标

在现有 Pokerlab 内完成本地可运行的首版剪辑应用：多素材、非破坏剪辑、手牌时间标记、动态叠加、字幕/SRT、真实 MP4 导出、真实 solver 与可操作业务工具的订阅/API 双模式 agent。验收以真实文件、实际计算、实际导出和真实认证请求为准。

## 执行计划与分工

1. 根代理：覆盖参考视频 00:00–07:26、证据文档、项目状态/HTTP 服务/中文界面、集成与浏览器验收。
2. media_backend：媒体探测、字幕、共享渲染计划、后台任务、FFmpeg 导出/取消与测试素材。
3. solver_adapter：现有 Workbench 接口勘察、结构化手牌映射、真实小型求解与数值检查。
4. agent_integration：核实本机 Codex app-server 协议与官方文档，双 provider、工具调用、会话/流式/取消、真实认证验证。
5. 集成：保存重开、两片段编辑、手牌/字幕/叠加、solver、导出与开始/中间/结尾帧、agent 实际操作。

## 已确认

- 读取根 AGENTS.md、最新 solver 需求、现有进度和架构。现有工作台入口为 `python -m pokerlab.solver.server`，127.0.0.1:8765。
- 当前目录没有 `.git`；`git status --short` 返回 `fatal: not a git repository`。不初始化、不重置、不清理现有工作。
- 参考视频 00:00–07:26 已按 15 秒基线实际抽帧，软件段按 2–3 秒加密；接触表与多个原尺寸关键画面已实际查看。不是逐帧检查。证据保存在 `.data/reference/frames/`。
- 沿用已修复的 Playwright Firefox；不安装或升级浏览器。
- 官方 App Server 与 SIWC 起点已经搜索并打开；CLI 0.162.0 实际 schema 已生成并使用，完整运行证据在忽略目录 `.data/protocol-schema/`。

## 关键决定

- 首版采用 Python 本地后端加浏览器界面，主要代码/测试/文档放 `pokerstudio/`；保留 solver 现有运行方式。
- 原始媒体、缓存、项目、导出与应用凭据不纳入源码。具体路径随实现记录。
- Agent 只通过经验证的业务工具改项目；工具结果与真实状态一致。订阅与 API 不自动互换。
- 没有用户配置/授权时，不发起收费 API 调用；模型候选不代表真实请求可用。

## 已完成的实现与实测

- VIDEO_WORKFLOW.md、ARCHITECTURE.md、README、AGENT.md、MEDIA.md、SOLVER.md及ACCEPTANCE.md已完成。77张参考截图（含一张偏时重载图），官方字幕为0；后续本地CPU转写成功，256段0–446.64秒，未人工听校。
- `project.py`/`tools.py`/`server.py` 与中文 web 界面已联调。2 个真实合成素材、3 个剪切/重排片段、10秒时间线、手牌/行动/发牌锚点、SRT/说明叠加、保存切换后重开保持一致。
- 最终相关回归：75 passed、3 skipped，4.90秒（转写依赖修复后重跑；原生测试须显式启用）；另行实际运行的3项原生测试通过，4项真实媒体测试通过。播放位置不占撤销、审计保留、项目切换竞态、Windows端口独占及客户端断开处理均已通过。
- 真实原生适配器 3 项通过（5.70s）：River 均衡 EV 13.3332891464 对独立 LP 13.3333333333，误差 4.41869e-5；固定对手 BR 与取消/回收通过。证据在 `pokerstudio/data/solver_acceptance_*.json`。
- 本人 existing_cli 真实订阅与 gpt-6.1-sol 验收通过：项目底池120/字幕保存重开；独立分析 agent 调用真实求解/报告。最新隔离后证据 `.data/agent-acceptance/1791503042/acceptance.json` passed=true，进程及两入口外部 MCP 工具数为0。浏览器自然语言请求也通过：手牌标题与第一条字幕真实修改、界面显示、source=agent 审计。
- FFmpeg/FFprobe 9.0.2 已授权下载到 `.tools/ffmpeg/ffmpeg-9.0.2-essentials_build/bin/`。媒体模块已经生成可播放 8秒 H.264/AAC TEST 原素材。
- 三处暂停合成预览已实际打开查看，公共牌3/4/5张、底池20/30/42、字幕随时间变化，实时播放跨片段与素材边界通过。花色改用几何绘制，真实成片无方框。
- 浏览器编辑项目真实导出完成：10.005333秒、1280×720、30fps、H.264、AAC 48kHz双声道。文件 `.data/exports/73505b1236874fb9b9ecd7dec28853c1-1791503450-7685de4e.mp4`。浏览器打开并定位0.5/5.5/9.5秒成功，实际查看对应完整导出帧；来源时间3.5/0.5/2.5秒与片段重排相符。
- `.data/acceptance/browser-export/verification.json` passed=true：三帧与共享预览的像素平均绝对误差2.086/2.023/2.112（0–255），测试音轨频谱主峰440Hz。没有把测试音轨验证当成真人语音同步验收。
- 已修复项目切换期间导入/求解绑定竞态，编辑、撤销、上传均传项目ID并在锁内校验。app-server 显式禁用继承的外部MCP；应用模式/历史验证摘要持久化，API key及付费授权不持久化。

## 验收完成与剩余配置/素材范围

- A/B/C/D 与 existing_cli E 已通过，详见 ACCEPTANCE.md。浏览器导出取消与agent取消均为“已取消”；已有街内行动的自动求解被真实工具拒绝，agent最终为“失败”并显示原因。未配置API的发送请求明确失败，没有收费请求或provider回退。
- 独立分析页面自然语言真实求解已完成，报告5779e3403f4a4e729c56c16998248225，EV和精度与原生样例一致，基线缓存命中。最终分析面板只显示求解/节点查询；analysis-final.png 与 studio-final.png 均实际查看。
- 参考音轨取得成功：446.901秒Opus、48kHz双声道，.data/reference/audio/reference.webm。首次沙箱代理WinError10061，正常审批权限重试成功。faster-whisper1.2.1+本地tiny模型转写256段、19.344秒。PyAV19参数不兼容已修复为18.1.0，并保存可选依赖文件。原先 needs_dependency 是早期真实失败，后续已完成转写。
- 浏览器转写接口及字幕映射实际通过：8秒TEST-ASR素材生成4条素材秒字幕，导入后项目秒0–8，项目d220dbfe5c2e48e3b8bff2694d117236。另一次实际取消终态cancelled。模型词句仍有误识别，需人工编辑。没有自动将机器结果转成牌局金额。
- existing_cli 订阅已接通；独立 SIWC/managed 尚未本人首次登录。API 真实调用等待凭据与明确付费授权，未调用。本地模型已可用，但真实扑克长录像、复杂音轨/VFR/HDR仍未实测。
- 最后修复新项目残留旧聊天：项目ID变化且助手空闲时清空旧聊天/事件/状态；运行中的旧请求保留真实状态，后台项目作用域检查始终有效。静态语法与实际项目切换检查通过。
- 当前服务已加载全部修复，http://127.0.0.1:8770，exec session 15528；项目 `.data/projects/73505b1236874fb9b9ecd7dec28853c1.pokerstudio.json`。

## 恢复后直接执行

本轮A–E首版验收完成，真实API/独立SIWC登录按未配置明确标记。若服务已经停止，从仓库根目录运行 `python -X utf8 -m pokerstudio.server`；无需重新下载FFmpeg或Firefox。打开保存的浏览器验收项目继续操作，转写时填写 `.data/models/faster-whisper-tiny` 的完整路径。个人后续步骤为独立SIWC首次授权、需要时配置API并明确付费，以及提供真实扑克短素材验证效果。未来功能/商业分发没有冒充本轮实现。

## 后续桌面启动任务（进行中）

- 新需求：在当前用户真实桌面创建 Pokerstudio 与 Pokerlab Solver 快捷方式；双击隐藏启动后台并打开无地址栏的独立窗口。保留现有命令行入口和 Solver 核心。
- 约定安装脚本 `pokerstudio/install-desktop.ps1` 默认解析 Windows 当前用户桌面（本机 OneDrive Desktop），支持 `-DesktopPath` 测试目录。目标固定本机 `pythonw -X utf8 -m pokerstudio.desktop --app pokerstudio/pokerlab`，工作目录为项目根。
- 约定 Edge `--app` 窗口、8770/8765 两个默认端口、自有后台登记与重复启动保护。关闭窗口保留服务和任务；同应用服务复用，陌生端口占用报告错误。`--stop` 只停止桌面启动器自己启动的服务；旧手动服务仍用 Ctrl+C。
- 只读勘察确认现有 Solver 没有 HTTP 健康/关停接口；首页及 `/api/examples` 可识别应用，正常退出经 `jobs.close()` 取消所属任务并等待回收。检查时8765为 `WinError 10061`，未对服务作变更。
- 基础说明已加入两份 README 与 [DESKTOP.md](DESKTOP.md)。快捷方式真实安装、独立窗口、连续双击、关闭重开、端口冲突与自有后台关停尚未验收，不能把已有浏览器工作台验收视为桌面启动验收。
