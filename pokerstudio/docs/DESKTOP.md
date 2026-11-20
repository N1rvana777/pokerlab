# Windows 桌面启动

本轮状态：桌面启动器与安装脚本正在实现。真实桌面安装、双击、无地址栏窗口、重复启动和后台关停尚未验收。下面说明本轮约定的使用方式；实际验证结果补充在本文件末尾。

## 安装快捷方式

在项目根目录运行一次：

```powershell
Set-Location C:\Users\n1rva\projects\pokerlab
powershell -ExecutionPolicy Bypass -File pokerstudio/install-desktop.ps1
```

默认使用 Windows 返回的当前用户真实桌面位置，兼容桌面重定向；本机为 OneDrive Desktop。创建 `Pokerstudio.lnk` 和 `Pokerlab Solver.lnk`。测试时可以指定独立目录，不向真实桌面写入测试快捷方式：

```powershell
powershell -ExecutionPolicy Bypass -File pokerstudio/install-desktop.ps1 -DesktopPath C:\Users\n1rva\projects\pokerlab\pokerstudio\.data\desktop-test
```

快捷方式固定本机 Python 的 `pythonw.exe`，工作目录为 `C:\Users\n1rva\projects\pokerlab`；参数分别为 `-X utf8 -m pokerstudio.desktop --app pokerstudio` 与 `-X utf8 -m pokerstudio.desktop --app pokerlab`。迁移项目或更换 Python 路径后需重新生成快捷方式。它们使用现有应用、媒体依赖和 Solver 引擎，不执行安装依赖、修改日常 Codex 配置或启动求解。

## 双击与关闭窗口

双击 Pokerstudio 打开剪辑工作台，默认服务地址 `http://127.0.0.1:8770`；双击 Pokerlab Solver 打开原 Solver 工作台，默认 `http://127.0.0.1:8765`。启动器隐藏运行后台，等待应用就绪后使用本机 Edge 的 `--app` 模式打开独立窗口，不显示普通浏览器地址栏或控制台。

已运行的同一应用服务可以复用。重复双击不应重复启动后台服务；若对应端口被其他应用占用，报告错误并保留该占用进程。窗口与后台生命周期分开：关闭应用窗口保留服务、导出和计算任务，再次双击可以连接同一后台。

应用窗口使用独立浏览器配置目录 `pokerstudio/.data/desktop/profiles/`；后台与启动器日志位于 `pokerstudio/.data/desktop/logs/`。这些目录属于本地运行数据，不纳入源码。原始项目、导出和 Solver 研究文件沿用既有存储位置。

## 显式停止后台

需要停止由桌面启动器启动的后台时，在项目根目录运行对应命令：

```powershell
python -X utf8 -m pokerstudio.desktop --app pokerstudio --stop
python -X utf8 -m pokerstudio.desktop --app pokerlab --stop
```

`--stop` 只关闭启动器自己启动并登记的服务，不能关闭陌生进程或此前手动启动的服务。后台停止要经过应用的正常清理流程，取消所属任务并等待进程回收。手动运行 `python -m pokerlab.solver.server` 或 `python -m pokerstudio.server` 的旧服务仍在原终端用 Ctrl+C 停止。

## 出错时

若双击未打开窗口，先检查 `.data/desktop/logs/` 中的最新日志，再使用既有命令行入口查看错误。Python 或项目路径失效时重新生成快捷方式；Edge 缺失时需要安装或恢复本机 Edge。端口被其他程序占用时，先确认占用来源；启动器不负责终止该程序。网页服务就绪只说明连接可用，不能代替导出、求解或 Agent 认证验证。

## 验收状态

- 本机 Python 3.12.10 可导入现有 Solver，项目根路径已确认。
- 本轮只读检查时8765连接被拒绝（`WinError 10061`）；该检查没有启动或停止服务。
- 安装脚本默认桌面解析、两个快捷方式的目标/参数/工作目录：尚未验收。
- 从两个快捷方式启动并打开真实独立窗口、地址栏和控制台隐藏：尚未验收。
- 连续双击仅一个后台、关闭窗口后服务保留、重开复用：尚未验收。
- 错占端口拒绝、显式停止仅作用于自有后台、正常取消及进程回收：尚未验收。
