"""Poker hand evaluator for casino game mathematics.

Classifies 5-card and 7-card hands into standard poker rankings.
For 7-card hands, finds the best 5-card combination.

Hand Rankings (strongest to weakest):
    9 = Royal Flush
    8 = Straight Flush
    7 = Four of a Kind
    6 = Full House
    5 = Flush
    4 = Straight
    3 = Three of a Kind
    2 = Two Pair
    1 = One Pair
    0 = High Card
"""

from itertools import combinations  # generates all C(n,k) combos from a collection
from collections import Counter     # counts occurrences of each element
from enum import IntEnum

from pokerlab.core.card import Card


class HandRank(IntEnum):
    """Poker hand ranking categories.

    Higher value = stronger hand. Using IntEnum so we can compare with < > directly.
    """
    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8
    ROYAL_FLUSH = 9


# Human-readable names for par sheet output
HAND_RANK_NAMES: dict[HandRank, str] = {
    HandRank.ROYAL_FLUSH: "Royal Flush",
    HandRank.STRAIGHT_FLUSH: "Straight Flush",
    HandRank.FOUR_OF_A_KIND: "Four of a Kind",
    HandRank.FULL_HOUSE: "Full House",
    HandRank.FLUSH: "Flush",
    HandRank.STRAIGHT: "Straight",
    HandRank.THREE_OF_A_KIND: "Three of a Kind",
    HandRank.TWO_PAIR: "Two Pair",
    HandRank.ONE_PAIR: "One Pair",
    HandRank.HIGH_CARD: "High Card",
}


def evaluate_5card(cards: list[Card] | tuple[Card, ...]) -> HandRank:
    """Classify a 5-card hand into its poker ranking.

    Parameters
    ----------
    cards : list or tuple of Card
        Exactly 5 cards.

    Returns
    -------
    HandRank
        The ranking category of this hand.

    Examples
    --------
    >>> from pokerlab.core.card import card_from_str
    >>> cards = [card_from_str(s) for s in ["Ah", "Kh", "Qh", "Jh", "Th"]]
    >>> evaluate_5card(cards)
    <HandRank.ROYAL_FLUSH: 9>
    """
    if len(cards) != 5:
        raise ValueError(f"Need exactly 5 cards, got {len(cards)}")

    ranks = sorted([c.rank for c in cards])
    suits = [c.suit for c in cards]

    # Check flush: all 5 cards same suit
    is_flush = len(set(suits)) == 1

    # Check straight: 5 consecutive ranks
    is_straight = False
    if ranks[-1] - ranks[0] == 4 and len(set(ranks)) == 5:
        # Normal straight (e.g., 5-6-7-8-9)
        is_straight = True
    elif ranks == [2, 3, 4, 5, 14]:
        # Wheel: A-2-3-4-5 (Ace plays low)
        is_straight = True

    # Count rank frequencies for pair/trips/quads detection
    # Counter example: [A, A, K, K, Q] -> {14: 2, 13: 2, 12: 1}
    rank_counts = Counter(ranks)
    # Sort frequencies descending: e.g., [2, 2, 1] for two pair
    freqs = sorted(rank_counts.values(), reverse=True)

    # Classify hand
    if is_straight and is_flush:
        if ranks == [10, 11, 12, 13, 14]:
            return HandRank.ROYAL_FLUSH
        return HandRank.STRAIGHT_FLUSH
    if freqs[0] == 4:
        return HandRank.FOUR_OF_A_KIND
    if freqs == [3, 2]:
        return HandRank.FULL_HOUSE
    if is_flush:
        return HandRank.FLUSH
    if is_straight:
        return HandRank.STRAIGHT
    if freqs[0] == 3:
        return HandRank.THREE_OF_A_KIND
    if freqs == [2, 2, 1]:
        return HandRank.TWO_PAIR
    if freqs[0] == 2:
        return HandRank.ONE_PAIR
    return HandRank.HIGH_CARD


def evaluate_best5(cards: list[Card] | tuple[Card, ...]) -> HandRank:
    """Find the best 5-card poker hand from 5, 6, or 7 cards.

    For 7-card Texas Hold'em hands, this tries all C(7,5) = 21 combinations
    and returns the strongest ranking.

    Parameters
    ----------
    cards : list or tuple of Card
        5 to 7 cards.

    Returns
    -------
    HandRank
        The best possible 5-card hand ranking.
    """
    n = len(cards)
    if n < 5 or n > 7:
        raise ValueError(f"Need 5-7 cards, got {n}")

    if n == 5:
        return evaluate_5card(cards)

    # Try all C(n, 5) combinations and return the best ranking
    # combinations() is from itertools — it generates all ways to choose 5 from n
    best = HandRank.HIGH_CARD
    for combo in combinations(cards, 5):
        rank = evaluate_5card(combo)
        if rank > best:
            best = rank
    return best
