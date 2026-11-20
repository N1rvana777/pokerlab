"""Pot-limit semantics shared by the engine and the subgame trees (P, h, c notation)."""
import random
from fractions import Fraction

import pytest

from pokerlab.plo.betting import (
    DEFAULT_SIZES, abstract_targets, fraction_raise_to, max_raise_to, parse_fraction,
    raise_window, round_chips,
)
from pokerlab.plo.engine import Action, TableRules, deal_hand
from pokerlab.plo.subgame.tree import BettingConfig, BettingTree


def test_independent_expected_values_of_the_formula():
    assert max_raise_to(P=150, h=0, c=50) == 250      # pot 100, villain bets 50, hero has 0 in
    assert max_raise_to(P=3, h=1, c=1) == 6           # heads-up 1/2, small blind acts first
    assert max_raise_to(P=350, h=50, c=150) == 700    # pot 100, hero bet 50, villain raised to 200
    assert max_raise_to(P=4, h=2, c=0) == 6           # big blind facing a limp: h = 2 counts


def _flop_pot_100():
    s = deal_hand(TableRules(25, 50), [10_000, 10_000], 0, random.Random(1))
    s.apply(Action.call())
    s.apply(Action.check())
    assert s.limit_pot == 100 and s.to_act == 1          # big blind (seat 1) acts first postflop
    return s


def test_engine_case_1_raise_over_a_first_bet():
    s = _flop_pot_100()
    s.apply(Action.bet(50))
    assert s.to_act == 0 and s.committed_street[0] == 0 and s.legal_actions().max_to == 250


def test_engine_case_2_heads_up_small_blind_first_action():
    s = deal_hand(TableRules(1, 2), [200, 200], 0, random.Random(1))
    legal = s.legal_actions()
    assert s.to_act == 0 and (legal.min_to, legal.max_to) == (4, 6)


def test_engine_case_3_reraise_after_own_bet():
    s = _flop_pot_100()
    s.apply(Action.bet(50))
    s.apply(Action.raise_to(200))
    legal = s.legal_actions()
    assert s.to_act == 1 and legal.max_to == 700
    assert legal.max_to - s.committed_street[1] == 650


def test_engine_case_4_big_blind_facing_a_limp_counts_its_blind():
    s = deal_hand(TableRules(1, 2), [200, 200], 0, random.Random(1))
    s.apply(Action.call())
    legal = s.legal_actions()
    assert s.to_act == 1 and legal.can_check and (legal.min_to, legal.max_to) == (4, 6)


def test_tree_uses_the_same_formulas():
    tree = BettingTree(BettingConfig(pot=100, stacks=(10_000, 10_000), bet_sizes=("1/2",),
                                     raise_sizes=("3/4", "1"), min_bet=2, include_min_raise=False))
    ip = tree.nodes[tree.find(["bet:50"])]
    assert {"raise:200", "raise:250"} <= set(ip.actions)
    assert max(int(a.split(":")[1]) for a in ip.actions if a.startswith("raise:")) == 250   # case 1
    oop = tree.nodes[tree.find(["bet:50", "raise:200"])]
    assert max(int(a.split(":")[1]) for a in oop.actions if a.startswith("raise:")) == 700  # case 3


def test_four_size_abstraction_boundaries_filtering_and_dedup():
    w = raise_window(P=1000, h=0, c=0, stack=5000, last_full_increment=50, big_blind=50)
    assert abstract_targets(1000, 0, 0, w, DEFAULT_SIZES) == [50, 333, 500, 667, 1000]
    assert abstract_targets(1000, 0, 0, w, DEFAULT_SIZES, include_min=False) == [333, 500, 667, 1000]
    assert 5000 not in abstract_targets(1000, 0, 0, w, DEFAULT_SIZES)   # no all-in above pot limit
    short = raise_window(1000, 0, 0, 700, 50, 50)                        # stack below the pot limit
    assert (short.min_to, short.max_to, short.max_is_all_in) == (50, 700, True)
    assert abstract_targets(1000, 0, 0, short, DEFAULT_SIZES) == [50, 333, 500, 667, 700]
    tiny = raise_window(1000, 0, 0, 30, 50, 50)                          # below the minimum bet
    assert abstract_targets(1000, 0, 0, tiny, DEFAULT_SIZES) == [30]
    assert raise_window(1000, 200, 300, 300, 300, 50) is None            # can only call all-in
    # facing a bet of 300 into 1000 (P = 1300): pot raise to 1900, minimum raise to 600
    w = raise_window(1300, 0, 300, 10_000, 300, 50)
    assert (w.min_to, w.max_to) == (600, 1900)
    assert abstract_targets(1300, 0, 300, w, DEFAULT_SIZES) == [600, 833, 1100, 1367, 1900]


def test_exact_fractions_and_rounding():
    assert parse_fraction("1/3") == Fraction(1, 3) and parse_fraction(0.5) == Fraction(1, 2)
    assert parse_fraction(0.33) == Fraction(33, 100)
    assert fraction_raise_to(1000, 0, 0, Fraction(1, 3)) == 333
    assert fraction_raise_to(1000, 0, 0, Fraction(2, 3)) == 667
    assert round_chips(Fraction(5, 2)) == 3 and round_chips(Fraction(7, 3)) == 2
    with pytest.raises(ValueError):
        parse_fraction("3/2")
