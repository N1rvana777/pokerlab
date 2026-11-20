"""Small real trees only; reuses PokerLab's serialized supervisor and LP oracle."""
import json
import os
import time
from itertools import product

import numpy as np
import pytest

from pokerlab.solver.__main__ import ROOT, save_result
from pokerlab.solver.reference import cards, equilibrium_value, river_matrix
from pokerstudio.solver import SolverAdapter, default_config

pytestmark = pytest.mark.skipif(os.environ.get("POKERLAB_NATIVE") != "1", reason="real native solver integration opt-in")


def wait(adapter, state, timeout=60):
    until = time.monotonic() + timeout
    while state["state"] not in ("completed", "failed", "cancelled", "interrupted"):
        if time.monotonic() > until:
            adapter.cancel(state["id"])
            pytest.fail("small solver adapter task exceeded 60 seconds")
        time.sleep(0.05)
        state = adapter.status(state["id"])
    assert state["state"] == "completed", state
    return adapter.result(state["id"])


def test_real_river_mapping_matches_existing_independent_linear_program():
    config = default_config()
    with SolverAdapter() as adapter:
        state = adapter.start(config)
        report = wait(adapter, state)
    matrix = river_matrix("".join(config["board"]), [[("AsAh", 1), ("QhJh", 1)], [("KsKh", 1), ("TcTd", 1)]], 20, 10)
    reference = equilibrium_value(matrix)
    assert reference == pytest.approx(40 / 3, abs=1e-8)
    assert report["ev"][0] == pytest.approx(reference, abs=0.025)
    assert sum(report["ev"]) == pytest.approx(config["pot"], abs=1e-4)
    assert report["precision"]["metric"] == "exploitability"
    assert report["precision"]["actual_chips"] <= 0.01
    assert report["config"] == config
    assert report["worker_resources"]["process_reaped"]
    save_result(ROOT / "pokerstudio/data/solver_acceptance_equilibrium.json", {
        "job_id": state["id"], "input": config, "ev": report["ev"], "independent_lp_oop_ev": reference,
        "absolute_error": abs(report["ev"][0] - reference), "precision": report["precision"],
        "worker_resources": report["worker_resources"], "resource_budget": report["resource_budget"],
        "config_sha256": report["config_sha256"]})


def test_real_fixed_model_export_is_independently_revalued_and_opponent_frozen():
    config = default_config("station_overbluff.json")
    with SolverAdapter() as adapter:
        state = adapter.start(config)
        report = wait(adapter, state)
        nodes = [wait(adapter, adapter.inspect(state["id"], p))["node"] for p in ([], [0], [0, 1], [1])]
    root, ip_check, hero_facing, ip_bet = nodes
    ranges = [[("AsAh", 1), ("QhJh", 1)], [("KsKh", 1), ("TcTd", 1), ("AcJd", 1)]]

    def probability(node, player, combo, action):
        combos = node["players"][player]["combos"]
        hand_index = next(i for i, s in enumerate(combos) if set(cards(s)) == set(cards(combo)))
        return node["strategy_action_major"][node["actions"].index(action) * len(combos) + hand_index]

    hero, villain = [], []
    for combo, _ in ranges[0]:
        hero += [probability(root, 0, combo, "Bet(10)"), probability(hero_facing, 0, combo, "Call")]
    for combo, _ in ranges[1]:
        villain += [probability(ip_check, 1, combo, "Bet(10)"), probability(ip_bet, 1, combo, "Call")]

    def plans(probabilities):
        return np.array([np.prod([p if bit else 1 - p for bit, p in zip(plan, probabilities)])
                         for plan in product([0, 1], repeat=len(probabilities))])

    matrix = river_matrix("".join(config["board"]), ranges, 20, 10)
    independent_ev = float(plans(hero) @ matrix @ plans(villain))
    assert independent_ev == pytest.approx(report["hero_best_response_ev"], abs=1e-4)
    assert report["opponent_unchanged"]
    assert report["precision"]["metric"] == "hero_response_gap"
    assert report["hero_improvement"] >= -0.001
    assert report["policy_validation"]["absolute_error"] <= report["policy_validation"]["tolerance_chips"]
    save_result(ROOT / "pokerstudio/data/solver_acceptance_fixed.json", {
        "job_id": state["id"], "input": config, "hero_best_response_ev": report["hero_best_response_ev"],
        "same_model_baseline_hero_ev": report["same_model_baseline_hero_ev"], "independent_policy_ev": independent_ev,
        "hero_improvement": report["hero_improvement"], "opponent_unchanged": report["opponent_unchanged"],
        "policy_validation": report["policy_validation"], "precision": report["precision"],
        "config_sha256": report["config_sha256"]})


def test_real_cancel_is_not_a_successful_result():
    with SolverAdapter() as adapter:
        state = adapter.start(default_config())
        adapter.cancel(state["id"])
        until = time.monotonic() + 30
        while adapter.status(state["id"])["state"] in ("queued", "running", "cancelling"):
            assert time.monotonic() < until
            time.sleep(0.05)
        assert adapter.status(state["id"])["state"] == "cancelled"
        with pytest.raises(ValueError, match="cancelled"):
            adapter.result(state["id"])
        worker_path = ROOT / "outputs/jobs" / state["id"] / "worker.json"
        if worker_path.exists():
            assert json.loads(worker_path.read_text())["process_reaped"]
