import random

import numpy as np
import pytest

from pokerlab.plo.cards import all_hands, parse_cards
from pokerlab.plo.engine import RIVER, Action, ActionType, TableRules, deal_hand
from pokerlab.plo.evaluator import plo_rank_batch
from pokerlab.plo.subgame.cfr import (
    ALGORITHMS, CFRSolver, CheckpointMismatch, SolverConfig, evaluate_profile,
)
from pokerlab.plo.subgame.instance import KUHN_VALUE_P0, dense_from_outcomes, kuhn_instance, plo_river_instance
from pokerlab.plo.subgame.policy import RiverResolver, SubgamePolicy
from pokerlab.plo.subgame.reference import (
    best_response_reference, profile_value_reference, solve_sequence_form,
)
from pokerlab.plo.subgame.showdown import DenseShowdown, InclusionExclusionShowdown
from pokerlab.plo.subgame.tree import DECISION, BettingConfig, BettingTree


def tiny(board="Ks9h7d4c2s", seeds=(1, 2), n=7, **extra):
    spec = {"board": board, "pot": 1000, "stacks": [3000, 3000], "big_blind": 100,
            "ranges": [{"sample": n, "seed": seeds[0]}, {"sample": n, "seed": seeds[1]}],
            "bet_sizes": [0.5, 1.0], "raise_sizes": [1.0], "max_raises": 2}
    spec.update(extra)
    return spec


def random_profile(inst, seed):
    rng = np.random.default_rng(seed)
    profile = {}
    for nid in inst.tree.decision_nodes():
        node = inst.tree.nodes[nid]
        x = rng.random((inst.size(node.player), len(node.children))) ** 3
        profile[nid] = x / x.sum(axis=1, keepdims=True)
    return profile


# ------------------------------------------------------------------- tree
def test_tree_sizes_respect_pot_limit_min_raise_and_raise_cap():
    cfg = BettingConfig(pot=700, stacks=(5_000, 9_000), bet_sizes=(0.25, 0.6, 1.0),
                        raise_sizes=(0.4, 1.0), max_raises=3, min_bet=100)
    tree = BettingTree(cfg)
    stack = cfg.effective_stack
    for node in tree.nodes:
        if node.kind != DECISION:
            continue
        pot_total = cfg.pot + sum(node.commit)
        to_call = node.current_bet - node.commit[node.player]
        increments = [0]
        for label in node.history:
            if label.startswith(("bet:", "raise:")):
                increments.append(int(label.split(":")[1]))
        last_increment = max(cfg.min_bet, max(b - a for a, b in zip(increments, increments[1:])) if
                             len(increments) > 1 else cfg.min_bet)
        for label in node.actions:
            if label.startswith("bet:"):
                amount = int(label.split(":")[1])
                assert to_call == 0 and amount <= min(pot_total, stack)
                assert amount >= cfg.min_bet or amount == stack
            elif label.startswith("raise:"):
                to = int(label.split(":")[1])
                assert to <= node.current_bet + pot_total + to_call and to <= stack
                assert to >= node.current_bet + last_increment or to == stack
                assert node.raises < cfg.max_raises
    assert tree.summary()["decision"] > 10


def test_tree_never_offers_a_bet_below_the_minimum_unless_all_in():
    tree = BettingTree(BettingConfig(pot=50, stacks=(1_000, 1_000), bet_sizes=(0.5, 1.0), min_bet=100))
    assert tree.targets((0, 0), 0, 0, 100) == [100]
    assert [a for a in tree.nodes[0].actions if a.startswith("bet:")] == ["bet:100"]
    short = BettingTree(BettingConfig(pot=50, stacks=(60, 1_000), bet_sizes=(1.0,), min_bet=100))
    assert short.targets((0, 0), 0, 0, 100) == [60]   # a short all-in may be below the minimum


def _river_state(stack=10_000):
    s = deal_hand(TableRules(50, 100), [stack, stack], 0, random.Random(3))
    s.apply(Action.call())
    s.apply(Action.check())
    while s.street < RIVER:
        s.apply(Action.check())
    return s


def test_tree_actions_are_legal_in_the_engine_and_hit_the_pot_limit():
    river = _river_state()
    assert river.pot == 200 and river.to_act == 1
    cfg = BettingConfig(pot=200, stacks=(9_900, 9_900), bet_sizes=(0.33, 0.75, 1.0),
                        raise_sizes=(0.5, 1.0), max_raises=3, min_bet=100)
    tree = BettingTree(cfg)
    seat_of = {0: 1, 1: 0}   # tree OOP = big blind seat 1, tree IP = button seat 0
    paths = 0
    for node in tree.nodes:
        if node.kind != DECISION:
            continue
        state = _river_state()
        current = tree.nodes[0]
        for label in node.history:
            state.apply(_engine_action(label, state))
            current = tree.nodes[current.children[current.actions.index(label)]]
        assert state.to_act == seat_of[node.player]
        legal = state.legal_actions()
        aggressive = [int(a.split(":")[1]) for a in node.actions if ":" in a]
        if aggressive:
            assert max(aggressive) == legal.max_to   # 1.0 pot size included, so the tree reaches the cap
        for label in node.actions:
            legal.validate(_engine_action(label, state))
        paths += 1
    assert paths == tree.summary()["decision"]


def _engine_action(label, state):
    if label == "check":
        return Action.check()
    if label == "call":
        return Action.call()
    if label == "fold":
        return Action.fold()
    kind, amount = label.split(":")
    return Action(ActionType.BET if kind == "bet" else ActionType.RAISE, int(amount))


# ---------------------------------------------------------------- solvers
@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_kuhn_poker_value(algorithm):
    inst = kuhn_instance()
    solver = CFRSolver(inst, SolverConfig(algorithm=algorithm, seed=3))
    solver.run(20_000 if algorithm == "es-mccfr" else 1_500)
    result = evaluate_profile(inst, solver.average_profile())
    tolerance = 5e-3 if algorithm == "es-mccfr" else 1e-3
    assert result["value"][0] == pytest.approx(KUHN_VALUE_P0, abs=tolerance)
    assert 0 <= result["exploitability_chips"] < (1e-2 if algorithm == "es-mccfr" else 1e-3)


def test_kuhn_reports_net_value_and_offset_free_exploitability():
    inst = kuhn_instance()
    solver = CFRSolver(inst, SolverConfig("dcfr"))
    solver.run(3_000)
    result = evaluate_profile(inst, solver.average_profile())
    # Utilities count from after the antes (sunk pot 2): player 0 is worth 17/18 there,
    # i.e. -1/18 once its own ante of 1 = pot/2 is subtracted.
    assert result["value"][0] == pytest.approx(17 / 18, abs=1e-3)
    assert result["value_net_of_equal_sunk_share"][0] == pytest.approx(-1 / 18, abs=1e-3)
    zero_sum_br = [b - inst.pot / 2 for b in result["best_response_value"]]
    assert result["exploitability_chips"] == pytest.approx(sum(zero_sum_br) / 2, abs=1e-12)
    assert result["nash_conv_chips"] == pytest.approx(2 * result["exploitability_chips"], abs=1e-12)


@pytest.mark.parametrize("board,seeds", [("Ks9h7d4c2s", (1, 2)), ("Ah8h8d5c2h", (5, 6))])
def test_cfr_converges_to_the_sequence_form_lp_value(board, seeds):
    inst = plo_river_instance(tiny(board, seeds))
    lp = solve_sequence_form(inst)
    assert lp["value0"] == pytest.approx(lp["value0_dual"], abs=1e-6)
    assert evaluate_profile(inst, lp["profile"])["exploitability_chips"] < 1e-6
    for algorithm in ("dcfr", "cfr+"):
        solver = CFRSolver(inst, SolverConfig(algorithm=algorithm))
        solver.run(2_000)
        result = evaluate_profile(inst, solver.average_profile())
        assert result["exploitability_pct_pot"] < 0.01
        assert abs(result["value"][0] - lp["value0"]) <= result["nash_conv_chips"] + 1e-6  # both lie in [pot-BR1, BR0]


def test_fast_best_response_matches_independent_reference():
    for board, seeds in (("Ks9h7d4c2s", (1, 2)), ("Ah8h8d5c2h", (3, 4))):
        inst = plo_river_instance(tiny(board, seeds, n=6))
        for seed in range(3):
            profile = random_profile(inst, seed)
            fast = evaluate_profile(inst, profile)
            for p in (0, 1):
                assert fast["best_response_value"][p] == pytest.approx(
                    best_response_reference(inst, profile, p), abs=1e-9)
                assert fast["value"][p] == pytest.approx(profile_value_reference(inst, profile, p), abs=1e-9)
            assert fast["exploitability_chips"] >= -1e-9
            assert fast["constant_sum_check"] == pytest.approx(0.0, abs=1e-9)


def test_vectorised_showdown_matches_scalar_oracle():
    inst = plo_river_instance(tiny("Ah8h8d5c2h", (7, 8), n=25))
    reference = dense_from_outcomes(inst)
    np.testing.assert_array_equal(reference.compat, inst.showdown.compat)
    np.testing.assert_array_equal(reference.win0, inst.showdown.win0)


def test_inclusion_exclusion_matches_dense_masses():
    board = parse_cards("Ah8h8d5c2h")
    pool = all_hands(4, board)
    rng = np.random.default_rng(1)
    h0 = pool[np.sort(rng.choice(len(pool), 400, replace=False))]
    h1 = pool[np.sort(rng.choice(len(pool), 350, replace=False))]
    s0, s1 = plo_rank_batch(h0, board), plo_rank_batch(h1, board)
    dense = DenseShowdown.from_hands(h0, s0, h1, s1)
    ie = InclusionExclusionShowdown(h0, s0, h1, s1)
    for _ in range(4):
        for p, n_opp in ((0, len(h1)), (1, len(h0))):
            reach = rng.random(n_opp) * (rng.random(n_opp) < 0.6)
            for a, b in zip(dense.masses(p, reach), ie.masses(p, reach)):
                np.testing.assert_allclose(a, b, atol=1e-9)
            j = int(rng.integers(n_opp))
            for a, b in zip(dense.versus(p, j), ie.versus(p, j)):
                np.testing.assert_array_equal(a, b)


def test_dense_and_inclusion_exclusion_solvers_agree():
    profiles = []
    for kind in ("dense", "inclusion_exclusion"):
        solver = CFRSolver(plo_river_instance(tiny(n=60, showdown=kind)), SolverConfig("dcfr"))
        solver.run(50)
        profiles.append(solver.average_profile())
    for nid in profiles[0]:
        np.testing.assert_allclose(profiles[0][nid], profiles[1][nid], atol=1e-9)


@pytest.mark.parametrize("algorithm", ["dcfr", "cfr+", "es-mccfr"])
def test_checkpoint_resume_is_bitwise_identical(tmp_path, algorithm):
    inst = plo_river_instance(tiny(n=20))
    config = SolverConfig(algorithm=algorithm, seed=9)
    straight = CFRSolver(inst, config)
    straight.run(40)
    first = CFRSolver(inst, config)
    first.run(20)
    path = first.save_checkpoint(tmp_path / "ckpt.npz")
    resumed = CFRSolver.load_checkpoint(path, plo_river_instance(tiny(n=20)))
    assert resumed.iteration == 20
    resumed.run(20)
    for nid in straight.regret:
        np.testing.assert_array_equal(straight.regret[nid], resumed.regret[nid])
        np.testing.assert_array_equal(straight.strategy_sum[nid], resumed.strategy_sum[nid])
    assert straight.rng.bit_generator.state == resumed.rng.bit_generator.state


def test_checkpoint_rejects_a_different_subgame(tmp_path):
    solver = CFRSolver(plo_river_instance(tiny()), SolverConfig())
    solver.run(2)
    path = solver.save_checkpoint(tmp_path / "ckpt.npz")
    with pytest.raises(CheckpointMismatch):
        CFRSolver.load_checkpoint(path, plo_river_instance(tiny(seeds=(1, 3))))
    with pytest.raises(CheckpointMismatch):
        CFRSolver.load_checkpoint(path, plo_river_instance(tiny(bet_sizes=[0.75])))


def test_mccfr_seed_controls_sampling():
    inst = plo_river_instance(tiny(n=15))
    runs = []
    for seed in (1, 1, 2):
        solver = CFRSolver(inst, SolverConfig("es-mccfr", seed=seed))
        solver.run(200)
        runs.append(solver.strategy_sum[0].copy())
    np.testing.assert_array_equal(runs[0], runs[1])
    assert not np.array_equal(runs[0], runs[2])


def test_policy_query_and_frequencies():
    policy = RiverResolver(SolverConfig("dcfr")).resolve(tiny(), 300)
    hand = policy.inst.labels[0][0]
    answer = policy.query((), hand)
    assert answer["player"] == 0 and sum(answer["actions"].values()) == pytest.approx(1.0)
    shuffled = hand[4:] + hand[:4]
    assert policy.query((), shuffled)["actions"] == answer["actions"]
    with pytest.raises(KeyError):
        policy.query((), "AsKsQsJs" if "As" not in policy.inst.description["board"] else "AhKhQhJh")
    with pytest.raises(KeyError):
        policy.query(("check", "check"), hand)
    ip = policy.frequencies(("check",))
    assert ip["player"] == 1 and sum(ip["actions"].values()) == pytest.approx(1.0)
    assert isinstance(SubgamePolicy.from_solver(CFRSolver(policy.inst)).query((), hand)["actions"], dict)
