"""Verify a short exported project against decoded shared preview frames.

This records numerical checks, not a substitute for actually viewing the PNGs.
python -m pokerstudio.verify_export --project PATH --video PATH --output DIR
"""
import argparse
import json
from pathlib import Path
import subprocess

from . import media
from .project import validate


def verify(project_file, video_file, folder):
    import numpy as np
    from PIL import Image
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    project = validate(json.loads(Path(project_file).read_text(encoding="utf-8-sig")))
    plan = media.render_plan(project)
    metadata = media.probe_media(video_file)
    width, height, fps = plan["settings"]
    checks = {"duration_matches": abs(metadata["duration"] - plan["duration"]) < max(.12, 2/fps),
              "resolution_matches": (metadata["width"], metadata["height"]) == (width, height),
              "h264": metadata["video_codec"] == "h264", "audio_aac": bool(metadata["audio"]) and metadata["audio"][0]["codec"] == "aac"}
    times = [.5, plan["duration"]/2 + .5, plan["duration"] - .5]
    frames = []
    for i, t in enumerate(times):
        t = max(0, min(t, plan["duration"] - 1/fps))
        actual = folder / f"export-{i+1}.png"
        expected = folder / f"preview-{i+1}.png"
        media.extract_frame(video_file, t, actual, width, height)
        media.preview_frame(project, t, expected)
        with Image.open(actual) as a, Image.open(expected) as b:
            difference = np.abs(np.asarray(a.convert("RGB"), dtype=np.float32)-np.asarray(b.convert("RGB"), dtype=np.float32))
        clip = next(c for c in plan["clips"] if c["start"] <= t < c["end"])
        error = float(difference.mean())
        frames.append({"project_seconds": t, "source_path": clip["path"], "source_seconds": clip["in"]+t-clip["start"],
                       "export_frame": str(actual), "preview_frame": str(expected), "pixel_mae_0_to_255": error,
                       "matches_with_encoding_tolerance": error < 10})
    checks["frame_composites_match"] = all(f["matches_with_encoding_tolerance"] for f in frames)
    # A one-second decoded excerpt checks this TEST source's known 440Hz audio.
    # Never describe this as listening to narration or validating real speech.
    pcm = subprocess.run([media._require("ffmpeg"), "-v", "error", "-ss", "0.5", "-i", str(video_file),
                          "-t", "1", "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                         capture_output=True, timeout=30)
    if pcm.returncode:
        raise RuntimeError("音轨校验解码失败：" + pcm.stderr.decode("utf-8", "replace")[-4000:])
    samples = np.frombuffer(pcm.stdout, dtype="<i2").astype(np.float64)
    audio = {"sample_count": len(samples), "rms": float(np.sqrt(np.mean(samples**2))) if len(samples) else 0}
    if len(samples):
        power = np.abs(np.fft.rfft(samples*np.hanning(len(samples))))
        audio["peak_hz"] = float(np.fft.rfftfreq(len(samples), 1/48000)[np.argmax(power)])
    checks["test_tone_preserved"] = audio["rms"] > 100 and abs(audio.get("peak_hz", 0)-440) < 3
    result = {"project": str(Path(project_file).resolve()), "video": str(Path(video_file).resolve()),
              "metadata": metadata, "checks": checks, "frames": frames, "test_audio": audio,
              "passed": all(checks.values()), "visual_review": "PNG files still require actual viewing",
              "scope": "short synthetic TEST video, not real poker footage or speech"}
    (folder / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.project, args.video, args.output)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
