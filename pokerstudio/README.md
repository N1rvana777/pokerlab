# Pokerstudio

本机中文扑克 vlog 剪辑工作台。原 Pokerlab solver 的运行方式保留。实际结果见 [验收](docs/ACCEPTANCE.md)、[进度](docs/PROGRESS.md)。

## 启动

Windows PowerShell：

```powershell
Set-Location C:\Users\n1rva\projects\pokerlab
python -m pip install -r pokerstudio/requirements.txt
python -X utf8 -m pokerstudio.server
```

打开 http://127.0.0.1:8770 ，或使用 `pokerstudio/start.ps1`。端口占用加 `--port 8771`；可用 `--data-dir D:\PokerstudioData` 更换数据目录。Ctrl+C 取消任务并回收进程。

桌面快捷方式安装命令（本轮正在实现，真实安装和独立窗口尚未验收）：

```powershell
powershell -ExecutionPolicy Bypass -File pokerstudio/install-desktop.ps1
```

安装目标是 Windows 当前用户的真实桌面，本机为 OneDrive Desktop。两个快捷方式分别为 `Pokerstudio.lnk` 和 `Pokerlab Solver.lnk`；双击隐藏启动本地后台，打开 Edge 独立应用窗口。关闭窗口保留后台和任务，重开复用服务。端口分别为8770和8765；端口被其他程序占用时报告错误，不终止该程序。安装路径、日志、显式停止后台和验收状态见 [桌面启动](docs/DESKTOP.md)。

本机：Python 3.12.10、Pillow 12.1.1、cryptography 46.0.5、psutil 7.2.2、Codex CLI 0.162.0、FFmpeg/FFprobe 9.0.2。媒体工具依次从 `POKERSTUDIO_FFMPEG`/`POKERSTUDIO_FFPROBE`、PATH、`.tools/` 自动发现，见 [媒体配置](docs/MEDIA.md)。真实求解需要现有 Pokerlab Python 包及 WSL 引擎，按根 README 构建。

## 操作流程

1. 新建项目，完整路径导入多个视频，或选择文件复制到应用目录。自动读取时长、分辨率、帧率与音轨。没有短素材时生成明确 TEST 标识的合成视频与 440Hz 音轨。
2. 按**项目秒**定位，选中片段后按**素材秒**设置入/出点，切分、重排、移除。原文件保持完整。按需流媒体、缩略图缓存；不兼容格式可生成 960×540 代理，导出仍用原文件。
3. 标记手牌范围，编辑玩家/位置、盲注、筹码、底池、底牌、公共牌、范围、行动、行动后底池和发牌锚点。未知牌/金额留空或 `?`，不强行补齐。
4. 编辑字幕或导入 SRT，添加说明叠加。讲稿可人工编辑或由助手按真实手牌/报告起草。暂停、播放叠加和导出共用项目时间计划。
5. 导出面板设置尺寸/帧率、字幕/叠加，实际输出 H.264/AAC MP4。查看进度、错误、取消和文件位置；成功后播放/下载。当前保留第一音轨，无音轨片段补静音。

重要编辑自动保存，最近100步可撤销/恢复。重开恢复当前状态和播放位置，撤销栈不跨重启。普通片段重排不会猜测并移动手牌标记，应检查其范围。源素材转写按片段入出点和排列转换为项目秒；SRT 按当前项目秒解释。

项目 JSON 引用媒体路径，不包含原视频。路径失效时仍可打开并重新定位，另存到已有其他文件拒绝覆盖。项目、缓存、代理、导出、导入副本、会话默认位于 `.data/` 并忽略；启动恢复最后项目，迁移要保留原素材。

## 分析与 Agent

“分析当前手牌”严格检查两人、整数筹码、公共牌、OOP/IP 范围和街开始根状态。缺数据/不支持场景如实拒绝；可以输入与手牌一致的完整配置，结果保留假设与测得精度，计算字段改变标记过期。[Solver](docs/SOLVER.md)。

http://127.0.0.1:8770/analysis 为独立分析入口：载入明确样例或完整配置后保存、求解或让助手调用。原8765工作台也有链接。分析会话不能修改/导出剪辑项目。

订阅默认正式 Sign in with ChatGPT 独立登录，首次需本人授权。本机可明确选择现有 Codex 登录，通过正式 app-server 使用认证，不提取 token、不改日常配置。真实验收使用 existing_cli + gpt-6.1-sol 修改项目和调用 solver；独立 SIWC/managed 尚需首次本人登录。候选和历史成功不保证未来权限。[Agent](docs/AGENT.md)。

API 模式自行填写 OpenAI key/模型并明确开启付费；key 仅在后端内存，重启重填。未配置/授权不收费调用，订阅限额不自动回退 API。可要求“改底池120”“缩短字幕”“裁切标记手牌”“求解并解释假设”“按时间线导出”；实际业务操作自动保存、可撤销，取消后等待终态。

## 当前边界

独立分析配置 `.data/analysis.json`，项目 `.data/projects/`，agent 会话和应用模式分开保存。应用 OAuth 使用自己的认证目录和 DPAPI；不作为 API key。

本机已通过本地CPU转写：在“本地转写与媒体能力”填写 `C:\Users\n1rva\projects\pokerlab\pokerstudio\.data\models\faster-whisper-tiny`，选择素材并转写，完成后按时间线导入字幕。新环境可选安装 `pip install -r pokerstudio/requirements-transcribe.txt`，另配置本地模型；不自动下载或收费。tiny模型文字/时间需人工检查，不能自动补牌局金额。缺依赖/模型如实提示。

首版用短合成素材验收，长真实扑克录像仍需验证。未实现自动识牌、手机同步、AI封面/云配音、独立口播/BGM轨、定格、SRT自动手牌锚点、多人数solver或远程共享个人订阅。见 [视频依据](docs/VIDEO_WORKFLOW.md)、[架构](docs/ARCHITECTURE.md)。
