"""Business state/scope checks; these do not verify media, models or solver EV.

Slow boundary doubles deliberately switch the real ProjectStore mid-operation.
They return no EV and do not establish a real solver or FFmpeg acceptance.
"""
from types import SimpleNamespace

import pytest

from pokerstudio.project import ProjectStore, uid
from pokerstudio.tools import Studio


def studio_state(tmp_path):
    # Avoid constructing authentication/solver subprocesses for state tests.
    studio = Studio.__new__(Studio)
    studio.data_dir = tmp_path / "data"
    studio.store = ProjectStore(studio.data_dir)
    studio.store.create("original")
    studio.solver_bindings = {}
    studio.analysis_config = None
    hand = {"id": uid(), "start": 0, "end": 3, "pot": 20,
            "effective_stack": 100, "amount_unit": "chips",
            "board": ["Ac", "Ad", "2h"],
            "players": [{"id": "hero", "position": "OOP", "cards": ["As", "Ah"]},
                        {"id": "villain", "position": "IP", "cards": [None, None]}]}
    studio.store.edit({"op": "upsert_hand", "item": hand})
    studio.store.save()
    return studio, hand


def test_agent_scope_rejects_old_project_before_any_edit(tmp_path):
    studio, hand = studio_state(tmp_path)
    original = studio.store.get()
    studio.store.create("new project")
    before = studio.store.get()
    with pytest.raises(ValueError, match="切换"):
        studio.execute_tool("update_hand", {"hand_id": hand["id"], "patch": {"pot": 120}},
                            context={"entry": "studio", "project_id": original["id"]})
    assert studio.store.get() == before
    reopened = ProjectStore(studio.data_dir)
    reopened.open(original["file_path"])
    assert reopened.get()["hands"][0]["pot"] == 20


@pytest.mark.parametrize("tool,args", [
    ("update_hand", {"patch": {"pot": 120}}),
    ("update_subtitle", {"subtitle": {"start": 0, "end": 1, "text": "blocked"}}),
    ("undo_edit", {}),
    ("export_video", {}),
])
def test_analysis_business_context_cannot_edit_studio(tmp_path, tool, args):
    studio, _ = studio_state(tmp_path)
    before = studio.store.get()
    with pytest.raises(ValueError, match="分析"):
        studio.execute_tool(tool, args, context={"entry": "analysis"})
    assert studio.store.get() == before


def test_agent_cannot_write_report_and_edits_autosave(tmp_path):
    studio, hand = studio_state(tmp_path)
    context = {"entry": "studio", "project_id": studio.store.get()["id"]}
    before = studio.store.get()
    with pytest.raises(ValueError, match="真实 solver"):
        studio.execute_tool("update_hand", {"patch": {"analysis": {"stale": False}}}, context)
    assert studio.store.get() == before
    result = studio.execute_tool("update_hand", {"patch": {"pot": 120}}, context)
    assert result["hands"][0]["pot"] == 120
    assert result["audit"][-1]["source"] == "agent"
    assert ProjectStore(studio.data_dir).get()["hands"][0]["pot"] == 120
    studio.execute_tool("undo_edit", {}, context)
    assert ProjectStore(studio.data_dir).get()["hands"][0]["pot"] == 20


def test_slow_probe_cannot_import_into_switched_project(tmp_path):
    studio, _ = studio_state(tmp_path)
    original = studio.store.get()
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"not a media acceptance fixture")

    def probe(_path):
        studio.store.create("new project")
        return {"duration": 3}

    studio.media = SimpleNamespace(probe_media=probe)
    with pytest.raises(ValueError, match="切换"):
        studio.import_asset(source)
    assert studio.store.get()["name"] == "new project"
    assert studio.store.get()["assets"] == []
    studio.store.open(original["file_path"])
    assert studio.store.get()["assets"] == []


def test_solver_job_keeps_project_scope_from_before_start(tmp_path):
    studio, hand = studio_state(tmp_path)
    original = studio.store.get()

    def start(**_kwargs):
        studio.store.create("new project")
        return {"id": "boundary-job", "state": "queued"}

    studio.solver = SimpleNamespace(start=start)
    task = studio.solve()
    assert task["task_id"] == "solve:boundary-job"
    binding = studio.solver_bindings["boundary-job"]
    assert binding["project_id"] == original["id"]
    assert binding["hand_id"] == hand["id"]
    assert studio.store.get()["name"] == "new project"
