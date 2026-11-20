"""Tests for combinatorial engine (Step 3).

We verify our enumeration against known published values.
These numbers are mathematical facts — if our code produces them,
we know our Card, Deck, and Evaluator are all correct.
"""

import pytest
from pokerlab.math.combinatorics import enumerate_all_hands, count_5card_by_rank
from pokerlab.math.evaluator import HandRank


class TestEnumeration:
    def test_5card_total(self):
        assert enumerate_all_hands(5) == 2_598_960

    def test_7card_total(self):
        assert enumerate_all_hands(7) == 133_784_560

    def test_2card_total(self):
        assert enumerate_all_hands(2) == 1_326


class TestCount5Card:
    """Verify 5-card hand counts against known mathematical values.

    These are exact, published numbers. If our code matches all of them,
    it proves our evaluator is correct across every possible 5-card hand.
    """

    @pytest.fixture(scope="class")
    def counts(self):
        """Run enumeration once for all tests in this class.

        scope='class' means this runs once and is shared across all test methods,
        not re-run for each test. The enumeration takes ~5 seconds.
        """
        return count_5card_by_rank()

    def test_total_hands(self, counts):
        total = sum(counts.values())
        assert total == 2_598_960

    def test_royal_flush(self, counts):
        assert counts[HandRank.ROYAL_FLUSH] == 4

    def test_straight_flush(self, counts):
        # 36 = 9 ranks (A-low through 9-high) x 4 suits, excluding royals
        assert counts[HandRank.STRAIGHT_FLUSH] == 36

    def test_four_of_a_kind(self, counts):
        assert counts[HandRank.FOUR_OF_A_KIND] == 624

    def test_full_house(self, counts):
        assert counts[HandRank.FULL_HOUSE] == 3_744

    def test_flush(self, counts):
        assert counts[HandRank.FLUSH] == 5_108

    def test_straight(self, counts):
        assert counts[HandRank.STRAIGHT] == 10_200

    def test_three_of_a_kind(self, counts):
        assert counts[HandRank.THREE_OF_A_KIND] == 54_912

    def test_two_pair(self, counts):
        assert counts[HandRank.TWO_PAIR] == 123_552

    def test_one_pair(self, counts):
        assert counts[HandRank.ONE_PAIR] == 1_098_240

    def test_high_card(self, counts):
        assert counts[HandRank.HIGH_CARD] == 1_302_540
