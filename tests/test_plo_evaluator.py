from collections import Counter

import numpy as np
import pytest

from pokerlab.plo.cards import CardConflictError, all_hands, format_cards, parse_cards
from pokerlab.plo.evaluator import (
    CATEGORY_NAMES, category_of, plo_rank_batch, plo_rank_reference, rank5_batch, rank5_reference,
)


def test_all_five_card_hands_have_the_textbook_counts():
    keys = rank5_batch(all_hands(5))
    counts = Counter((keys >> 20).tolist())
    expected = {0: 1302540, 1: 1098240, 2: 123552, 3: 54912, 4: 10200, 5: 5108,
                6: 3744, 7: 624, 8: 40}
    assert counts == expected
    distinct = {c: len(np.unique(keys[(keys >> 20) == c])) for c in range(9)}
    assert distinct == {0: 1277, 1: 2860, 2: 858, 3: 858, 4: 10, 5: 1277, 6: 156, 7: 156, 8: 10}
    assert len(np.unique(keys)) == 7462


def test_vectorised_matches_scalar_oracle():
    hands = all_hands(5)
    rng = np.random.default_rng(3)
    idx = rng.choice(len(hands), 4000, replace=False)
    assert rank5_batch(hands[idx]).tolist() == [rank5_reference(h) for h in hands[idx]]


@pytest.mark.parametrize("better,worse", [
    ("AsAhKdQcJs", "AcAdKhQdTs"),     # kicker decides
    ("2s3h4d5c6s", "As2h3d4c5s"),     # six-high straight beats the wheel
    ("KsKhKd2c2s", "QsQhQdAcAs"),     # full house by trips
    ("9s9h9d9c2s", "8s8h8d8cAs"),
    ("AsKsQsJs9s", "AhKhQhJh8h"),     # flush kicker
])
def test_five_card_ordering(better, worse):
    assert rank5_reference(parse_cards(better)) > rank5_reference(parse_cards(worse))
    assert rank5_batch(np.array([parse_cards(better), parse_cards(worse)])).tolist() == [
        rank5_reference(parse_cards(better)), rank5_reference(parse_cards(worse))]


def plo(hole: str, board: str) -> int:
    return plo_rank_reference(parse_cards(hole), parse_cards(board))


def test_plo_needs_two_hole_cards_for_a_flush():
    board = "AhKh7h2h9c"
    assert CATEGORY_NAMES[category_of(plo("QhQsJdTc", board))] == "pair"
    assert CATEGORY_NAMES[category_of(plo("3h4c5d6s", board))] == "high card"
    assert CATEGORY_NAMES[category_of(plo("3h4h5d6s", board))] == "flush"


def test_plo_board_full_house_and_straight_do_not_play():
    assert CATEGORY_NAMES[category_of(plo("2c3d4h5s", "AcAdAhKcKd"))] == "three of a kind"
    assert CATEGORY_NAMES[category_of(plo("AcAdKcKd", "5c6d7h8s9c"))] == "pair"
    assert CATEGORY_NAMES[category_of(plo("KcKdQhJs", "KsKh7d2c3s"))] == "four of a kind"
    # extra suited hole cards do not help: exactly two hole cards play
    assert plo("AsKsQsJs", "Ts9s2s3c4h") == plo("AsKs7d8d", "Ts9s2s3c4h")
    assert CATEGORY_NAMES[category_of(plo("AsKsQsJs", "Ts9s2s3c4h"))] == "flush"


def test_plo_wheel_and_exact_split():
    assert CATEGORY_NAMES[category_of(plo("Ad2c9h9s", "3s4d5cKhQd"))] == "straight"
    board = "AsKdQhJc3s"
    assert plo("Th9h4c4d", board) == plo("Td9d5c5h", board)


def test_plo_batch_matches_reference_on_random_boards():
    rng = np.random.default_rng(9)
    for board_size in (3, 4, 5):
        for _ in range(30):
            cards = rng.permutation(52)
            board = tuple(int(c) for c in cards[:board_size])
            holes = cards[board_size:board_size + 40].reshape(10, 4)
            assert plo_rank_batch(holes, board).tolist() == [plo_rank_reference(h, board) for h in holes]


def test_pair_table_ranking_matches_brute_force_2_plus_3():
    from pokerlab.plo.evaluator import plo_rank_batch_direct
    rng = np.random.default_rng(12)
    flop = parse_cards("KsKh7d")
    hands = all_hands(4, flop)                       # every hand, exhaustive on a flop
    assert np.array_equal(plo_rank_batch(hands, flop), plo_rank_batch_direct(hands, flop))
    for text in ("Ah8h8d5c2h", "5c6d7h8s9c", "As2c3d4h"):
        board = parse_cards(text)
        hands = all_hands(4, board)
        idx = rng.choice(len(hands), 15_000, replace=False)
        assert np.array_equal(plo_rank_batch(hands, board)[idx], plo_rank_batch_direct(hands[idx], board))


def test_card_conflicts_are_rejected():
    with pytest.raises(CardConflictError):
        parse_cards("AsAs")
    with pytest.raises(CardConflictError):
        plo_rank_reference(parse_cards("AsKdQh2c"), parse_cards("As7d8h9cTs"))
    with pytest.raises(CardConflictError):
        plo_rank_batch(np.array([parse_cards("AsKdQh2c")]), parse_cards("As7d8h9cTs"))
    assert format_cards(parse_cards("Td 9c")) == "Td9c"
