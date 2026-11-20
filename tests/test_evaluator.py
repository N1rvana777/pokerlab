"""Tests for poker hand evaluator (Step 2)."""

from pokerlab.core.card import card_from_str
from pokerlab.math.evaluator import evaluate_5card, evaluate_best5, HandRank


def make_hand(*card_strs: str):
    """Helper: make a list of Cards from short strings like 'As', 'Kh'."""
    return [card_from_str(s) for s in card_strs]


class TestEvaluate5Card:
    def test_royal_flush(self):
        hand = make_hand("Ah", "Kh", "Qh", "Jh", "Th")
        assert evaluate_5card(hand) == HandRank.ROYAL_FLUSH

    def test_straight_flush(self):
        hand = make_hand("9d", "8d", "7d", "6d", "5d")
        assert evaluate_5card(hand) == HandRank.STRAIGHT_FLUSH

    def test_straight_flush_wheel(self):
        """A-2-3-4-5 of same suit = straight flush, not royal flush."""
        hand = make_hand("Ac", "2c", "3c", "4c", "5c")
        assert evaluate_5card(hand) == HandRank.STRAIGHT_FLUSH

    def test_four_of_a_kind(self):
        hand = make_hand("Ks", "Kh", "Kd", "Kc", "2s")
        assert evaluate_5card(hand) == HandRank.FOUR_OF_A_KIND

    def test_full_house(self):
        hand = make_hand("Qs", "Qh", "Qd", "Jc", "Jh")
        assert evaluate_5card(hand) == HandRank.FULL_HOUSE

    def test_flush(self):
        hand = make_hand("As", "Js", "9s", "7s", "2s")
        assert evaluate_5card(hand) == HandRank.FLUSH

    def test_straight(self):
        hand = make_hand("Ts", "9h", "8d", "7c", "6s")
        assert evaluate_5card(hand) == HandRank.STRAIGHT

    def test_straight_wheel(self):
        """A-2-3-4-5 mixed suits = straight."""
        hand = make_hand("As", "2h", "3d", "4c", "5s")
        assert evaluate_5card(hand) == HandRank.STRAIGHT

    def test_straight_ace_high(self):
        """A-K-Q-J-T = ace-high straight."""
        hand = make_hand("As", "Kh", "Qd", "Jc", "Ts")
        assert evaluate_5card(hand) == HandRank.STRAIGHT

    def test_three_of_a_kind(self):
        hand = make_hand("7s", "7h", "7d", "Kc", "2s")
        assert evaluate_5card(hand) == HandRank.THREE_OF_A_KIND

    def test_two_pair(self):
        hand = make_hand("As", "Ah", "Kd", "Kc", "2s")
        assert evaluate_5card(hand) == HandRank.TWO_PAIR

    def test_one_pair(self):
        hand = make_hand("Js", "Jh", "9d", "7c", "2s")
        assert evaluate_5card(hand) == HandRank.ONE_PAIR

    def test_high_card(self):
        hand = make_hand("As", "Jh", "9d", "7c", "2s")
        assert evaluate_5card(hand) == HandRank.HIGH_CARD

    def test_wrong_card_count(self):
        import pytest
        with pytest.raises(ValueError):
            evaluate_5card(make_hand("As", "Kh", "Qd"))


class TestEvaluateBest5:
    def test_7card_finds_flush(self):
        """7 cards with 5 of same suit -> flush (at least)."""
        hand = make_hand("As", "Ks", "Qs", "Js", "3s", "2h", "4d")
        result = evaluate_best5(hand)
        assert result >= HandRank.FLUSH

    def test_7card_finds_straight(self):
        """7 cards containing a straight among garbage."""
        hand = make_hand("Ts", "9h", "8d", "7c", "6s", "2h", "3d")
        result = evaluate_best5(hand)
        assert result >= HandRank.STRAIGHT

    def test_7card_full_house_over_two_pair(self):
        """Should find full house even though two pair is also present."""
        hand = make_hand("Ks", "Kh", "Kd", "Qc", "Qs", "2h", "3d")
        assert evaluate_best5(hand) == HandRank.FULL_HOUSE

    def test_7card_royal_flush(self):
        hand = make_hand("Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d")
        assert evaluate_best5(hand) == HandRank.ROYAL_FLUSH

    def test_6card_works(self):
        hand = make_hand("As", "Ah", "Kd", "Kc", "Qs", "Qh")
        result = evaluate_best5(hand)
        assert result == HandRank.TWO_PAIR or result == HandRank.FULL_HOUSE
        # Actually with 3 pairs in 6 cards, best 5 = two pair
        # Wait — AAKKQx -> best 5 must include 2 pair at minimum
        # But no trips possible, so TWO_PAIR is correct

    def test_5card_passthrough(self):
        """5-card input should work identically to evaluate_5card."""
        hand = make_hand("As", "Ah", "Kd", "Kc", "Qs")
        assert evaluate_best5(hand) == HandRank.TWO_PAIR
