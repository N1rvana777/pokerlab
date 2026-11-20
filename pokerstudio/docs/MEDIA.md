# 媒体处理、字幕与真实验收

Pokerstudio 使用本机 FFmpeg/FFprobe、Python Pillow。原视频按需读取，项目只保存片段入出点与标注；不把完整长视频读入 Python 内存。测试素材明确印有 `TEST / 合成验收素材`，不是真实牌局。

## 依赖与运行

已下载的 Windows 构建：`pokerstudio/.tools/ffmpeg/ffmpeg-9.0.2-essentials_build/bin/`，包括 FFmpeg 9.0.2 与 FFprobe。自动先检测 `POKERSTUDIO_FFMPEG` / `POKERSTUDIO_FFPROBE`，再检测 PATH，最后递归查找 `.tools`。可把环境变量指向用户已有可执行文件，无需改变系统 PATH。Pillow 通过 `pokerstudio/requirements.txt` 安装。

CPU 路径使用 `libx264` / `yuv420p` / AAC、48kHz 双声道，输出 MP4 `faststart`。没有自动选择 GPU 编码；目前无需独立云 API。画面归一化到项目 `export_settings` 的宽高与帧率，默认 1280×720 / 30fps，保留宽高比并补黑边。无音轨素材生成静音轨，有音轨素材使用第一条音轨。

## 共享时间与画面计划

`render_plan(project)` 将按列表排列的 `clips`（`asset_id,in,out`，素材秒）映射为连续项目秒。手牌、字幕、说明文字及行动、发公共牌均使用项目秒。`preview_frame` 合成实际素材帧，`overlay_frame` 提供同尺寸透明 PNG，`export_project` 使用完全相同的 `overlay_image` 与事件边界，不另写一套牌谱或字幕。

- `hand.board_reveal:[{time,cards}]` 精确指定公共牌事件；未到首个事件时不显示公共牌。
- 缺发牌事件但有行动时，按最近行动的 `street` 显示 0 / 3 / 4 / 5 张，并明确标注“按行动街道”。两者均无时显示“静态记录”。这不是自动牌张识别。
- 底池仅用手工确认的 `hand.pot` 与最近已发生行动的 `pot_after`；不会推算不完整行动的底池。未知牌显示 `?`，未知底池显示“未知”。
- 每位玩家显示已确认底牌与最近行动。花色使用 Pillow 几何绘制，避免中文字体缺少 ♠♥♦♣ 字形。
- `export_settings.subtitles/overlays` 及条目的 `enabled`、手牌的 `overlay_enabled` 控制预览与导出；结束边界使用 `[start,end)`。
- 中文默认字体为 `C:/Windows/Fonts/msyh.ttc`，可用 `POKERSTUDIO_FONT` 指定字体。字幕太长时最多四行，并以省略号提示裁切；请编辑为更短字幕后导出。

导出先串行精确裁切并统一每个片段的画面和音频，再拼接并烧录 PNG 事件流。当前是两次 CPU 编码，优先可靠；长视频性能尚未实测。代理生成是独立后台任务，960×540 / 30fps，原素材保持完整。缓存与任务中间文件在 `.data`，不会进版本管理。

## 任务、取消与发布

媒体任务串行运行，状态为 `queued/running/completed/failed/cancelled`，进度 0–1，记录最近日志与真实错误。取消先设置事件，由进程监督循环结束 FFmpeg 进程组，随后 `wait` 回收；失败／取消不返回成功。FFmpeg 错误保留退出码和 stderr 尾部。任务 shutdown 请求取消并等待。

导出只在编码完成、FFprobe 检查时长／分辨率／音轨通过后，把同目录临时文件原子移动到新的结果路径；拒绝覆盖已有导出。关闭或异常取消会清理该任务私有临时目录。取消请求与终态可有短暂间隔，界面必须继续查询。

## 字幕与转写

SRT 导入支持 UTF-8 BOM、CRLF、标准 `HH:MM:SS,mmm`，校验分钟／秒／正时长。SRT 导出保持文本和项目时间，忽略禁用条目。

`transcribe_local(source,model_path,task)` 为可选的 CPU `faster-whisper` 接口，仅接受已存在的本地模型目录、`local_files_only=True`，不自动下载模型，不访问收费媒体服务。缺依赖/模型返回明确 `needs_dependency` 或 `needs_model`。当前机器已安装并真实验证 faster-whisper1.2.1 + PyAV18.1.0，tiny模型位于 `.data/models/faster-whisper-tiny`。界面“本地转写与媒体能力”中填写模型目录完整路径并选择素材，完成后点击“按时间线导入转写字幕”。文字和时间须人工检查。

新环境的可选依赖：`pip install -r pokerstudio/requirements-transcribe.txt`。PyAV19删除了 faster-whisper1.2.1使用的 metadata_errors 参数，实际出现 `TypeError: open() got an unexpected keyword argument 'metadata_errors'`；固定 av<19 后通过。此兼容原因见 [上游变更记录](https://github.com/PyAV-Org/PyAV/blob/master/CHANGELOG.rst)。主 requirements 不强制安装转写依赖。

转写返回的是**素材秒**，附 `time_basis:source_media_seconds`、`requires_timeline_mapping:true`，不能直接当成已裁切项目秒。应用需经用户选择和时间线映射后导入。当前不自动转写与自动映射整条时间线。

## 验收命令与限制

在仓库根目录运行 `python -m pytest pokerstudio/tests/test_media.py -q`。FFmpeg 可用时真实生成短 TEST 视频，测试多片段顺序、动态公共牌／行动／底池／字幕、MP4 的 H264/AAC 与时长、源帧对应、取消后进程回收和失败未发布。缺 FFmpeg 时真实媒体测试标为 skipped，不能据此宣称导出成功。

长时间真实扑克录像、可变帧率、HDR、非默认旋转、复杂多音轨与超长字幕仍需实测。当前不含自动手牌 OCR、自动配音或背景音乐混音。最后成片视觉验收另在 `PROGRESS.md` / 验收记录保存实际截图路径。

2026-10-08 已完成真实媒体专项验收：`python -m pytest pokerstudio/tests/test_media.py -q -s` **4 passed / 3.23 秒**。保存于 `.data/acceptance/media-2095a4a6/` 的 `TEST-export.mp4` 为 5 秒、640×360、30fps、H264 / AAC。实际打开并查看 `export-start.png`、`export-middle.png`、`export-end.png`：可见公共牌 3→4→5 张、底池 10→120、Hero 下注 120、未知对手底牌问号、中文字幕与说明；几何花色清楚。源视频时间对应 3.5 / 0.5 / 6.5 秒，与项目预览和成片数值对比通过。失败任务无输出，取消测试终态为 cancelled，并结束／回收监督子进程。最终应用界面导出及后续回归由根任务另记。

最后用一段参考音轨（446.901秒、Opus双声道），经同一应用接口本地转写成功：256段、0–446.64秒、19.344秒，未人工听校。兼容错误和证据来源见 VIDEO_WORKFLOW.md。没有使用收费服务，应用没有自动下载模型。

实际浏览器另导入8秒 `TEST-ASR-interface.mp4`（明确测试画面与参考音轨短段），任务 `6d780d61e5c64299907528df06901211` completed，生成4条素材秒字幕，并实际按时间线导入/保存为项目秒0–8秒；项目 `.data/projects/d220dbfe5c2e48e3b8bff2694d117236.pokerstudio.json`。转写取消任务 `01a61637ef2044f381e40a1cb1ab1181` 终态cancelled。全音轨是参考材料分析，不是用户真实扑克录像效果或准确率验收。

可显式运行 `python -X utf8 -m pokerstudio.reference_transcribe --source <本地音视频> --model-dir <本地模型> --output-dir <结果目录>`；180秒超时可取消并回收。只有明确加 `--download-tiny` 才下载上游tiny模型，默认仅本地文件。模型下载和本地推理方式参考 [faster-whisper 上游](https://github.com/SYSTRAN/faster-whisper)。
