"""Card removal with non-uniform, asymmetric ranges (not covered by uniform full-range checks).

Every pair of hands sharing a card must get zero joint probability; the joint deal
distribution is proportional to w0(i) * w1(j) over disjoint pairs only.  Each oracle
is compared against a brute-force enumeration with the scalar evaluator.
"""
from itertools import product

import numpy as np
import pytest

from pokerlab.plo.cards import parse_cards
from pokerlab.plo.evaluator import plo_rank_batch, plo_rank_reference
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile
from pokerlab.plo.subgame.instance import plo_river_instance
from pokerlab.plo.subgame.reference import (
    best_response_reference, profile_value_reference, solve_sequence_form,
)
from pokerlab.plo.subgame.showdown import DenseShowdown, InclusionExclusionShowdown

BOARD = "Ah Kh 7d 4c 2s"
OOP = {"AsAdKsKd": 4.0, "AsQsJsTs": 1.0, "QdQcJdJc": 2.0, "9s8s6d5d": 0.5, "AcKcQhJh": 3.0}
IP = {"AsKdQdJd": 2.0, "AdAcKsKc": 1.0, "QsQcTdTc": 5.0, "6s6c5s5c": 0.25, "JsJh9h8h": 1.5,
      "Th9c8d3h": 0.75}


def spec(**extra):
    base = {"board": BOARD, "pot": 1000, "stacks": [3000, 3000], "big_blind": 100,
            "ranges": [{"hands": list(OOP), "weights": list(OOP.values())},
                       {"hands": list(IP), "weights": list(IP.values())}],
            "bet_sizes": ["1/2", "1"], "raise_sizes": ["1"], "max_raises": 1}
    base.update(extra)
    return base


def brute_force_joint():
    board = parse_cards(BOARD)
    joint = {}
    for (a, wa), (b, wb) in product(OOP.items(), IP.items()):
        ha, hb = parse_cards(a), parse_cards(b)
        if set(ha) & set(hb):
            continue
        ra, rb = plo_rank_reference(ha, board), plo_rank_reference(hb, board)
        joint[(a, b)] = (wa * wb, 1.0 if ra > rb else 0.5 if ra == rb else 0.0)
    total = sum(w for w, _ in joint.values())
    return {k: (w / total, share) for k, (w, share) in joint.items()}


def test_shared_cards_get_zero_probability_and_the_joint_is_normalised():
    joint = brute_force_joint()
    assert ("AsAdKsKd", "AsKdQdJd") not in joint            # share As, Kd
    assert ("QdQcJdJc", "QsQcTdTc") not in joint            # share Qc
    assert ("9s8s6d5d", "6s6c5s5c") in joint                 # no shared card
    assert sum(p for p, _ in joint.values()) == pytest.approx(1.0)
    assert len(joint) < len(OOP) * len(IP)


def test_dense_and_inclusion_exclusion_match_brute_force_with_weighted_reach():
    board = parse_cards(BOARD)
    h0 = np.array([sorted(parse_cards(h)) for h in OOP])
    h1 = np.array([sorted(parse_cards(h)) for h in IP])
    s0, s1 = plo_rank_batch(h0, board), plo_rank_batch(h1, board)
    w0, w1 = np.array(list(OOP.values())), np.array(list(IP.values()))
    oracles = (DenseShowdown.from_hands(h0, s0, h1, s1), InclusionExclusionShowdown(h0, s0, h1, s1))
    for player, (mine, theirs, reach) in enumerate(((OOP, IP, w1), (IP, OOP, w0))):
        expected_compat, expected_win = [], []
        for a in mine:
            ha = parse_cards(a)
            compat = win = 0.0
            for (b, r) in zip(theirs, reach):
                hb = parse_cards(b)
                if set(ha) & set(hb):
                    continue
                ra, rb = plo_rank_reference(ha, board), plo_rank_reference(hb, board)
                compat += r
                win += r * (1.0 if ra > rb else 0.5 if ra == rb else 0.0)
            expected_compat.append(compat)
            expected_win.append(win)
        for oracle in oracles:
            compat, win = oracle.masses(player, reach)
            np.testing.assert_allclose(compat, expected_compat, atol=1e-12)
            np.testing.assert_allclose(win, expected_win, atol=1e-12)


def test_values_use_the_weighted_joint_distribution():
    inst = plo_river_instance(spec())
    joint = brute_force_joint()
    # Profile where everybody checks: value0 = pot * P(player 0 wins the showdown).
    profile = {}
    for nid in inst.tree.decision_nodes():
        node = inst.tree.nodes[nid]
        probs = np.zeros(len(node.actions))
        probs[node.actions.index("check" if "check" in node.actions else "call")] = 1.0
        profile[nid] = np.tile(probs, (inst.size(node.player), 1))
    expected = inst.pot * sum(p * share for p, share in joint.values())
    assert evaluate_profile(inst, profile)["value"][0] == pytest.approx(expected, abs=1e-9)
    assert profile_value_reference(inst, profile, 0) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("showdown", ["dense", "inclusion_exclusion"])
def test_best_response_lp_and_cfr_agree_on_weighted_asymmetric_ranges(showdown):
    inst = plo_river_instance(spec(showdown=showdown))
    rng = np.random.default_rng(4)
    for _ in range(3):
        profile = {}
        for nid in inst.tree.decision_nodes():
            node = inst.tree.nodes[nid]
            x = rng.random((inst.size(node.player), len(node.children)))
            profile[nid] = x / x.sum(axis=1, keepdims=True)
        fast = evaluate_profile(inst, profile)
        for p in (0, 1):
            assert fast["best_response_value"][p] == pytest.approx(
                best_response_reference(inst, profile, p), abs=1e-9)
    lp = solve_sequence_form(inst)
    solver = CFRSolver(inst, SolverConfig("dcfr"))
    solver.run(3000)
    result = evaluate_profile(inst, solver.average_profile())
    assert result["exploitability_pct_pot"] < 0.01
    assert abs(result["value"][0] - lp["value0"]) <= result["nash_conv_chips"] + 1e-6  # both lie in [pot-BR1, BR0]
