"""On-demand media processing and a shared, time-based overlay render plan.

FFmpeg reads media from disk; no whole movie is decoded into Python memory.
All commands use argv, private temporary files and cancellable process groups.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .tasks import TaskCancelled

ROOT = Path(__file__).resolve().parent


def _binary(name):
    explicit = os.environ.get("POKERSTUDIO_" + name.upper())
    if explicit:
        target = Path(explicit).expanduser()
        return str(target.resolve()) if target.is_file() else None
    found = shutil.which(name)
    if found:
        return found
    suffix = ".exe" if os.name == "nt" else ""
    for target in sorted((ROOT / ".tools").glob("**/" + name + suffix)):
        if target.is_file():
            return str(target)
    return None


def capabilities():
    ffmpeg, ffprobe = _binary("ffmpeg"), _binary("ffprobe")
    whisper = importlib.util.find_spec("faster_whisper") is not None
    return {"available": bool(ffmpeg and ffprobe), "ffmpeg": ffmpeg, "ffprobe": ffprobe,
            "encoding": "CPU libx264 / AAC", "hardware_encoding": "not_selected",
            "transcription": {"available": whisper, "provider": "faster-whisper",
                              "status": "needs_model" if whisper else "needs_dependency",
                              "reason": "需要本地模型目录；不会自动下载或调用收费API" if whisper else "本机未安装 faster-whisper；SRT导入导出可用"}}


def _require(name):
    value = _binary(name)
    if not value:
        raise RuntimeError(f"缺少{name}：安装FFmpeg/FFprobe到PATH或pokerstudio/.tools，或设置POKERSTUDIO_{name.upper()}；见docs/MEDIA.md")
    return value


def _check(task):
    if task and task.cancel_event.is_set():
        raise TaskCancelled("媒体任务已取消")


def _stop_process(process):
    if process.poll() is None:
        if os.name == "nt":
            # FFmpeg has no shell wrapper; taskkill /T also covers future child
            # processes. Always wait on the Popen object after termination.
            try:
                result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode and process.poll() is None:
                    process.kill()
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=5)
    else:
        process.wait()


def _run(args, *, task=None, duration=None, progress=(0, 0.99), timeout=3600):
    _check(task)
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.Popen([str(x) for x in args], stdout=subprocess.PIPE, stderr=errors,
                                   stdin=subprocess.DEVNULL, **kwargs)
        lines = queue.Queue()
        def read():
            for line in iter(process.stdout.readline, b""):
                lines.put(line.decode("utf-8", "replace").strip())
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                _check(task)
                if time.monotonic() > deadline:
                    raise TimeoutError(f"媒体子进程超过{timeout}秒时限")
                try:
                    line = lines.get(timeout=0.05)
                    if task and duration and line.startswith("out_time_us="):
                        seconds = max(0, int(line.partition("=")[2])) / 1e6
                        task.set_progress(progress[0] + (progress[1] - progress[0]) * min(1, seconds / duration))
                except queue.Empty:
                    pass
            code = process.wait()
            reader.join(timeout=2)
            _check(task)
            if code:
                errors.seek(0, os.SEEK_END)
                length = errors.tell()
                errors.seek(max(0, length - 16000))
                detail = errors.read().decode("utf-8", "replace").strip()
                raise RuntimeError(f"{Path(str(args[0])).name}退出码{code}: {detail}")
        finally:
            _stop_process(process)
            if process.stdout:
                process.stdout.close()
            reader.join(timeout=2)


def _ffmpeg(*args, **kwargs):
    return _run([_require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-progress", "pipe:1", "-filter_threads", "2", *args], **kwargs)


def probe_media(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"素材路径失效，请重新定位：{path}")
    process = subprocess.run([_require("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                              "-of", "json", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        raise RuntimeError("FFprobe读取失败：" + process.stderr.decode("utf-8", "replace")[-8000:])
    result = json.loads(process.stdout)
    streams = result.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ValueError("素材没有可播放视频流")
    duration = float(result.get("format", {}).get("duration") or video.get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("不能确定素材时长")
    ratio = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    a, b = ratio.split("/") if "/" in ratio else (ratio, "1")
    fps = float(a) / float(b) if float(b) else 0.0
    audio = [{"codec": s.get("codec_name"), "sample_rate": int(s.get("sample_rate") or 0),
              "channels": s.get("channels", 0), "index": s.get("index")} for s in streams if s.get("codec_type") == "audio"]
    return {"duration": duration, "width": video["width"], "height": video["height"],
            "fps": fps, "audio": audio, "video_codec": video.get("codec_name"),
            "format": result.get("format", {}).get("format_name"), "size": path.stat().st_size,
            "rotation": next((x.get("rotation", 0) for x in video.get("side_data_list", []) if "rotation" in x), 0)}


def _settings(project):
    settings = project.get("export_settings", {})
    width, height, fps = (int(settings.get(k, d)) for k, d in (("width", 1280), ("height", 720), ("fps", 30)))
    if not 320 <= width <= 3840 or not 240 <= height <= 2160 or width % 2 or height % 2 or not 1 <= fps <= 60:
        raise ValueError("导出设置无效：宽高必须为范围内偶数，帧率1–60")
    return width, height, fps


def render_plan(project):
    """The preview and export share clip mapping and all overlay event times."""
    assets = {a["id"]: a for a in project.get("assets", [])}
    clips, cursor = [], 0.0
    for clip in project.get("clips", []):
        asset = assets.get(clip["asset_id"])
        if not asset:
            raise ValueError("片段引用不存在的素材")
        start, end = float(clip["in"]), float(clip["out"])
        if not 0 <= start < end <= float(asset["metadata"]["duration"]) + 0.05:
            raise ValueError("片段入出点超出素材时长")
        clips.append({**clip, "path": asset["path"], "metadata": asset["metadata"],
                      "start": cursor, "end": cursor + end - start})
        cursor += end - start
    events = {0.0, cursor}
    for group in ("hands", "subtitles", "overlays"):
        for item in project.get(group, []):
            for key in ("start", "end"):
                if 0 < float(item[key]) < cursor:
                    events.add(float(item[key]))
            if group == "hands":
                for event in item.get("actions", []) + item.get("board_reveal", []):
                    if 0 < float(event["time"]) < cursor:
                        events.add(float(event["time"]))
    return {"clips": clips, "duration": cursor, "events": sorted(events), "settings": _settings(project)}


def _font(size):
    from PIL import ImageFont
    choices = [os.environ.get("POKERSTUDIO_FONT"), "C:/Windows/Fonts/msyh.ttc",
               "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for candidate in choices:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width, max_lines=5):
    lines, line = [], ""
    for char in str(text):
        if char == "\n" or (line and draw.textlength(line + char, font=font) > width):
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _card(draw, card, x, y, w, h, font):
    draw.rounded_rectangle((x, y, x+w, y+h), radius=max(3, w//10), fill=(247, 247, 240, 255), outline=(190, 195, 203, 255), width=1)
    value = str(card) if card else "?"
    suit = value[1] if len(value) == 2 and value[1] in "shdc" else None
    label = value[0] if suit else "?"
    color = (204, 46, 61, 255) if value[-1:] in ("h", "d") else (18, 27, 38, 255)
    box = draw.textbbox((0, 0), label, font=font)
    if not suit:
        draw.text((x + (w-(box[2]-box[0]))/2, y+(h-(box[3]-box[1]))/2-box[1]), label, fill=color, font=font)
        return
    draw.text((x+w*.11, y+h*.06-box[1]), label, fill=color, font=font)
    # Suit shapes are vectors, independent of font glyph coverage. Microsoft
    # YaHei supports Chinese but does not reliably contain playing-card suits.
    cx, cy, r = x+w*.62, y+h*.71, w*.20
    if suit == "d":
        draw.polygon([(cx,cy-r*1.2),(cx+r,cy),(cx,cy+r*1.2),(cx-r,cy)], fill=color)
    elif suit == "h":
        draw.ellipse((cx-r,cy-r,cx,cy), fill=color)
        draw.ellipse((cx,cy-r,cx+r,cy), fill=color)
        draw.polygon([(cx-r,cy-r*.45),(cx+r,cy-r*.45),(cx,cy+r)], fill=color)
    elif suit == "s":
        draw.ellipse((cx-r,cy-r*.15,cx,cy+r*.85), fill=color)
        draw.ellipse((cx,cy-r*.15,cx+r,cy+r*.85), fill=color)
        draw.polygon([(cx-r,cy+r*.4),(cx+r,cy+r*.4),(cx,cy-r)], fill=color)
        draw.polygon([(cx-r*.35,cy+r*1.15),(cx+r*.35,cy+r*1.15),(cx,cy+r*.3)], fill=color)
    else:
        small = r*.65
        for dx,dy in ((0,-r*.55),(-r*.52,r*.2),(r*.52,r*.2)):
            draw.ellipse((cx+dx-small,cy+dy-small,cx+dx+small,cy+dy+small), fill=color)
        draw.polygon([(cx-r*.35,cy+r*1.2),(cx+r*.35,cy+r*1.2),(cx,cy+r*.2)], fill=color)


def overlay_image(project, seconds):
    from PIL import Image, ImageDraw
    width, height, _ = _settings(project)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = width / 1280
    small, normal, large = (_font(max(12, round(n*scale))) for n in (20, 26, 32))
    margin = round(22*scale)
    settings = project.get("export_settings", {})
    if settings.get("overlays", True):
        hands = [h for h in project.get("hands", []) if h.get("overlay_enabled", True) and h["start"] <= seconds < h["end"]]
        if hands:
            hand = hands[-1]
            panel_width = min(width-margin*2, round(590*scale))
            card_w, card_h, gap = round(39*scale), round(53*scale), round(6*scale)
            players = hand.get("players", [])[:6]
            panel_height = round((116 + 56*len(players) + 43)*scale)
            panel_height = min(panel_height, height - margin*2 - round(120*scale))
            draw.rounded_rectangle((margin, margin, margin+panel_width, margin+panel_height), radius=round(12*scale), fill=(9, 20, 31, 214), outline=(81, 136, 164, 255), width=1)
            x, y = margin+round(14*scale), margin+round(10*scale)
            draw.text((x, y), str(hand.get("title") or "已记录手牌")[:30], font=normal, fill="white")
            actions = sorted((a for a in hand.get("actions", []) if a["time"] <= seconds), key=lambda a: a["time"])
            reveals = sorted((r for r in hand.get("board_reveal", []) if r["time"] <= seconds), key=lambda r: r["time"])
            if hand.get("board_reveal"):
                board = reveals[-1]["cards"] if reveals else []
                note = "公共牌"
            elif actions:
                count = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[actions[-1]["street"]]
                board = hand.get("board", [])[:count]
                note = "公共牌（按行动街道）"
            else:
                board = hand.get("board", [])
                note = "公共牌（静态记录）"
            y += round(37*scale)
            draw.text((x, y), note, font=small, fill=(192, 220, 230, 255))
            bx = x + round(222*scale)
            for i, value in enumerate(board):
                _card(draw, value, bx+i*(card_w+gap), y-round(5*scale), card_w, card_h, normal)
            pot = hand.get("pot")
            for action in actions:
                if action.get("pot_after") is not None:
                    pot = action["pot_after"]
            draw.text((x, y+round(26*scale)), "底池 " + (f"{pot:g}" if isinstance(pot, (int, float)) else "未知") + (" USD" if hand.get("amount_unit") == "USD" else " 筹码"), font=small, fill=(247, 199, 93, 255))
            y += round(59*scale)
            names = {p["id"]: p.get("name", p["id"]) for p in players}
            labels = {"check": "过牌", "bet": "下注", "call": "跟注", "raise": "加注", "fold": "弃牌", "allin": "全下", "showdown": "摊牌"}
            for player in players:
                last = next((a for a in reversed(actions) if a["player_id"] == player["id"]), None)
                label = (str(player.get("name") or "玩家") + " " + str(player.get("position") or ""))[:22]
                draw.text((x, y), label, font=small, fill="white")
                if last:
                    action_text = labels.get(last["type"], last["type"])
                    if last.get("amount") is not None:
                        action_text += f" {last['amount']:g}"
                    draw.text((x, y+round(23*scale)), action_text, font=small, fill=(125, 219, 170, 255))
                for i, value in enumerate(player.get("cards", [None, None])):
                    _card(draw, value, bx+i*(card_w+gap), y-round(4*scale), card_w, card_h, normal)
                y += round(56*scale)
        top = margin
        for item in project.get("overlays", []):
            if item.get("enabled", True) and item["start"] <= seconds < item["end"]:
                lines = _wrap(draw, item["text"], normal, width//2-margin*3, 4)
                lh = round(34*scale)
                x = width//2 + margin
                draw.rounded_rectangle((x, top, width-margin, top+len(lines)*lh+margin), radius=round(8*scale), fill=(8, 15, 22, 214))
                for i, line in enumerate(lines):
                    draw.text((x+margin//2, top+margin//2+i*lh), line, font=normal, fill="white")
                top += len(lines)*lh + margin*2
    if settings.get("subtitles", True):
        texts = [s["text"] for s in project.get("subtitles", []) if s.get("enabled", True) and s["start"] <= seconds < s["end"]]
        if texts:
            lines = _wrap(draw, "\n".join(texts), large, width-margin*4, 4)
            lh = round(43*scale)
            y = height-margin-len(lines)*lh
            draw.rounded_rectangle((margin, y-margin//2, width-margin, height-margin//2), radius=round(8*scale), fill=(0, 0, 0, 184))
            for i, line in enumerate(lines):
                length = draw.textlength(line, font=large)
                draw.text(((width-length)/2, y+i*lh), line, font=large, fill="white", stroke_width=1, stroke_fill="black")
    return image


def overlay_frame(project, seconds, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    overlay_image(project, float(seconds)).save(output, "PNG")
    return output


def extract_frame(path, seconds, output, width=1280, height=720):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-ss", f"{max(0,float(seconds)):.6f}", "-i", str(path), "-frames:v", "1", "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
            "-threads", "2", str(output), timeout=45)
    if not output.is_file():
        raise RuntimeError("请求时间没有可解码视频帧")
    return output


def preview_frame(project, seconds, output):
    from PIL import Image
    plan = render_plan(project)
    if not plan["clips"]:
        raise ValueError("时间线没有片段")
    t = min(max(0, float(seconds)), max(0, plan["duration"]-1/plan["settings"][2]))
    clip = next(c for c in plan["clips"] if c["start"] <= t < c["end"])
    width, height, _ = plan["settings"]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="studio-frame-", dir=output.parent) as tmp:
        base = extract_frame(clip["path"], clip["in"]+t-clip["start"], Path(tmp)/"base.png", width, height)
        with Image.open(base) as image:
            composed = Image.alpha_composite(image.convert("RGBA"), overlay_image(project, t))
            composed.convert("RGB").save(output, "PNG")
    return output


def _concat_escape(path):
    return "'" + str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''") + "'"


def export_project(project, output, task=None):
    plan = render_plan(project)
    if not plan["clips"] or plan["duration"] <= 0:
        raise ValueError("时间线没有有效片段")
    _require("ffmpeg")
    _require("ffprobe")
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("导出目标已存在，请选择新的文件名")
    width, height, fps = plan["settings"]
    _check(task)
    with tempfile.TemporaryDirectory(prefix=".studio-export-", dir=output.parent) as tmpname:
        tmp = Path(tmpname)
        segments = []
        total, cursor = plan["duration"], 0.0
        for i, clip in enumerate(plan["clips"]):
            _check(task)
            actual = probe_media(clip["path"])
            if clip["out"] > actual["duration"] + 0.05:
                raise ValueError("素材已变更，片段超出实际时长；请重新定位")
            duration = clip["out"] - clip["in"]
            segment = tmp / f"clip-{i:05d}.mp4"
            args = ["-ss", f"{clip['in']:.6f}", "-i", clip["path"]]
            if not actual["audio"]:
                args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            args += ["-t", f"{duration:.6f}", "-map", "0:v:0", "-map", "0:a:0" if actual["audio"] else "1:a:0",
                     "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},setpts=PTS-STARTPTS",
                     "-af", "aresample=48000,asetpts=PTS-STARTPTS,apad", "-ac", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                     "-pix_fmt", "yuv420p", "-threads", "4", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(segment)]
            if task:
                task.set_progress(0.55*cursor/total, f"处理片段 {i+1}/{len(plan['clips'])}")
            _ffmpeg(*args, task=task, duration=duration, progress=(0.55*cursor/total, 0.55*(cursor+duration)/total))
            segments.append(segment)
            cursor += duration
        concat = tmp / "clips.ffconcat"
        concat.write_text("ffconcat version 1.0\n" + "\n".join(
            "file " + _concat_escape(p) + f"\nduration {clip['out']-clip['in']:.9f}"
            for p, clip in zip(segments, plan["clips"])) + "\n", encoding="utf-8")
        overlay_concat = tmp / "overlay.ffconcat"
        overlay_lines = ["ffconcat version 1.0"]
        for i, (start, end) in enumerate(zip(plan["events"], plan["events"][1:])):
            _check(task)
            image = overlay_frame(project, start+min(1e-6, (end-start)/2), tmp / f"overlay-{i:05d}.png")
            overlay_lines += ["file " + _concat_escape(image), "option framerate 1000", f"duration {end-start:.9f}"]
        # A final duplicate gives concat a final timestamp; export -t owns length.
        overlay_lines += ["file " + _concat_escape(image), "option framerate 1000"]
        overlay_concat.write_text("\n".join(overlay_lines)+"\n", encoding="utf-8")
        pending = tmp / "result.mp4"
        if task:
            task.set_progress(0.57, "烧录同一时间计划的牌面、行动与字幕")
        _ffmpeg("-safe", "0", "-f", "concat", "-i", str(concat), "-safe", "0", "-f", "concat", "-i", str(overlay_concat),
                "-filter_complex_threads", "2", "-filter_complex", "[0:v]setpts=PTS-STARTPTS[base];[1:v]format=rgba,setpts=PTS-STARTPTS[ov];[base][ov]overlay=0:0:format=auto:eof_action=repeat[v]",
                "-map", "[v]", "-map", "0:a:0", "-t", f"{total:.6f}", "-r", str(fps),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-threads", "4",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(pending),
                task=task, duration=total, progress=(0.58, 0.97))
        _check(task)
        metadata = probe_media(pending)
        if abs(metadata["duration"]-total) > max(0.12, 2/fps) or metadata["width"] != width or metadata["height"] != height or not metadata["audio"]:
            raise RuntimeError("导出文件校验未通过：时长、分辨率或音轨不匹配")
        _check(task)
        # Never publish incomplete files or clobber an existing user's export.
        if output.exists():
            raise FileExistsError("导出目标在任务期间已创建，请更换文件名")
        os.replace(pending, output)
    return {"path": str(output), "duration": metadata["duration"], "width": width,
            "height": height, "fps": metadata["fps"], "audio": metadata["audio"], "verified": True}


def create_demo_media(output, duration=8, task=None):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("测试素材目标已存在")
    with tempfile.TemporaryDirectory(prefix=".studio-demo-", dir=output.parent) as tmpname:
        from PIL import Image, ImageDraw
        label = Path(tmpname)/"TEST.png"
        image = Image.new("RGBA", (960, 540))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((230, 400, 930, 515), radius=12, fill=(0, 0, 0, 190))
        draw.text((250, 410), "TEST / 合成验收素材", font=_font(40), fill="white")
        draw.text((250, 465), "非真实牌局 / 440Hz 音轨", font=_font(24), fill="white")
        image.save(label)
        target = Path(tmpname)/"test.mp4"
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=960x540:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-loop", "1", "-i", str(label), "-filter_complex_threads", "2", "-filter_complex", "[0:v][2:v]overlay=0:0[v]",
                "-map", "[v]", "-map", "1:a:0", "-t", str(float(duration)), "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "4", "-c:a", "aac", "-movflags", "+faststart", str(target),
                task=task, duration=duration)
        _check(task)
        probe_media(target)
        os.replace(target, output)
    return {"path": str(output), **probe_media(output), "test_material": True}


def create_proxy(path, output, task=None):
    metadata = probe_media(path)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name("." + uuid.uuid4().hex + ".mp4")
    try:
        _ffmpeg("-i", str(path), "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p", "-threads", "4",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(pending), task=task, duration=metadata["duration"])
        _check(task)
        verified = probe_media(pending)
        if abs(verified["duration"]-metadata["duration"]) > 0.15:
            raise RuntimeError("代理时长不匹配，未发布")
        os.replace(pending, output)
        return {"path": str(output), **verified, "source_path": str(path)}
    finally:
        pending.unlink(missing_ok=True)


def transcribe_local(path, model_path=None, task=None):
    if importlib.util.find_spec("faster_whisper") is None:
        raise RuntimeError("needs_dependency: 未安装 faster-whisper；请使用SRT或手工字幕。安装是独立可选步骤")
    if not model_path or not Path(model_path).expanduser().is_dir():
        raise RuntimeError("needs_model: 请配置已下载的本地 faster-whisper 模型目录；不会自动下载或调用收费API")
    _check(task)
    # Isolate native inference so model loading/transcribing can be cancelled
    # and reaped even before the generator produces its first segment.
    with tempfile.TemporaryDirectory(prefix="studio-transcribe-") as tmpname:
        target = Path(tmpname) / "result.json"
        _run([sys.executable, "-m", "pokerstudio.media", "transcribe-worker", str(Path(path).resolve()),
              str(Path(model_path).expanduser().resolve()), str(target)], task=task, timeout=3600)
        _check(task)
        return json.loads(target.read_text(encoding="utf-8"))


def _transcribe_worker(path, model_path, result_path):
    from faster_whisper import WhisperModel
    # local_files_only protects this explicit local route against model downloads.
    model = WhisperModel(str(Path(model_path).expanduser().resolve()), device="cpu", compute_type="int8", local_files_only=True, cpu_threads=4)
    segments, info = model.transcribe(str(path), beam_size=3)
    result = []
    for segment in segments:
        result.append({"id": uuid.uuid4().hex, "start": segment.start, "end": segment.end, "text": segment.text.strip(), "enabled": True})
        print("out_time_us=" + str(int(segment.end*1e6)), flush=True)
    value = {"subtitles": result, "language": info.language, "duration": info.duration,
             "time_basis": "source_media_seconds", "provider": "local faster-whisper", "requires_timeline_mapping": True}
    Path(result_path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "transcribe-worker":
        _transcribe_worker(*sys.argv[2:])
    else:
        raise SystemExit("该模块通过 Pokerstudio 媒体接口使用")
