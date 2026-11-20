import random

import pytest

from pokerlab.plo.agents import RandomAgent
from pokerlab.plo.cards import DECK, parse_cards
from pokerlab.plo.engine import (
    FLOP, PREFLOP, RIVER, TURN, Action, ActionType, HandState, IllegalActionError, RakeRule,
    TableRules, deal_hand, observe,
)

RULES = TableRules(small_blind=50, big_blind=100)


def explicit(stacks, button, holes, board, rules=RULES):
    return HandState(rules, stacks, button, [parse_cards(h) for h in holes], parse_cards(board))


def dealt(stacks, button, rules=RULES, seed=1):
    return deal_hand(rules, stacks, button, random.Random(seed))


def test_six_max_preflop_pot_limit_and_min_raise():
    s = dealt([10_000] * 6, button=5)
    assert (s.sb_seat, s.bb_seat, s.to_act) == (0, 1, 2)
    legal = s.legal_actions()
    assert (legal.raise_type, legal.call_amount, legal.min_to, legal.max_to) == (ActionType.RAISE, 100, 200, 350)
    assert not legal.can_check and legal.can_fold
    s.apply(Action.raise_to(350))
    legal = s.legal_actions()
    assert (legal.min_to, legal.max_to) == (600, 1200)   # pot raise = 3 x 350 + 150


def test_heads_up_blinds_order_and_streets():
    s = dealt([10_000, 10_000], button=0)
    assert (s.sb_seat, s.bb_seat, s.to_act) == (0, 1, 0)
    legal = s.legal_actions()
    assert (legal.call_amount, legal.min_to, legal.max_to) == (50, 200, 300)
    s.apply(Action.call())
    legal = s.legal_actions()
    assert s.to_act == 1 and legal.can_check and not legal.can_fold
    assert (legal.min_to, legal.max_to) == (200, 300)
    with pytest.raises(IllegalActionError):
        s.apply(Action.fold())
    s.apply(Action.check())
    assert s.street == FLOP and s.to_act == 1 and len(s.board) == 3
    legal = s.legal_actions()
    assert (legal.raise_type, legal.min_to, legal.max_to) == (ActionType.BET, 100, 200)
    s.apply(Action.bet(200))
    legal = s.legal_actions()
    assert (legal.min_to, legal.max_to) == (400, 800)   # 3 x 200 + 200
    s.apply(Action.raise_to(800))
    legal = s.legal_actions()
    assert (legal.min_to, legal.max_to) == (1400, 2600)
    with pytest.raises(IllegalActionError):
        s.apply(Action.raise_to(2601))
    with pytest.raises(IllegalActionError):
        s.apply(Action.raise_to(1399))


def _limp_to_flop(s, order):
    for seat in order:
        assert s.to_act == seat
        s.apply(Action.check() if s.legal_actions().can_check else Action.call())


def test_short_all_in_raise_does_not_reopen_betting():
    s = dealt([10_000, 10_000, 350], button=2)
    _limp_to_flop(s, [2, 0, 1])
    assert s.street == FLOP and s.pot == 300 and s.to_act == 0
    s.apply(Action.bet(200))
    s.apply(Action.call())
    legal = s.legal_actions()
    assert s.to_act == 2 and (legal.min_to, legal.max_to) == (250, 250)  # all-in for less than a raise
    s.apply(Action.raise_to(250))
    assert s.to_act == 0 and s.legal_actions().raise_type is None
    s.apply(Action.call())
    assert s.to_act == 1 and s.legal_actions().raise_type is None
    s.apply(Action.call())
    assert s.street == TURN


def test_cumulative_short_all_ins_reopen_betting():
    s = dealt([10_000, 10_000, 400, 520], button=3)
    _limp_to_flop(s, [2, 3, 0, 1])
    assert s.pot == 400 and s.to_act == 0
    s.apply(Action.bet(200))
    s.apply(Action.call())
    s.apply(Action.raise_to(300))          # seat 2 all-in, +100
    legal = s.legal_actions()
    assert (legal.min_to, legal.max_to) == (420, 420)
    s.apply(Action.raise_to(420))          # seat 3 all-in, +120
    legal = s.legal_actions()
    assert s.to_act == 0 and legal.raise_type is ActionType.RAISE and legal.min_to == 620


def test_three_way_side_pots():
    s = explicit([300, 600, 1000], 2, ["KcKd4h5d", "9c9d6h8c", "2d2hQhJc"], "2c7d9hKs3s")
    s.apply(Action.raise_to(350))
    assert s.legal_actions().call_amount == 250 and s.legal_actions().raise_type is None
    s.apply(Action.call())
    assert s.legal_actions().max_to == 600
    s.apply(Action.raise_to(600))
    assert s.legal_actions().raise_type is None
    s.apply(Action.call())
    r = s.result
    assert r is not None and s.street == RIVER
    assert [(p.amount, p.eligible, p.winners) for p in r.pots] == [(900, (0, 1, 2), (0,)), (600, (1, 2), (1,))]
    assert r.net == (600, 0, -600) and sum(r.net) == 0
    assert set(r.showdown) == {0, 1, 2}


def test_uncalled_bet_is_returned_without_showdown():
    s = dealt([10_000, 10_000], button=0)
    s.apply(Action.raise_to(300))
    s.apply(Action.fold())
    r = s.result
    assert r.returned == (200, 0) and r.net == (100, -100)
    assert r.showdown == {} and r.board == ()


def test_split_pot_odd_chip_goes_first_left_of_button():
    rules = TableRules(small_blind=25, big_blind=50)
    s = explicit([1000] * 3, 2, ["2c2d6s7s", "Th9h4c4d", "Td9d5c5h"], "AsKdQhJc3s", rules)
    s.apply(Action.call())
    s.apply(Action.fold())
    s.apply(Action.check())
    while s.to_act is not None:
        s.apply(Action.check())
    r = s.result
    assert r.pots[0].winners == (1, 2) and r.pots[0].shares == (63, 62)
    assert r.net == (-25, 13, 12)


def test_short_big_blind_all_in_and_nominal_blind_to_call():
    s = dealt([10_000, 60, 10_000], button=2)
    assert s.stacks[1] == 0 and s.to_act == 2
    assert s.legal_actions().call_amount == 100
    s.apply(Action.call())
    s.apply(Action.call())
    assert s.street == FLOP and s.to_act == 0


@pytest.mark.parametrize("counted,expected", [(True, 380), (False, 350)])
def test_antes_and_pot_limit_convention(counted, expected):
    rules = TableRules(50, 100, ante=10, antes_count_for_pot_limit=counted)
    s = dealt([10_000] * 3, button=2, rules=rules)
    assert s.pot == 180 and s.legal_actions().max_to == expected


def test_rake_is_explicit_and_conserved():
    rules = TableRules(50, 100, rake=RakeRule(percent=5.0, cap=30))
    s = dealt([10_000, 10_000], button=0, rules=rules)
    s.apply(Action.call())
    s.apply(Action.check())
    while s.to_act is not None:
        s.apply(Action.check())
    assert s.result.rake == 10 and sum(s.result.net) == -10
    s = dealt([10_000, 10_000], button=0, rules=rules)
    s.apply(Action.fold())
    assert s.result.rake == 0 and s.result.net == (-50, 50)


def test_folded_chips_above_a_short_all_in_are_returned():
    # Reviewer repro: the big blind is all-in on a 30-chip ante and posts no blind.
    s = dealt([150, 30, 99], button=2, rules=TableRules(50, 100, ante=50))
    assert s.stacks[1] == 0 and s.committed_total == [100, 30, 50]
    s.apply(Action.fold())
    s.apply(Action.fold())
    r = s.result
    assert r.returned == (70, 0, 20) and r.net == (-30, 60, -30)
    assert [(p.amount, p.winners) for p in r.pots] == [(90, (1,))]


def test_two_short_all_ins_with_a_bigger_folded_contribution():
    s = dealt([1_000, 30, 60], button=2, rules=TableRules(50, 100, ante=50))
    s.apply(Action.call())       # seat 2 all-in for its last 10
    s.apply(Action.fold())       # seat 0 folds 100 (ante + small blind)
    r = s.result
    assert r.returned == (40, 0, 0) and sum(r.net) == 0
    assert [p.amount for p in r.pots] == [90, 60] and r.pots[1].eligible == (2,)


def test_rake_is_taken_from_each_pot_in_proportion():
    rules = TableRules(50, 100, rake=RakeRule(percent=5.0, cap=None))
    s = explicit([60, 10_000, 10_000], 2, ["AsAcKdQd", "KsKhQcJc", "9s9h8c8d"], "AhAd7c4s2h", rules)
    s.apply(Action.raise_to(350))
    s.apply(Action.call())                 # short stack all-in for 60 with quad aces
    s.apply(Action.call())
    for to in (760, 2280, 6610):
        s.apply(Action.bet(to))
        s.apply(Action.call())
    r = s.result
    assert r.rake == 1003                  # 5% of 20,060
    assert r.pots[0].winners == (0,) and r.pots[0].shares == (171,)   # 180 minus 9 rake
    assert r.net[0] == 111 and sum(r.net) == -1003


def test_rake_uses_exact_decimal_arithmetic():
    rules = TableRules(50, 100, rake=RakeRule(percent=4.1, cap=None))
    s = dealt([10_000, 10_000], button=0, rules=rules)
    s.apply(Action.call())
    s.apply(Action.check())
    for to in (200, 600, 600):
        s.apply(Action.bet(to))
        s.apply(Action.call())
    assert sum(s.committed_total) == 3_000 and s.result.rake == 123   # float math gave 122


def test_random_play_with_antes_and_tiny_stacks_settles():
    rng = random.Random(17)
    for trial in range(1_500):
        n = rng.randint(2, 8)
        rules = TableRules(50, 100, ante=rng.choice([10, 25, 50]))
        stacks = [rng.choice([20, 40, 75, 120, 300, 2_000]) for _ in range(n)]
        s = deal_hand(rules, stacks, rng.randrange(n), random.Random(trial))
        agents = [RandomAgent(seed=trial * 10 + k) for k in range(n)]
        while s.to_act is not None:
            s.apply(agents[s.to_act].act(observe(s, s.to_act)))
        assert sum(s.result.net) == 0 and min(s.result.final_stacks) >= 0


def test_random_play_invariants_two_to_eight_players():
    rng = random.Random(5)
    hands = 0
    for trial in range(250):
        n = rng.randint(2, 8)
        rules = TableRules(50, 100, ante=rng.choice([0, 0, 5]),
                           rake=rng.choice([None, RakeRule(5.0, 300)]))
        stacks = [rng.choice([30, 99, 160, 700, 5_000, 20_000]) for _ in range(n)]
        s = deal_hand(rules, stacks, rng.randrange(n), random.Random(trial), hand_id=trial)
        agents = [RandomAgent(seed=trial * 10 + k) for k in range(n)]
        while s.to_act is not None:
            legal = s.legal_actions()
            assert legal.call_amount <= s.stacks[s.to_act]
            if legal.can_raise:
                assert 0 < legal.min_to <= legal.max_to <= s.committed_street[s.to_act] + s.stacks[s.to_act]
            assert s.pot == sum(s.committed_total)
            s.apply(agents[s.to_act].act(observe(s, s.to_act)))
        r = s.result
        assert sum(r.net) == -r.rake and min(r.final_stacks) >= 0
        assert sum(p.amount for p in r.pots) + sum(r.returned) + r.rake == sum(s.committed_total)
        hands += 1
    assert hands == 250


def test_observation_is_invariant_to_hidden_cards():
    rng = random.Random(11)
    checked = 0
    for trial in range(60):
        n = rng.randint(2, 6)
        stacks = [rng.choice([400, 3_000, 10_000]) for _ in range(n)]
        button = rng.randrange(n)
        agents = [RandomAgent(seed=trial * 7 + k) for k in range(n)]
        s = deal_hand(RULES, stacks, button, random.Random(trial))
        actions = []
        while s.to_act is not None:
            seat = s.to_act
            obs = observe(s, seat)
            # Re-deal every card the observer cannot see, replay the public actions, compare.
            visible = set(s.hole_cards[seat]) | set(s.board)
            hidden = [c for c in DECK if c not in visible]
            rng.shuffle(hidden)
            holes = []
            for k in range(n):
                if k == seat:
                    holes.append(s.hole_cards[seat])
                else:
                    holes.append(tuple(hidden[:4]))
                    del hidden[:4]
            runout = tuple(s.board) + tuple(hidden[:5 - len(s.board)])
            alt = HandState(RULES, stacks, button, holes, runout)
            for a in actions:
                alt.apply(a)
            assert observe(alt, seat) == obs
            assert set(obs.hole_cards) | set(obs.board) == visible
            action = agents[seat].act(obs)
            actions.append(action)
            s.apply(action)
            checked += 1
    assert checked > 100


def test_preset_cards_conflicts_rejected():
    with pytest.raises(ValueError):
        deal_hand(RULES, [1000, 1000], 0, random.Random(1),
                  preset_holes={0: parse_cards("AsKsQsJs")}, preset_board=parse_cards("As2c3d"))
    s = deal_hand(RULES, [1000, 1000], 0, random.Random(1),
                  preset_holes={1: parse_cards("AsKsQsJs")}, preset_board=parse_cards("2c3d4h"))
    assert s.hole_cards[1] == parse_cards("AsKsQsJs") and s._runout[:3] == parse_cards("2c3d4h")
    assert s.street == PREFLOP
