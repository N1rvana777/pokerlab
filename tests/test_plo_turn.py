"""Joint turn + river solving: chance handling, independent references, checkpoints, CLI."""
import json

import numpy as np
import pytest

from pokerlab.plo.__main__ import main
from pokerlab.plo.cards import parse_cards
from pokerlab.plo.subgame import turn as turn_module
from pokerlab.plo.evaluator import plo_rank_reference
from pokerlab.plo.subgame.cfr import SolverConfig
from pokerlab.plo.subgame.turn import (
    CheckpointMismatch, TurnRiverSolver, evaluate_turn_profile, turn_river_game,
)
from pokerlab.plo.subgame.turn_reference import (
    solve_turn_sequence_form, turn_best_response_reference, turn_profile_value_reference,
)
from pokerlab.plo.subgame.tree import DECISION

BOARD = "Ks 9h 7d 4c"
# Deliberate card overlaps across players (As, 8h) and weights that are not uniform.
OOP = {"AsAdQcJc": 3.0, "8h8c6s5s": 1.0, "AcKdTh9c": 2.0}
IP = {"AsKhQd3s": 2.5, "8h6h5d2c": 0.5, "QsQhJdTd": 1.0}


def tiny(**extra):
    spec = {"board": BOARD, "big_blind": 100, "pot": 1000, "stacks": [500, 500],
            "ranges": [{"hands": list(OOP), "weights": list(OOP.values())},
                       {"hands": list(IP), "weights": list(IP.values())}],
            "turn_max_raises": 1, "river_max_raises": 1}
    spec.update(extra)
    return spec


def random_profile(solver, seed):
    rng = np.random.default_rng(seed)
    norm = lambda x: x / x.sum(axis=-1, keepdims=True)
    return {"turn": {k: norm(rng.random(v.shape)) for k, v in solver.turn_regret.items()},
            "river": {k: norm(rng.random(v.shape)) for k, v in solver.river_regret.items()}}


def test_joint_cfr_converges_to_the_joint_sequence_form_lp():
    game = turn_river_game(tiny())
    lp = solve_turn_sequence_form(game)
    assert lp["value0"] == pytest.approx(lp["value0_dual"], abs=1e-6)
    assert evaluate_turn_profile(game, lp["profile"])["exploitability_chips"] < 1e-6
    solver = TurnRiverSolver(game, SolverConfig("dcfr"))
    solver.run(400)
    result = evaluate_turn_profile(game, solver.average_profile())
    assert result["exploitability_pct_pot"] < 0.01
    # v0(profile) and the game value both lie in [pot - BR1, BR0], an interval of length NashConv.
    assert abs(result["value"][0] - lp["value0"]) <= result["nash_conv_chips"] + 1e-6
    assert result["constant_sum_check"] == pytest.approx(0.0, abs=1e-9)


def test_fast_best_response_matches_the_loop_reference_with_explicit_river_cards():
    game = turn_river_game(tiny())
    solver = TurnRiverSolver(game)
    for seed in range(2):
        profile = random_profile(solver, seed)
        fast = evaluate_turn_profile(game, profile)
        for p in (0, 1):
            assert fast["best_response_value"][p] == pytest.approx(
                turn_best_response_reference(game, profile, p), abs=1e-9)
            assert fast["value"][p] == pytest.approx(turn_profile_value_reference(game, profile, p), abs=1e-9)


def test_river_deal_probabilities_are_normalised():
    game = turn_river_game(tiny())
    # Everyone checks/calls: value0 = pot * E[share] over disjoint pairs and the 40 cards each leaves.
    profile = {"turn": {}, "river": {}}
    solver = TurnRiverSolver(game)
    for nid in game.turn_tree.decision_nodes():
        node = game.turn_tree.nodes[nid]
        probs = np.zeros(len(node.actions))
        probs[node.actions.index("check" if "check" in node.actions else "call")] = 1.0
        profile["turn"][nid] = np.tile(probs, (game.size(node.player), 1))
    for (leaf, rid), regret in solver.river_regret.items():
        node = game.leaves[leaf].tree.nodes[rid]
        probs = np.zeros(len(node.actions))
        probs[node.actions.index("check" if "check" in node.actions else "call")] = 1.0
        profile["river"][(leaf, rid)] = np.broadcast_to(probs, regret.shape).copy()
    board = parse_cards(BOARD)
    total = z = 0.0
    for a, wa in OOP.items():
        for b, wb in IP.items():
            ha, hb = parse_cards(a), parse_cards(b)
            if set(ha) & set(hb):
                continue
            z += wa * wb
            rivers = [c for c in range(52) if c not in board and c not in ha and c not in hb]
            assert len(rivers) == 40
            for c in rivers:
                ra, rb = plo_rank_reference(ha, board + (c,)), plo_rank_reference(hb, board + (c,))
                total += wa * wb * (1.0 if ra > rb else 0.5 if ra == rb else 0.0) / 40
    assert evaluate_turn_profile(game, profile)["value"][0] == pytest.approx(game.pot * total / z, abs=1e-9)


def test_hands_holding_the_river_card_never_reach_that_river():
    game = turn_river_game(tiny())
    solver = TurnRiverSolver(game)
    solver.run(30)
    for (leaf, rid), strategy in solver.river_strategy.items():
        player = game.leaves[leaf].tree.nodes[rid].player
        blocked = game.masks[player] == 0                  # (cards, hands)
        assert np.all(strategy[blocked] == 0.0)
        assert strategy[~blocked].sum() > 0


def test_turn_checkpoint_resume_is_bitwise_identical(tmp_path):
    game = turn_river_game(tiny())
    straight = TurnRiverSolver(game)
    straight.run(20)
    first = TurnRiverSolver(game)
    first.run(10)
    path = first.save_checkpoint(tmp_path / "turn.npz")
    resumed = TurnRiverSolver.load_checkpoint(path, turn_river_game(tiny()))
    resumed.run(10)
    for key in straight.turn_regret:
        np.testing.assert_array_equal(straight.turn_regret[key], resumed.turn_regret[key])
    for key in straight.river_strategy:
        np.testing.assert_array_equal(straight.river_strategy[key], resumed.river_strategy[key])
    with pytest.raises(CheckpointMismatch):
        TurnRiverSolver.load_checkpoint(path, turn_river_game(tiny(stacks=[400, 400])))


def test_spliced_independent_rivers_are_not_a_turn_equilibrium():
    game = turn_river_game(tiny(ranges=[{"sample": 10, "seed": 1}, {"sample": 10, "seed": 2}]))
    joint = TurnRiverSolver(game)
    joint.run(150)
    joint_expl = evaluate_turn_profile(game, joint.average_profile())["exploitability_pct_pot"]
    rivers = TurnRiverSolver(game).solve_rivers_with_prior_ranges(150)
    turn_only = TurnRiverSolver(game, frozen_river=rivers)
    turn_only.run(150)
    spliced = evaluate_turn_profile(game, {"turn": turn_only.average_profile()["turn"], "river": rivers})
    assert spliced["exploitability_pct_pot"] > 3 * joint_expl + 0.05


def test_solve_turn_cli_report(tmp_path):
    config = tmp_path / "turn.json"
    config.write_text(json.dumps(tiny(solver={"algorithm": "dcfr", "iterations": 40})))
    main(["solve-turn", str(config), "--output", str(tmp_path / "run"), "--eval-every", "20", "--lp-limit", "3"])
    report = json.loads((tmp_path / "run" / "report.json").read_text())
    assert [t["iteration"] for t in report["trajectory"]] == [20, 40]
    assert report["lp_check"]["value0"] == pytest.approx(report["lp_check"]["value0_dual"], abs=1e-6)
    assert report["subgame"]["turn_max_raises"] == 1 and report["subgame"]["river_max_raises"] == 1
    assert report["subgame"]["abstraction"]["max_raises"] == {"turn": 1, "river": 1}
    assert "no sampling" in report["subgame"]["river_cards"]
    assert (tmp_path / "run" / "average_strategy.npz").exists()
    assert report["turn_frequencies"][0]["history"] == [] and report["turn_frequencies"][0]["player"] == "OOP"
    main(["solve-turn", str(config), "--output", str(tmp_path / "run2"), "--iterations", "10",
          "--resume", str(tmp_path / "run" / "checkpoint.npz"), "--lp-limit", "0"])
    second = json.loads((tmp_path / "run2" / "report.json").read_text())
    assert second["solver"]["iterations_total"] == 50


def test_inclusion_exclusion_matches_dense_masses_values_and_best_response():
    dense = turn_river_game(tiny(showdown="dense"))
    ie = turn_river_game(tiny(showdown="inclusion_exclusion"))
    assert dense.fingerprint == ie.fingerprint                 # the backend is not part of the game
    assert (dense.description["showdown"], ie.description["showdown"]) == ("dense", "inclusion_exclusion")
    rng = np.random.default_rng(5)
    for p in (0, 1):
        ro = rng.random((len(dense.river_cards), dense.size(1 - p))) * dense.masks[1 - p]
        for need_win in (False, True):
            (cd, wd), (ci, wi) = (g.showdown.river_masses(p, ro, need_win) for g in (dense, ie))
            np.testing.assert_allclose(ci, cd, atol=1e-12)
            if need_win:
                np.testing.assert_allclose(wi, wd, atol=1e-12)
        r = rng.random(dense.size(1 - p))
        np.testing.assert_allclose(ie.showdown.turn_masses(p, r), dense.showdown.turn_masses(p, r), atol=1e-12)
    solver = TurnRiverSolver(dense)
    for seed in range(2):
        profile = random_profile(solver, seed)
        a, b = evaluate_turn_profile(dense, profile), evaluate_turn_profile(ie, profile)
        assert b["value"] == pytest.approx(a["value"], abs=1e-9)
        assert b["best_response_value"] == pytest.approx(a["best_response_value"], abs=1e-9)


def test_inclusion_exclusion_cfr_converges_to_the_joint_lp():
    game = turn_river_game(tiny(showdown="inclusion_exclusion"))
    lp = solve_turn_sequence_form(game)                        # scalar oracle, independent of the backend
    solver = TurnRiverSolver(game, SolverConfig("dcfr"))
    solver.run(400)
    result = evaluate_turn_profile(game, solver.average_profile())
    assert result["exploitability_pct_pot"] < 0.01
    assert abs(result["value"][0] - lp["value0"]) <= result["nash_conv_chips"] + 1e-6


def test_auto_showdown_switches_to_inclusion_exclusion_above_the_dense_limit(monkeypatch):
    monkeypatch.setattr(turn_module, "DENSE_TURN_LIMIT", 4)    # 3 x 3 hands exceed it
    assert turn_river_game(tiny()).description["showdown"] == "inclusion_exclusion"
    with pytest.raises(ValueError, match="too large for the dense"):
        turn_river_game(tiny(showdown="dense"))


def test_worker_threads_give_bitwise_identical_cfr_state():
    runs = []
    for workers in (1, 3):
        game = turn_river_game(tiny(showdown="inclusion_exclusion"))
        solver = TurnRiverSolver(game, SolverConfig("dcfr"), workers=workers)
        assert solver.workers == workers
        solver.run(6)
        runs.append(solver)
    for attr in ("turn_regret", "turn_strategy", "river_regret", "river_strategy"):
        a, b = getattr(runs[0], attr), getattr(runs[1], attr)
        for key in a:
            np.testing.assert_array_equal(a[key], b[key])
