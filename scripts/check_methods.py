"""Check principle files: required fields, tags, evidence that points at real moments, and no pasted captions.

  python -X utf8 scripts/check_methods.py outputs/knowledge/hhp/methods/methods.json

A candidate file from one reading batch has the same shape, without "id". Exit code 1 means problems were printed.
"""
import argparse
import json
from pathlib import Path
import re
import sys

from pokerlab.coach.knowledge import Knowledge, seconds_of
from pokerlab.coach.tools import METHOD_TAGS

NEEDED = ("title", "read", "adjustment", "why")
COPIED_WORDS = 12  # this many caption words in a row means text was pasted, not written


def caption_runs(base):
    """Every run of COPIED_WORDS caption words, to catch pasted text."""
    runs = set()
    for segments in base.segments.values():
        words = re.findall(r"[a-z']+", " ".join(text for _, text in segments).lower())
        runs.update(" ".join(words[at:at + COPIED_WORDS]) for at in range(len(words) - COPIED_WORDS + 1))
    return runs


def problems(entries, base):
    out = []
    hands = {entry["id"] for entry in base.hands}
    runs = caption_runs(base)
    last = {vid: segments[-1][0] for vid, segments in base.segments.items() if segments}
    for at, entry in enumerate(entries):
        name = entry.get("id") or f"第 {at + 1} 条"
        out += [f"{name}：缺少 {key}" for key in NEEDED if not entry.get(key)]
        out += [f"{name}：标签 {tag} 不在词表里" for tag in entry.get("tags") or [] if tag not in METHOD_TAGS]
        if not entry.get("evidence"):
            out.append(f"{name}：没有证据")
        for item in entry.get("evidence") or []:
            if item.get("url"):
                continue
            seconds = seconds_of(item.get("time"))
            if item.get("video") not in last:
                out.append(f"{name}：视频 {item.get('video')} 没有字幕")
            elif seconds is None or seconds > last[item["video"]] + 60:
                out.append(f"{name}：{item.get('video')} 的时间 {item.get('time')} 不在视频内")
            if item.get("hand") and item["hand"] not in hands:
                out.append(f"{name}：手牌 {item['hand']} 不存在")
        words = re.findall(r"[a-z']+", json.dumps(entry, ensure_ascii=False).lower())
        if any(" ".join(words[at:at + COPIED_WORDS]) in runs for at in range(len(words) - COPIED_WORDS + 1)):
            out.append(f"{name}：有一段和字幕连续相同")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    base = Knowledge()
    found = []
    for path in args.files:
        entries = json.loads(path.read_text(encoding='utf-8'))
        found += [f"{path.name} {text}" for text in problems(entries, base)]
        print(path.name, len(entries), 'entries')
    print('\n'.join(found) or 'no problems')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
