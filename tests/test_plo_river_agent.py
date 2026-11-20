import random

import numpy as np
import pytest

from pokerlab.plo.agents import BaseAgent, preflop_score
from pokerlab.plo.baseline import (
    BaselineAgent, BaselinePolicy, category_of_action, every_hand, hand_strength, preflop_scores,
)
from pokerlab.plo.engine import RIVER, Action, HandState, TableRules, deal_hand, observe
from pokerlab.plo.evaluate import evaluate_match
from pokerlab.plo.public import replay
from pokerlab.plo.river_agent import SolverRiverAgent, posterior_log_weights
from pokerlab.plo.session import play_hand

FAST = {"range_samples": 30, "iterations": 30, "max_raises": 1}
RULES = TableRules(50, 100)


class Recorder(BaseAgent):
    """Wraps an agent and keeps every observation it was given."""

    def __init__(self, inner):
        self.inner, self.seen = inner, []

    def act(self, obs):
        self.seen.append(obs)
        return self.inner.act(obs)


class PassiveThenOffTree(BaseAgent):
    """Checks/calls before the river; on the river bets min + 7 chips when it can, else calls."""

    def act(self, obs):
        legal = obs.legal
        if obs.street == RIVER and legal.can_check and legal.can_raise and legal.min_to + 7 <= legal.max_to:
            return Action(legal.raise_type, legal.min_to + 7)
        return Action.check() if legal.can_check else Action.call()


def play(hero, villain, hands, seed=0):
    for hid in range(hands):
        state = deal_hand(RULES, [10_000, 10_000], hid % 2, random.Random(seed * 1000 + hid), hand_id=hid)
        play_hand(state, [hero, villain] if hid % 2 == 0 else [villain, hero])


def test_preflop_vectorisation_matches_the_scalar_heuristic():
    hands = every_hand()[np.random.default_rng(1).choice(270_725, 2_000, replace=False)]
    assert np.allclose(preflop_scores(hands), [preflop_score(tuple(int(c) for c in h)) for h in hands])


def test_baseline_probabilities_are_valid_and_floored():
    policy = BaselinePolicy()
    s = np.linspace(0, 1, 11)
    for street in (0, 1, 3):
        for facing, can_raise in ((True, True), (True, False), (False, True), (False, False)):
            p = policy.category_probs(street, facing, can_raise, s)
            assert np.allclose(p.sum(axis=1), 1.0)
            assert (p[:, 0] == 0).all() if not facing else (p[:, 0] >= policy.eps / 2).all()
            assert (p[:, 2] == 0).all() if not can_raise else (p[:, 2] > 0).all()


def test_river_agent_plays_legally_and_logs_its_inputs():
    hero = SolverRiverAgent(seed=3, river=FAST)
    play(hero, BaselineAgent(seed=4), hands=40, seed=1)
    river = [d for d in hero.decisions if d["source"] == "river-solver"]
    early = [d for d in hero.decisions if d["source"] != "river-solver"]
    assert river and early and all(d["source"] == "baseline-v1" for d in early)
    first = [d for d in river if "solve" in d]
    assert first
    for d in first:
        assert d["early_street_policy"] == "baseline-v1" and "unsafe" in d["scope"]
        assert {"prior", "model", "players"} <= set(d["range_update"])
        assert d["solve"]["abstraction"]["bet_sizes_pot_fraction"] == ["1/3", "1/2", "2/3", "1"]
        assert d["solve"]["exploitability_pct_pot"] >= 0
        assert {"ranges", "solve", "query", "total_decision"} <= set(d["latency_ms"])
        assert sum(d["probabilities"].values()) == pytest.approx(1.0)


def test_posterior_is_the_product_of_baseline_likelihoods():
    recorder = Recorder(SolverRiverAgent(seed=5, river=FAST))
    play(recorder, BaselineAgent(seed=6), hands=40, seed=2)
    obs = next(o for o in recorder.seen if o.street == RIVER)
    rep = replay(obs)
    board = tuple(obs.board)
    hands = every_hand()
    candidates = hands[~np.isin(hands, np.asarray(board)).any(axis=1)]
    assert len(candidates) == 178_365
    villain = 1 - obs.seat
    policy = BaselinePolicy()
    logw, steps = posterior_log_weights(policy, rep.decisions, villain, board, candidates)
    sizes = (0, 3, 4, 5)
    for i in np.random.default_rng(0).choice(len(candidates), 5, replace=False):
        expected = 0.0
        for d in rep.decisions:
            if d.seat == villain and d.street < RIVER:
                s = hand_strength(d.street, board[:sizes[d.street]], candidates[i:i + 1])
                expected += np.log(policy.category_probs(d.street, d.facing_bet, d.can_raise, s)[0,
                                                         category_of_action(d.action)])
        assert logw[i] == pytest.approx(expected, abs=1e-9)
    assert len(steps) == sum(d.seat == villain and d.street < RIVER for d in rep.decisions)


def test_off_tree_river_bet_triggers_a_re_solve_and_a_legal_reply():
    hero = SolverRiverAgent(seed=7, river=FAST)
    for hid in range(60):
        # hero is the button (in position); the villain checks/calls, then bets min + 7 on the river
        state = deal_hand(RULES, [10_000, 10_000], 0, random.Random(5_000 + hid), hand_id=hid)
        play_hand(state, [hero, PassiveThenOffTree()])
        if any(str(d.get("resolve_reason", "")).startswith("opponent action bet:") for d in hero.decisions):
            break
    resolved = [d for d in hero.decisions if str(d.get("resolve_reason", "")).startswith("opponent action")]
    assert resolved
    assert resolved[0]["solve"]["tree"]["root"]["current_bet"] > 0


class PassiveThenPot(BaseAgent):
    """Checks/calls before the river; on the river bets the maximum when it can, else calls."""

    def act(self, obs):
        legal = obs.legal
        if obs.street == RIVER and legal.can_check and legal.can_raise:
            return Action(legal.raise_type, legal.max_to)
        return Action.check() if legal.can_check else Action.call()


def test_opponent_bet_larger_than_our_stack_maps_to_the_all_in_branch():
    hero = SolverRiverAgent(seed=13, river=FAST)
    seen = 0
    for hid in range(80):
        # hero (button, in position) is short; the deep villain pot-bets the river
        state = deal_hand(RULES, [600, 20_000], 0, random.Random(9_000 + hid), hand_id=hid)
        play_hand(state, [hero, PassiveThenPot()])
        hero_in = sum(p.amount for p in state.posts if p.seat == 0) + sum(
            r.added for r in state.history if r.seat == 0 and r.street < RIVER)
        river_bets = [r for r in state.history if r.street == RIVER and r.seat == 1 and r.type.value == "bet"]
        if river_bets and river_bets[0].to > 600 - hero_in:
            seen += 1
    assert seen > 0
    assert any(d["source"] == "river-solver" for d in hero.decisions)


def test_decisions_depend_only_on_the_observation():
    recorder = Recorder(SolverRiverAgent(seed=9, river=FAST))
    play(recorder, BaselineAgent(seed=10), hands=40, seed=3)
    obs = next(o for o in recorder.seen if o.street == RIVER)
    # Same public history and own cards, different hidden opponent cards: identical observation.
    used = set(obs.hole_cards) | set(obs.board)
    spare = [c for c in range(52) if c not in used][::-1]
    holes = [tuple(obs.hole_cards) if s == obs.seat else tuple(spare[:4]) for s in range(2)]
    alt = HandState(RULES, obs.starting_stacks, obs.button, holes, tuple(obs.board), hand_id=obs.hand_id)
    for record in obs.history:
        alt.apply(Action(record.type, record.to))
    alt_obs = observe(alt, obs.seat)
    assert alt_obs == obs
    a, b = SolverRiverAgent(seed=9, river=FAST), SolverRiverAgent(seed=9, river=FAST)
    assert a.act(obs) == b.act(alt_obs)
    assert a.decisions[0]["range_update"] == b.decisions[0]["range_update"]


def test_river_agent_is_heads_up_only():
    state = deal_hand(RULES, [10_000] * 3, 0, random.Random(1))
    with pytest.raises(ValueError):
        SolverRiverAgent(river=FAST).act(observe(state, state.to_act))


def test_match_report_summarises_decisions_and_depth():
    report = evaluate_match({
        "kind": "match", "players": 2, "starting_stacks_bb": [100, 100], "format": "duplicate",
        "deals": 8, "seed": 4,
        "agents": [{"type": "river_solver", "seed": 1, "river": FAST}, {"type": "baseline", "seed": 2}]})
    summary = report["results"][0]["decision_summary"]
    assert summary["decisions_by_source"]["baseline-v1"] > 0
    assert "strategy_trained_or_validated_at" in report["depth"]
    assert any("misspecified" in c for c in report["caveats"])
    assert sum(r["net_chips"] for r in report["results"]) == 0
