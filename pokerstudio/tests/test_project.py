import copy
import json

import pytest

from pokerstudio.project import ProjectStore, duration, uid


def store_with_media(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"test fixture; ProjectStore does not decode media")
    store = ProjectStore(tmp_path / "data")
    asset_id = uid()
    store.edit({"op": "add_asset", "asset": {"id": asset_id, "path": str(path), "metadata": {"duration": 12}}})
    return store, asset_id


def test_save_reopen_undo_split_and_original_not_modified(tmp_path):
    store, asset = store_with_media(tmp_path)
    before = (tmp_path / "video.mp4").read_bytes()
    clip = store.get()["clips"][0]
    store.edit({"op": "split_clip", "id": clip["id"], "at": 4})
    assert [(c["in"], c["out"]) for c in store.get()["clips"]] == [(0, 4), (4, 12)]
    store.edit({"op": "move_clip", "id": clip["id"], "to": 1})
    assert store.get()["clips"][0]["in"] == 4
    store.undo()
    assert store.get()["clips"][0]["in"] == 0
    store.redo()
    saved = store.save()
    other = ProjectStore(tmp_path / "other")
    loaded = other.open(saved["file_path"])
    assert loaded["clips"] == saved["clips"]
    assert (tmp_path / "video.mp4").read_bytes() == before


def test_missing_paths_load_and_can_relink(tmp_path):
    store, asset = store_with_media(tmp_path)
    saved = store.save()
    (tmp_path / "video.mp4").unlink()
    p = store.open(saved["file_path"])
    assert "路径失效" in p["warnings"][0]
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"replacement")
    store.edit({"op": "relink_asset", "id": asset, "path": str(replacement), "metadata": {"duration": 12}})
    assert not store.get()["warnings"]


def test_duplicate_cards_unknowns_and_integer_units(tmp_path):
    store, _ = store_with_media(tmp_path)
    hand = {"id": uid(), "start": 0, "end": 10, "pot": 20, "effective_stack": None,
            "board": ["Ac", "Ad", "2h", None, None],
            "players": [{"id": "hero", "cards": ["As", "Ah"]}, {"id": "ip", "cards": [None, None]}]}
    store.edit({"op": "upsert_hand", "item": hand})
    result = store.get()["hands"][0]
    assert type(result["pot"]) is int
    assert result["effective_stack"] is None
    assert result["players"][1]["cards"] == [None, None]
    bad = copy.deepcopy(hand)
    bad["players"][1]["cards"] = ["As", None]
    with pytest.raises(ValueError, match="重复牌"):
        store.edit({"op": "upsert_hand", "item": bad})
    assert store.get()["hands"][0] == result


def test_extract_hand_range_maps_clips_and_timed_data_atomically(tmp_path):
    store, asset = store_with_media(tmp_path)
    store.edit({"op": "split_clip", "id": store.get()["clips"][0]["id"], "at": 6})
    store.edit({"op": "upsert_hand", "item": {"id": uid(), "start": 4, "end": 9, "board": [], "players": [], "actions": []}})
    store.edit({"op": "upsert_subtitle", "item": {"id": "sub", "start": 3, "end": 5, "text": "test"}})
    before = store.get()
    store.edit({"op": "crop_range", "start": 4, "end": 9})
    p = store.get()
    assert [(c["in"], c["out"]) for c in p["clips"]] == [(4, 6), (6, 9)]
    assert p["duration"] == 5
    assert (p["hands"][0]["start"], p["hands"][0]["end"]) == (0, 5)
    assert (p["subtitles"][0]["start"], p["subtitles"][0]["end"]) == (0, 1)
    store.undo()
    assert store.get()["clips"] == before["clips"]
    assert store.get()["subtitles"] == before["subtitles"]


def test_revision_and_project_scope_protect_concurrent_edits(tmp_path):
    store, _ = store_with_media(tmp_path)
    revision = store.get()["revision"]
    store.edit({"op": "name", "name": "first"}, expected_revision=revision)
    with pytest.raises(ValueError, match="更新"):
        store.edit({"op": "name", "name": "stale"}, expected_revision=revision)
    with pytest.raises(ValueError, match="切换"):
        store.edit({"op": "name", "name": "wrong"}, project_id=uid())
    assert store.get()["name"] == "first"


def test_undo_keeps_agent_audit_and_proxy_is_invalidated_on_relink(tmp_path):
    store, asset = store_with_media(tmp_path)
    store.edit({"op": "name", "name": "agent edit"}, source="agent")
    store.undo()
    assert any(x["source"] == "agent" for x in store.get()["audit"])
    assert store.get()["audit"][-1]["label"] == "undo"
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"proxy")
    store.edit({"op": "attach_proxy", "id": asset, "source_path": str(tmp_path / "video.mp4"), "path": str(proxy)})
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"replacement")
    store.edit({"op": "relink_asset", "id": asset, "path": str(replacement), "metadata": {"duration": 12}})
    assert "proxy_path" not in store.get()["assets"][0]


def test_playhead_persistence_does_not_consume_edit_history(tmp_path):
    store, _ = store_with_media(tmp_path)
    before = store.get()
    store.set_playhead(3.5, project_id=before["id"])
    assert store.get()["revision"] == before["revision"]
    assert store.get()["audit"] == before["audit"]
    assert ProjectStore(store.data_dir).get()["playhead"] == 3.5
    with pytest.raises(ValueError, match="切换"):
        store.set_playhead(5, project_id=uid())
    with pytest.raises(ValueError, match="超出"):
        store.set_playhead(50)


@pytest.mark.parametrize("start,end", [(8, 4), (-1, 2), (0, 14), (float('nan'), 4)])
def test_invalid_clip_rejected_without_partial_edit(tmp_path, start, end):
    store, _ = store_with_media(tmp_path)
    p = store.get()
    with pytest.raises(ValueError):
        store.edit({"op": "trim_clip", "id": p["clips"][0]["id"], "in": start, "out": end})
    assert store.get()["clips"] == p["clips"]
