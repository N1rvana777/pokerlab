"""Strict SRT import/export with project-relative seconds and no cloud calls."""
from __future__ import annotations

import math
import re
import uuid

TIMESTAMP = r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})"


def _seconds(value):
    match = re.fullmatch(TIMESTAMP, value.strip())
    if not match:
        raise ValueError("SRT时间应为 HH:MM:SS,mmm")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    if minutes > 59 or seconds > 59:
        raise ValueError("SRT分钟或秒超出范围")
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def parse_srt(text):
    if not isinstance(text, str) or len(text) > 2 * 1024 * 1024:
        raise ValueError("字幕文本须为最多2MiB的SRT字符串")
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    result = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines.pop(0)
        if not lines or "-->" not in lines[0]:
            raise ValueError("SRT缺少时间戳行")
        parts = lines.pop(0).split("-->")
        if len(parts) != 2:
            raise ValueError("SRT时间戳行无效")
        start, end = (_seconds(v) for v in parts)
        if end <= start:
            raise ValueError("字幕结束须晚于开始")
        content = "\n".join(lines).strip()
        if not content:
            raise ValueError("字幕文字不能为空")
        result.append({"id": uuid.uuid4().hex, "start": start, "end": end,
                       "text": content, "enabled": True})
    return result


def _timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError("字幕时间须为非负有限秒数")
    ms = round(value * 1000)
    hours, rest = divmod(ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def export_srt(items):
    blocks = []
    for item in sorted((x for x in items if x.get("enabled", True)), key=lambda x: (x["start"], x["end"])):
        if item["end"] <= item["start"]:
            raise ValueError("字幕结束须晚于开始")
        text = str(item["text"]).strip()
        if not text:
            continue
        blocks.append(f"{len(blocks)+1}\n{_timestamp(item['start'])} --> {_timestamp(item['end'])}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")
