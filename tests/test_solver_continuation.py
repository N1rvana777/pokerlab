"""Checkpoint orchestration tests; numeric continuation is separately opt-in.

The monkeypatched launcher tests do not claim a real solve. The native test
compares a resumed run to a fresh uninterrupted run with identical poker inputs.
"""
import copy
import json
import os
import uuid

import pytest

from pokerlab.solver import workbench


def config():
    return {
        "schema_version": 1,
        "board": ["9h", "8h", "2c", "4s", "3d"],
        "players": ["AsAh,KsKh,QsQh,JsJh:0.4", "AcAd,KcKd,QcQd,JcJd:0.7"],
        "pot": 43,
        "stack": 60,
        "bets": ["33%,75%"] * 3,
        "raises": ["2x"] * 3,
        "bets_ip": ["50%"] * 3,
        "raises_ip": ["2x"] * 3,
        "donks": ["", ""],
        "hero": 0,
        "mode": "equilibrium",
        "target": 0.0001,
        "target_unit": "pot_pct",
        "max_iterations": 18,
        "memory_budget_mb": 2048,
        "compression": True,
        "auto_suits": True,
        "expand_suits": True,
        "threads": 1,
        "profile": {"traits": [], "overrides": []},
    }


def test_cfr_key_preserves_progress_when_only_precision_or_model_changes():
    original = config()
    changed = copy.deepcopy(original)
    changed.update(target=0.00005, target_unit="chips", max_iterations=31,
                   mode="fixed", hero=1, memory_budget_mb=4096,
                   memory_auto=True, amount_unit="bb", time_limit_seconds=600)
    changed["profile"]["traits"] = [{"kind": "station", "strength": 3, "streets": [3, 4, 5]}]
    assert workbench.cfr_key(original) == workbench.cfr_key(changed)
    assert workbench.baseline_key(original) != workbench.baseline_key(changed)
    # Only the resolved canonical layout matters for continuation.
    merged = copy.deepcopy(original)
    merged.update(expand_suits=False, auto_suits=False)
    assert workbench.cfr_key(original) == workbench.cfr_key(merged)


@pytest.mark.parametrize("field,value", [
    ("board", ["9h", "8h", "2c", "4s", "5d"]),
    ("players", ["AsAh,KsKh", "AcAd,KcKd"]),
    ("pot", 44), ("stack", 61),
    ("bets", ["25%,75%"] * 3), ("raises", ["3x"] * 3),
    ("bets_ip", ["75%"] * 3), ("raises_ip", ["3x"] * 3),
    ("donks", ["33%", ""]), ("compression", False), ("threads", 4),
])
def test_cfr_key_invalidates_incompatible_cards_tree_storage_and_reduction(field, value):
    original = config()
    changed = copy.deepcopy(original)
    changed[field] = value
    assert workbench.cfr_key(original) != workbench.cfr_key(changed)


def test_cfr_key_separates_expanded_lock_layout_and_engine(monkeypatch):
    original = config()
    locked = copy.deepcopy(original)
    locked["profile"]["overrides"] = [{"path": [1], "combo": "AcAd", "probabilities": [0, 1]}]
    assert workbench.cfr_key(original) != workbench.cfr_key(locked)
    other_lock = copy.deepcopy(locked)
    other_lock["profile"]["overrides"][0]["probabilities"] = [0.5, 0.5]
    # Both CFR baselines have the same expanded tree; opponent lock contents
    # only become active after the raw CFR checkpoint has been saved.
    assert workbench.cfr_key(locked) == workbench.cfr_key(other_lock)
    previous = workbench.cfr_key(original)
    monkeypatch.setattr(workbench, "REV", "different-engine-revision")
    assert workbench.cfr_key(original) != previous


def write_header(path, metadata, *, length=None, magic=b"PLCFR001"):
    header = json.dumps(metadata, separators=(",", ":")).encode()
    path.write_bytes(magic + (len(header) if length is None else length).to_bytes(8, "little") + header)


@pytest.mark.parametrize("iterations", [0, 18, 31, 2**32 - 1])
def test_checkpoint_iteration_header_accepts_u32_counts(tmp_path, iterations):
    path = tmp_path / "state.cfr"
    write_header(path, {"key": "test", "iterations": iterations, "compression": True})
    assert workbench.checkpoint_iterations(path) == iterations


@pytest.mark.parametrize("metadata", [
    [], [1], None, True, "string", 5,
    {}, {"iterations": None}, {"iterations": -1}, {"iterations": True},
    {"iterations": 18.0}, {"iterations": "18"}, {"iterations": 2**32},
])
def test_checkpoint_iteration_header_rejects_wrong_json_type_and_count(tmp_path, metadata):
    path = tmp_path / "state.cfr"
    write_header(path, metadata)
    assert workbench.checkpoint_iterations(path) is None


def test_checkpoint_iteration_header_rejects_missing_old_oversized_and_truncated(tmp_path):
    path = tmp_path / "state.cfr"
    assert workbench.checkpoint_iterations(path) is None
    for data in [b"", b"PLCFR001", b"PLCFR001\x10", b"PLPOL003" + b"\x00" * 8]:
        path.write_bytes(data)
        assert workbench.checkpoint_iterations(path) is None
    write_header(path, {"iterations": 18}, length=1024 * 1024 + 1)
    assert workbench.checkpoint_iterations(path) is None
    # A valid JSON prefix does not satisfy a longer declared header length.
    write_header(path, {"iterations": 18}, length=200)
    assert workbench.checkpoint_iterations(path) is None


@pytest.fixture
def fake_launcher(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench, "ROOT", tmp_path)
    folder = tmp_path / "outputs" / "jobs" / "unit-test"
    folder.mkdir(parents=True)
    calls = []

    def execute(request, job_folder, timeout):
        calls.append({"request": copy.deepcopy(request), "folder": job_folder, "timeout": timeout})
        return {"unit_test_mock": True}

    monkeypatch.setattr(workbench, "execute", execute)
    return folder, calls


@pytest.mark.parametrize("legacy_limit", [1, 600, 3600])
def test_normal_solve_ignores_legacy_wall_timeout_without_mutating_config(fake_launcher, legacy_limit):
    folder, calls = fake_launcher
    original = config()
    original["time_limit_seconds"] = legacy_limit
    before = copy.deepcopy(original)
    result = workbench.solve_cached(original, folder)
    assert calls[0]["timeout"] is None
    assert original == before and "runtime" not in original
    assert result["config"] == before
    assert calls[0]["request"]["runtime"]["checkpoint_key"] == workbench.cfr_key(original)
    # Explicit diagnostic limits remain independently honored.
    workbench.solve_cached(original, folder, timeout=2.5)
    assert calls[1]["timeout"] == 2.5


@pytest.mark.parametrize("saved_iterations,should_resume", [(13, True), (18, True), (31, False)])
def test_solve_does_not_load_or_overwrite_state_beyond_iteration_ceiling(fake_launcher, saved_iterations, should_resume):
    folder, calls = fake_launcher
    original = config()
    path = workbench.ROOT / "outputs" / "cache" / f"{workbench.cfr_key(original)}.cfr"
    path.parent.mkdir(parents=True)
    write_header(path, {"key": workbench.cfr_key(original), "iterations": saved_iterations, "compression": True})
    previous = path.read_bytes()
    workbench.solve_cached(original, folder)
    assert ("checkpoint_file" in calls[0]["request"]["runtime"]) is should_resume
    assert path.read_bytes() == previous


@pytest.mark.skipif(os.environ.get("POKERLAB_NATIVE") != "1", reason="real native continuation opt-in")
def test_workbench_resume_matches_fresh_uninterrupted_native_run(monkeypatch):
    # Isolate this tiny River cache on every invocation without removing any
    # existing user study/cache or changing poker parameters for uniqueness.
    namespace = uuid.uuid4().hex
    original_cfr_key, original_baseline_key = workbench.cfr_key, workbench.baseline_key
    monkeypatch.setattr(workbench, "cfr_key", lambda c: workbench.fingerprint([namespace, original_cfr_key(c)]))
    monkeypatch.setattr(workbench, "baseline_key", lambda c: workbench.fingerprint([namespace, original_baseline_key(c)]))
    first_config = config()
    first = workbench.solve_cached(first_config, timeout=60)
    assert first["precision"]["baseline_iterations"] == 18
    assert first["precision"]["baseline_stop_reason"] == "iteration_limit"
    assert first["cache"]["resumed_iterations"] == 0
    checkpoint = workbench.ROOT / "outputs" / "cache" / f"{workbench.cfr_key(first_config)}.cfr"
    assert workbench.checkpoint_iterations(checkpoint) == 18
    continued_config = copy.deepcopy(first_config)
    continued_config["max_iterations"] = 31
    continued = workbench.solve_cached(continued_config, timeout=60)
    assert continued["cache"]["baseline_hit"] is False
    assert continued["cache"]["resumed_iterations"] == 18
    assert continued["precision"]["baseline_iterations"] == 31
    fresh = workbench.execute(continued_config, timeout=60)
    assert fresh["cache"]["resumed_iterations"] == 0
    assert continued["precision"]["baseline_exploitability_chips"] == fresh["precision"]["baseline_exploitability_chips"]
    assert continued["baseline_root_strategy"] == fresh["baseline_root_strategy"]
    assert continued["ev"] == fresh["ev"]
    assert sum(continued["ev"]) == pytest.approx(43, abs=1e-5)
