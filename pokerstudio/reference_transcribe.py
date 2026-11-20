"""Explicit, bounded local transcription for reference-media verification.

The application never downloads models implicitly. This optional command does so
only when --download-tiny is explicitly supplied, using the upstream model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .media import transcribe_local
from .subtitles import export_srt
from .tasks import Task


def main():
    parser = argparse.ArgumentParser(description="显式下载小型本地模型并验证媒体转写")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--download-tiny", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error("音频/视频源文件不存在")
    if not 1 <= args.timeout <= 600:
        parser.error("超时须为1–600秒")
    if args.download_tiny:
        # Do not use the user's Hugging Face credentials or global cache.
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "20"
        os.environ["HF_HUB_ETAG_TIMEOUT"] = "12"
        from faster_whisper.utils import download_model
        print("显式下载 upstream tiny 模型到 " + str(args.model_dir), flush=True)
        download_model("tiny", output_dir=str(args.model_dir.resolve()),
                       cache_dir=str(args.model_dir.parent / "download-cache"),
                       use_auth_token=False)
    task = Task("transcribe")
    timer = threading.Timer(args.timeout, task.cancel_event.set)
    timer.daemon = True
    started = time.monotonic()
    timer.start()
    try:
        print("开始本地 CPU/int8 转写，超时 " + str(args.timeout) + "秒", flush=True)
        result = transcribe_local(args.source, args.model_dir, task)
    finally:
        timer.cancel()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "transcript.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "transcript.srt").write_text(export_srt(result["subtitles"]), encoding="utf-8")
    items = result["subtitles"]
    source_hash = hashlib.sha256()
    with args.source.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            source_hash.update(chunk)
    summary = {
        "source": str(args.source.resolve()),
        "source_sha256": source_hash.hexdigest(),
        "model_dir": str(args.model_dir.resolve()), "model": "tiny",
        "language": result["language"], "duration": result["duration"],
        "segment_count": len(items),
        "first_start": items[0]["start"] if items else None,
        "last_end": items[-1]["end"] if items else None,
        "seconds": round(time.monotonic() - started, 3),
        "status": "completed", "review": "machine transcription; not official or manually corrected",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
