"""Four-street blueprint: preflop tree, street chaining, ES-MCCFR checkpoints, buckets, policy and agents."""
import random

import numpy as np
import pytest

from pokerlab.plo.baseline import BaselineAgent
from pokerlab.plo.blueprint import (
    PREFLOP, RIVER, TURN, BlueprintGame, BlueprintPolicy, BlueprintSpec, BlueprintTrainer, CoarseBuckets,
    IdentityBuckets, StreetSizes, coarse_hand_buckets,
)
from pokerlab.plo.blueprint_agent import BlueprintAgent
from pokerlab.plo.cards import parse_cards
from pokerlab.plo.engine import TURN as ENGINE_TURN, TableRules, deal_hand
from pokerlab.plo.evaluate import load_json
from pokerlab.plo.session import play_hand
from pokerlab.plo.subgame.cfr import evaluate_profile
from pokerlab.plo.subgame.instance import plo_river_instance
from pokerlab.plo.subgame.turn import turn_river_game
from pokerlab.plo.turn_agent import JointTurnRiverAgent

RULES = TableRules(50, 100)


@pytest.fixture(scope="module")
def coarse():
    return CoarseBuckets()


def test_preflop_tree_has_the_big_blind_option_and_pot_limit_sizes():
    game = BlueprintGame(BlueprintSpec())
    tree = game.trees[game.root]
    root = tree.nodes[0]
    assert root.player == 1 and root.actions == ("fold", "call", "raise:300")      # small blind first, pot = 3bb
    limp = tree.nodes[root.children[root.actions.index("call")]]
    assert limp.player == 0 and limp.actions == ("check", "raise:300")              # the big blind's option
    raised = tree.nodes[root.children[root.actions.index("raise:300")]]
    assert raised.actions == ("fold", "call", "raise:900")                          # h + P + 2c = 100 + 400 + 400
    sizes = game.build_all()
    assert all(sizes["decision_nodes"][s] > 0 for s in range(4))                   # every street is in the tree


def test_turn_subgame_tree_matches_the_exact_joint_solver():
    spec = load_json("examples/plo/turn_tiny_lp.json")
    exact = turn_river_game(spec)
    game = BlueprintGame(BlueprintSpec(stack=exact.effective_stack, start_street=TURN, pot=exact.pot,
                                       board=tuple(parse_cards(spec["board"])),
                                       postflop=StreetSizes(("1/3", "1/2", "2/3", "1"), ("1/3", "1/2", "2/3", "1"),
                                                            True, True, 2), turn_max_raises=1, river_max_raises=1))
    turn = game.trees[game.root]
    assert [n.actions for n in turn.nodes] == [n.actions for n in exact.turn_tree.nodes]
    for leaf_id, leaf in exact.leaves.items():
        nxt = game.next_street(game.root, turn.nodes[leaf_id])
        if leaf.tree is None:
            assert nxt is None
        else:
            assert [n.actions for n in game.trees[nxt].nodes] == [n.actions for n in leaf.tree.nodes]


def test_checkpoint_resume_is_bitwise_identical(tmp_path, coarse):
    game = BlueprintGame(BlueprintSpec())
    straight = BlueprintTrainer(game, coarse, seed=5)
    straight.iterate(30)
    first = BlueprintTrainer(game, coarse, seed=5)
    first.iterate(15)
    path = first.save(tmp_path / "bp.npz")
    resumed = BlueprintTrainer(game, coarse, seed=99)
    resumed.load(path)
    resumed.iterate(15)
    assert set(straight.regret) == set(resumed.regret)
    for k in straight.regret:
        np.testing.assert_array_equal(straight.regret[k], resumed.regret[k])
        np.testing.assert_array_equal(straight.strategy_sum[k], resumed.strategy_sum[k])


def test_vectorised_buckets_equal_per_deal_buckets(coarse):
    trainer = BlueprintTrainer(BlueprintGame(BlueprintSpec()), coarse, seed=2)
    for _ in range(40):
        hands, board = trainer._deal()
        buckets, _ = coarse.deal(hands, board, PREFLOP)
        for street in range(4):
            v = coarse_hand_buckets(coarse, street, board, np.array([sorted(hands[0]), sorted(hands[1])]))
            assert (int(v[0]), int(v[1])) == (buckets[(0, street)], buckets[(1, street)])
            assert 0 <= v.min() and v.max() < coarse.count(0, street)


def test_identity_es_mccfr_improves_on_a_river_subgame():
    spec = load_json("examples/plo/river_tiny_lp.json")
    exact = plo_river_instance(spec)
    game = BlueprintGame(BlueprintSpec(stack=3000, start_street=RIVER, pot=exact.pot,
                                       board=tuple(parse_cards(spec["board"])),
                                       postflop=StreetSizes(("1/3", "1/2", "2/3", "1"), ("1/3", "1/2", "2/3", "1"),
                                                            True, True, 2)))
    tree = game.trees[game.root]
    assert [n.actions for n in tree.nodes] == [n.actions for n in exact.tree.nodes]
    trainer = BlueprintTrainer(game, IdentityBuckets(exact.hands),
                               ranges=((exact.hands[0], exact.weights[0]), (exact.hands[1], exact.weights[1])), seed=1)

    def exploitability():
        prof = {}
        for nid in tree.decision_nodes():
            n = tree.nodes[nid]
            prof[nid] = (trainer.average(game.root, nid) if (game.root, nid) in trainer.strategy_sum
                         else np.full((exact.size(n.player), len(n.children)), 1.0 / len(n.children)))
        return evaluate_profile(exact, prof)["exploitability_pct_pot"]

    trainer.iterate(300)
    early = exploitability()
    trainer.iterate(2700)
    assert exploitability() < 0.5 * early


def test_blueprint_agents_play_legally_and_log(tmp_path, coarse):
    trainer = BlueprintTrainer(BlueprintGame(BlueprintSpec()), coarse, seed=4)
    trainer.iterate(150)
    path = trainer.save(tmp_path / "bp.npz")
    hero = BlueprintAgent(seed=1, checkpoint=str(path))
    joint = JointTurnRiverAgent(seed=2, turn_river={"range_samples": 8, "iterations": 10,
                                                    "river_fallback_iterations": 10}, early_policy=str(path))
    for hid in range(6):
        state = deal_hand(RULES, [2000, 2000], hid % 2, random.Random(40 + hid), hand_id=hid)
        play_hand(state, [hero, BaselineAgent(seed=3)] if hid % 2 == 0 else [BaselineAgent(seed=3), hero])
        state = deal_hand(RULES, [2000, 2000], hid % 2, random.Random(80 + hid), hand_id=hid)
        play_hand(state, [joint, hero] if hid % 2 == 0 else [hero, joint])
    assert hero.decisions and all(d["source"] == "blueprint-v0" for d in hero.decisions)
    early = [d for d in joint.decisions if d["street"] < ENGINE_TURN]
    assert early and all(d["source"] == "blueprint-v0" and not d["temporary_baseline"] for d in early)
    turn_solves = [s for d in joint.decisions for s in d.get("joint_solves_this_decision", [])]
    if turn_solves:
        assert "blueprint-v0" in turn_solves[0]["range_update"]["model"]
