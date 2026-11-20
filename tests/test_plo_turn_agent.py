"""Joint turn + river decisions: one solve per hand, the river read from the same solution, fallbacks logged."""
import random

import numpy as np

from pokerlab.plo.agents import BaseAgent
from pokerlab.plo.baseline import BaselineAgent
from pokerlab.plo.cards import parse_cards
from pokerlab.plo.engine import RIVER, TURN, Action, HandState, TableRules, deal_hand, observe
from pokerlab.plo.session import play_hand
from pokerlab.plo.turn_agent import JointTurnRiverAgent

RULES = TableRules(50, 100)
FAST = {"range_samples": 10, "iterations": 15, "river_fallback_iterations": 15}
HERO, VILLAIN = parse_cards("AsKsQdJd"), parse_cards("9c9d8c7h")
RUNOUT = parse_cards("Kh9h7d4c2s")


class Scripted(BaseAgent):
    """Fixed preflop/flop line (button raises, big blind calls; flop check, bet 2/3 pot, call), then delegates."""

    def __init__(self, later):
        self.later = later

    def act(self, obs):
        legal = obs.legal
        if obs.street >= TURN:
            return self.later.act(obs)
        if obs.street == 0:
            if legal.can_raise and obs.to_call > 0 and obs.seat == obs.button and not obs.history:
                return Action(legal.raise_type, 300)
            return Action.check() if legal.can_check else Action.call()
        if legal.can_check and obs.seat != obs.button:
            return Action.check()
        if legal.can_check:
            return Action(legal.raise_type, legal.min_to + (2 * obs.pot // 3 - legal.min_to))
        return Action.call()


class Passive(BaseAgent):
    def act(self, obs):
        return Action.check() if obs.legal.can_check else Action.call()


class OffTree(BaseAgent):
    """Bets min + 7 chips (outside the abstraction) on ``street`` when it can open, otherwise checks/calls."""

    def __init__(self, street):
        self.street = street

    def act(self, obs):
        legal = obs.legal
        if obs.street == self.street and legal.can_check and legal.can_raise and legal.min_to + 7 <= legal.max_to:
            return Action(legal.raise_type, legal.min_to + 7)
        return Action.check() if legal.can_check else Action.call()


def controlled_hand(hero_agent, villain_agent, hero_is_button=False, hand_id=1):
    """Hero is the big blind (out of position) unless ``hero_is_button``; cards and runout are fixed."""
    button = 0 if hero_is_button else 1
    holes = (HERO, VILLAIN)
    state = HandState(RULES, [10_000, 10_000], button, holes, RUNOUT, hand_id=hand_id)
    play_hand(state, [Scripted(hero_agent), Scripted(villain_agent)])
    return state


def joint(agent):
    return [d for d in agent.decisions if d["source"] == "joint-turn-river"]


def test_turn_and_river_come_from_one_joint_solution():
    hero = JointTurnRiverAgent(seed=3, turn_river=FAST)
    state = controlled_hand(hero, Passive())
    decisions = joint(hero)
    streets = [d["street"] for d in decisions]
    assert TURN in streets and RIVER in streets
    assert len({d["joint_solve_id"] for d in decisions}) == 1               # one solve for the hand
    assert len(decisions[0]["joint_solves_this_decision"]) == 1
    assert all(not d["joint_solves_this_decision"] for d in decisions[1:])
    assert all(d["joint_strategy_in_force"] and not d["fallbacks"] for d in decisions)
    ctx = hero._ctx
    for d in decisions:                                                     # recorded = solved probabilities
        look = d["strategy_lookup"]
        if look["street"] == "turn":
            nid = ctx.game.turn_tree.find(look["turn_path"])
            expected = ctx.profile["turn"][nid][look["hand_index"]]
        else:
            leaf = ctx.game.turn_tree.find(look["turn_path"])
            rid = ctx.game.leaves[leaf].tree.find(look["river_path"])
            expected = ctx.profile["river"][(leaf, rid)][look["river_card_index"], look["hand_index"]]
            assert ctx.game.river_cards[look["river_card_index"]] == RUNOUT[4]
        assert np.allclose(list(d["probabilities"].values()), expected)
    solve = decisions[0]["joint_solves_this_decision"][0]
    assert solve["river_cards"].startswith("all 48") and solve["range_sizes"][0] >= 2
    assert state.result is not None


def test_off_tree_turn_bet_re_solves_the_joint_game():
    hero = JointTurnRiverAgent(seed=5, turn_river=FAST)
    controlled_hand(hero, OffTree(TURN), hero_is_button=True)              # villain opens the turn off-tree
    decisions = joint(hero)
    assert decisions and decisions[0]["fallbacks"][0]["kind"] == "turn_resolve"
    solves = decisions[0]["joint_solves_this_decision"]                    # root solve, then the re-solve
    assert [s["reason"].split()[0] for s in solves] == ["first", "off-tree"]
    assert solves[1]["turn_root"]["current_bet"] > 0 and decisions[0]["joint_solve_id"] == solves[1]["id"]
    rivers = [d for d in decisions if d["street"] == RIVER]
    if rivers:                                                              # the river reads the re-solved joint game
        assert rivers[0]["joint_solve_id"] == decisions[0]["joint_solve_id"]


def test_off_tree_river_bet_falls_back_and_says_so():
    for hand_id in range(1, 6):
        hero = JointTurnRiverAgent(seed=hand_id, turn_river=FAST)
        controlled_hand(hero, OffTree(RIVER), hero_is_button=True, hand_id=hand_id)
        fallback = [d for d in hero.decisions if d["source"].startswith("river-fallback")]
        if fallback:
            break
    assert fallback, "the hero never faced an off-tree river bet in five controlled hands"
    assert fallback[0]["joint_strategy_in_force"] is False
    assert fallback[0]["fallbacks"][0]["kind"] == "river_resolve"
    assert "river_resolve" in fallback[0]


def test_decisions_depend_only_on_the_observation():
    holder = {}

    class Grab(BaseAgent):
        def act(self, obs):
            if obs.street == TURN and "obs" not in holder:
                holder["obs"] = obs
            return Passive().act(obs)

    controlled_hand(Grab(), Passive())
    obs = holder["obs"]
    used = set(obs.hole_cards) | set(obs.board)
    spare = [c for c in range(52) if c not in used][::-1]
    holes = [tuple(obs.hole_cards) if s == obs.seat else tuple(spare[:4]) for s in range(2)]
    alt = HandState(RULES, obs.starting_stacks, obs.button, holes, tuple(obs.board) + (spare[5],), hand_id=obs.hand_id)
    for record in obs.history:
        alt.apply(Action(record.type, record.to))
    alt_obs = observe(alt, obs.seat)
    assert alt_obs == obs
    a, b = JointTurnRiverAgent(seed=2, turn_river=FAST), JointTurnRiverAgent(seed=2, turn_river=FAST)
    assert a.act(obs) == b.act(alt_obs)
    assert a.decisions[0]["probabilities"] == b.decisions[0]["probabilities"]


def test_full_hands_label_baseline_streets_and_play_legally():
    hero = JointTurnRiverAgent(seed=11, turn_river=FAST)
    villain = BaselineAgent(seed=12)
    for hid in range(6):
        state = deal_hand(RULES, [10_000, 10_000], hid % 2, random.Random(700 + hid), hand_id=hid)
        play_hand(state, [hero, villain] if hid % 2 == 0 else [villain, hero])
    early = [d for d in hero.decisions if d["street"] < TURN]
    assert early and all(d["temporary_baseline"] for d in early)
    assert all(d["source"] in ("baseline-v1", "joint-turn-river") or d["source"].startswith("river-fallback")
               for d in hero.decisions)
