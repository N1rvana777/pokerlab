"""Tests for core card infrastructure (Step 1)."""

from pokerlab.core.card import Card, Suit, card_from_str, RANK_NAMES
from pokerlab.core.deck import Deck
from pokerlab.core.hand import Hand
import pytest


class TestCard:
    def test_create_card(self):
        c = Card(14, Suit.SPADES)
        assert c.rank == 14
        assert c.suit == Suit.SPADES

    def test_card_str(self):
        assert str(Card(14, Suit.SPADES)) == "As"
        assert str(Card(10, Suit.DIAMONDS)) == "Td"
        assert str(Card(2, Suit.CLUBS)) == "2c"

    def test_card_invalid_rank(self):
        with pytest.raises(ValueError):
            Card(1, Suit.HEARTS)
        with pytest.raises(ValueError):
            Card(15, Suit.HEARTS)

    def test_card_immutable(self):
        c = Card(14, Suit.SPADES)
        with pytest.raises(AttributeError):
            c.rank = 13  # type: ignore

    def test_card_hashable(self):
        """Cards must be hashable for use in sets and as dict keys."""
        c1 = Card(14, Suit.SPADES)
        c2 = Card(14, Suit.SPADES)
        assert hash(c1) == hash(c2)
        assert len({c1, c2}) == 1  # same card -> one entry in set

    def test_card_comparison(self):
        two = Card(2, Suit.CLUBS)
        ace = Card(14, Suit.SPADES)
        assert two < ace
        assert ace > two

    def test_card_from_str(self):
        assert card_from_str("As") == Card(14, Suit.SPADES)
        assert card_from_str("Td") == Card(10, Suit.DIAMONDS)
        assert card_from_str("2c") == Card(2, Suit.CLUBS)

    def test_card_from_str_invalid(self):
        with pytest.raises(ValueError):
            card_from_str("Xx")
        with pytest.raises(ValueError):
            card_from_str("ABC")


class TestDeck:
    def test_deck_has_52_cards(self):
        deck = Deck()
        assert len(deck) == 52

    def test_deck_all_unique(self):
        deck = Deck()
        cards = list(deck)
        assert len(set(cards)) == 52

    def test_deck_deal(self):
        deck = Deck()
        hand = deck.deal(5)
        assert len(hand) == 5
        assert len(deck) == 47

    def test_deck_deal_too_many(self):
        deck = Deck()
        with pytest.raises(ValueError):
            deck.deal(53)

    def test_deck_shuffle_reproducible(self):
        """Same seed should produce same shuffle order."""
        d1 = Deck(seed=42)
        d1.shuffle()
        cards1 = list(d1)

        d2 = Deck(seed=42)
        d2.shuffle()
        cards2 = list(d2)

        assert cards1 == cards2

    def test_deck_reset(self):
        deck = Deck()
        deck.deal(10)
        assert len(deck) == 42
        deck.reset()
        assert len(deck) == 52

    def test_full_deck_static(self):
        cards = Deck.full_deck()
        assert len(cards) == 52
        assert len(set(cards)) == 52


class TestHand:
    def test_hand_length(self):
        cards = [Card(14, Suit.SPADES), Card(13, Suit.HEARTS)]
        h = Hand(cards)
        assert len(h) == 2

    def test_hand_sorted(self):
        """Hand should store cards sorted by rank ascending."""
        cards = [Card(14, Suit.SPADES), Card(2, Suit.CLUBS), Card(7, Suit.HEARTS)]
        h = Hand(cards)
        ranks = h.ranks
        assert ranks == [2, 7, 14]

    def test_hand_str(self):
        cards = [Card(14, Suit.SPADES), Card(13, Suit.HEARTS)]
        h = Hand(cards)
        assert str(h) == "Kh As"

    def test_hand_iteration(self):
        cards = [Card(10, Suit.DIAMONDS), Card(5, Suit.CLUBS)]
        h = Hand(cards)
        assert list(h) == [Card(5, Suit.CLUBS), Card(10, Suit.DIAMONDS)]

    def test_hand_equality(self):
        h1 = Hand([Card(14, Suit.SPADES), Card(13, Suit.HEARTS)])
        h2 = Hand([Card(13, Suit.HEARTS), Card(14, Suit.SPADES)])
        assert h1 == h2  # same cards, different order -> equal

    def test_hand_add(self):
        h = Hand([Card(14, Suit.SPADES)])
        h2 = h.add(Card(13, Suit.HEARTS))
        assert len(h) == 1   # original unchanged
        assert len(h2) == 2  # new hand has both cards
