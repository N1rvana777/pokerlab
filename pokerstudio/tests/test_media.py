"""Real CPU media acceptance, with synthetic TEST material only."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import uuid

from PIL import Image, ImageChops, ImageStat
import pytest

from pokerstudio import media
from pokerstudio.subtitles import export_srt, parse_srt
from pokerstudio.tasks import TaskManager

ROOT = Path(__file__).resolve().parents[1]


def wait_task(manager, task_id, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = manager.get(task_id)
        if state["status"] in ("completed", "failed", "cancelled"):
            return state
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_srt_roundtrip_and_rejections():
    source = "\ufeff1\r\n00:00:00,125 --> 00:00:01,250\r\n下注 120\r\nTEST\r\n\r\n2\r\n00:00:01,250 --> 00:00:03,000\r\n未知牌保持 ?\r\n"
    items = parse_srt(source)
    assert items[0]["start"] == .125 and items[0]["text"] == "下注 120\nTEST"
    again = parse_srt(export_srt(items))
    assert [(x["start"], x["end"], x["text"]) for x in again] == [(x["start"], x["end"], x["text"]) for x in items]
    items[1]["enabled"] = False
    assert len(parse_srt(export_srt(items))) == 1
    for bad in ("1\n00:61:00,000 --> 00:62:00,000\ninvalid", "1\n00:00:01,000 --> 00:00:00,000\ninvalid", "text without time"):
        with pytest.raises(ValueError):
            parse_srt(bad)


def test_task_cancellation_reaps_process_and_failure():
    manager = TaskManager()
    # Exercise the same supervision routine as FFmpeg; no long media fixture.
    task = manager.create("cancel-test", lambda t: media._run([sys.executable, "-c", "import time; time.sleep(30)"], task=t))
    deadline = time.monotonic()+3
    while manager.get(task["id"])["status"] == "queued" and time.monotonic() < deadline:
        time.sleep(.01)
    manager.cancel(task["id"])
    state = wait_task(manager, task["id"], 10)
    assert state["status"] == "cancelled" and state["result"] is None and state["progress"] < 1
    failed = manager.create("fail-test", lambda t: media._run([sys.executable, "-c", "import sys; sys.stderr.write('TEST intentional failure'); sys.exit(7)"], task=t))
    state = wait_task(manager, failed["id"], 10)
    assert state["status"] == "failed" and "退出码7" in state["error"] and "TEST intentional failure" in state["error"]
    assert state["result"] is None
    manager.shutdown()


def test_shared_plan_and_dynamic_unknown_overlay():
    project = {"assets": [{"id": "a", "path": "TEST", "metadata": {"duration": 8}}],
               "clips": [{"id": "c1", "asset_id": "a", "in": 3, "out": 5}, {"id": "c2", "asset_id": "a", "in": 0, "out": 2}],
               "export_settings": {"width": 640, "height": 360, "fps": 30},
               "hands": [{"id": "h", "start": 0, "end": 4, "title": "TEST", "board": ["As", "Kh", "Qd", "Jc", None],
                          "players": [{"id": "p", "name": "Hero", "position": "BTN", "cards": ["Ts", None]}],
                          "board_reveal": [{"time": 1, "cards": ["As", "Kh", "Qd"]}, {"time": 2, "cards": ["As", "Kh", "Qd", "Jc"]}],
                          "pot": None, "actions": [{"time": 2, "street": "turn", "type": "bet", "player_id": "p", "amount": 120, "pot_after": 120}]}],
               "subtitles": [{"id": "s", "start": .5, "end": 1.5, "text": "已确认字幕"}], "overlays": []}
    plan = media.render_plan(project)
    assert plan["duration"] == 4 and plan["clips"][1]["start"] == 2
    assert plan["events"] == [0, .5, 1, 1.5, 2, 4]
    before, after = media.overlay_image(project, .1), media.overlay_image(project, 2.1)
    assert ImageChops.difference(before, after).getbbox() is not None
    project["export_settings"].update(overlays=False, subtitles=False)
    assert media.overlay_image(project, 2.1).getbbox() is None


@pytest.mark.skipif(not media.capabilities()["available"], reason="Real FFmpeg/FFprobe unavailable; export not verified")
def test_actual_multiclip_export_preview_and_probe():
    target_dir = ROOT / ".data" / "acceptance" / ("media-" + uuid.uuid4().hex[:8])
    target_dir.mkdir(parents=True)
    source = target_dir / "TEST-source.mp4"
    media.create_demo_media(source, duration=8)
    metadata = media.probe_media(source)
    assert abs(metadata["duration"]-8) <= .08 and metadata["audio"] and metadata["video_codec"] == "h264"
    project = {"assets": [{"id": "a", "path": str(source), "metadata": metadata}],
               "clips": [{"id": "c1", "asset_id": "a", "in": 3, "out": 5}, {"id": "c2", "asset_id": "a", "in": 0, "out": 2}, {"id": "c3", "asset_id": "a", "in": 6, "out": 7}],
               "export_settings": {"width": 640, "height": 360, "fps": 30, "overlays": True, "subtitles": True},
               "hands": [{"id": "h", "title": "TEST 动态牌谱", "start": 0, "end": 5, "board": ["As", "Kh", "Qd", "Jc", "2s"], "pot": 10,
                          "players": [{"id": "hero", "name": "Hero", "position": "BTN", "cards": ["Th", "9c"]}, {"id": "villain", "name": "未知对手", "position": "BB", "cards": [None, None]}],
                          "board_reveal": [{"time": .2, "cards": ["As", "Kh", "Qd"]}, {"time": 1.7, "cards": ["As", "Kh", "Qd", "Jc"]}, {"time": 3.3, "cards": ["As", "Kh", "Qd", "Jc", "2s"]}],
                          "actions": [{"time": 1.7, "street": "turn", "player_id": "hero", "type": "bet", "amount": 120, "pot_after": 120}]}],
               "subtitles": [{"id": "s1", "start": 0, "end": .8, "text": "TEST 起始字幕 / 已知牌"}, {"id": "s2", "start": 1.8, "end": 2.5, "text": "底池已确认 120；未知牌保持问号"}],
               "overlays": [{"id": "o", "start": 2.8, "end": 4.8, "text": "TEST 多片段、动态公共牌", "enabled": True}]}
    (target_dir/"TEST-project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    output = target_dir / "TEST-export.mp4"
    manager = TaskManager()
    task = manager.create("export", lambda t: media.export_project(project, output, t))
    state = wait_task(manager, task["id"])
    assert state["status"] == "completed", state
    assert state["progress"] == 1 and state["result"]["verified"]
    actual = media.probe_media(output)
    assert abs(actual["duration"]-5) < .12 and actual["width"] == 640 and actual["height"] == 360
    assert actual["video_codec"] == "h264" and actual["audio"][0]["codec"] == "aac"
    for label, t, source_t in (("start", .5, 3.5), ("middle", 2.5, .5), ("end", 4.5, 6.5)):
        preview = media.preview_frame(project, t, target_dir/f"preview-{label}.png")
        exported = media.extract_frame(output, t, target_dir/f"export-{label}.png", 640, 360)
        expected = media.extract_frame(source, source_t, target_dir/f"source-{label}.png", 640, 360)
        # Region is outside all hand panels/subtitles/text. Independently check
        # timeline source mapping, including reordered clips and source offsets.
        region = (15, 170, 110, 220)
        with Image.open(exported) as exp, Image.open(expected) as raw:
            difference = ImageStat.Stat(ImageChops.difference(exp.convert("RGB").crop(region), raw.convert("RGB").crop(region)))
            assert sum(difference.mean)/3 < 12, (label, difference.mean)
        # Burned overlay must match the same Pillow preview (allow H264 loss).
        with Image.open(exported) as exp, Image.open(preview) as pre:
            difference = ImageStat.Stat(ImageChops.difference(exp.convert("RGB").crop((12, 12, 260, 115)), pre.convert("RGB").crop((12, 12, 260, 115))))
            assert sum(difference.mean)/3 < 15, (label, difference.mean)
    # Failure leaves no apparently successful output, even with valid ffmpeg.
    broken = json.loads(json.dumps(project))
    broken["assets"][0]["path"] = str(target_dir/"missing.mp4")
    failed_target = target_dir/"SHOULD-NOT-EXIST.mp4"
    bad = manager.create("export", lambda t: media.export_project(broken, failed_target, t))
    bad_state = wait_task(manager, bad["id"])
    assert bad_state["status"] == "failed" and not failed_target.exists()
    manager.shutdown()
    (target_dir/"TEST-acceptance.json").write_text(json.dumps({"metadata": actual, "export_task": state, "failure_task": bad_state}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MEDIA_ACCEPTANCE=" + str(target_dir))
