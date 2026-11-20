"""Combinatorial engine for exact probability calculation.

This module provides tools to enumerate all possible card combinations
and count them by poker hand ranking. This is the foundation for
computing exact (analytic) probabilities in casino game math.

Key insight for Game Mathematician work:
    Monte Carlo gives you an ESTIMATE. Exact enumeration gives you the
    PRECISE answer. A par sheet requires exact numbers, so we enumerate
    when feasible (C(52,5) = 2.6M is fine, C(52,7) = 133.8M is slow
    but doable).
"""

from itertools import combinations
from collections import Counter as _Counter

from pokerlab.core.deck import Deck
from pokerlab.core.card import Card
from pokerlab.math.evaluator import HandRank, evaluate_5card, evaluate_best5


def enumerate_all_hands(n: int) -> int:
    """Count total number of n-card hands from a 52-card deck.

    This is simply C(52, n) = 52! / (n! * (52-n)!)

    Parameters
    ----------
    n : int
        Number of cards per hand.

    Returns
    -------
    int
        Total number of possible hands.
    """
    from math import comb
    return comb(52, n)


def count_5card_by_rank() -> dict[HandRank, int]:
    """Enumerate all C(52,5) = 2,598,960 five-card hands and count by ranking.

    Returns
    -------
    dict[HandRank, int]
        Number of hands for each poker hand ranking.

    Notes
    -----
    Known exact values (for verification):
        Royal Flush:       4
        Straight Flush:   36
        Four of a Kind:  624
        Full House:    3,744
        Flush:         5,108
        Straight:     10,200
        Three of Kind: 54,912
        Two Pair:     123,552
        One Pair:   1,098,240
        High Card:  1,302,540
        TOTAL:      2,598,960
    """
    all_cards = Deck.full_deck()
    counts: dict[HandRank, int] = {rank: 0 for rank in HandRank}

    for combo in combinations(all_cards, 5):
        rank = evaluate_5card(combo)
        counts[rank] += 1

    return counts


def count_7card_by_rank() -> dict[HandRank, int]:
    """Enumerate all C(52,7) = 133,784,560 seven-card hands, classify by best-5.

    This is the key computation for UTH Trips Bet analysis.
    WARNING: This takes several minutes to run (~133M hands, each checking C(7,5)=21 combos).

    Returns
    -------
    dict[HandRank, int]
        Number of 7-card hands whose best 5-card hand falls into each ranking.
    """
    all_cards = Deck.full_deck()
    counts: dict[HandRank, int] = {rank: 0 for rank in HandRank}

    for combo in combinations(all_cards, 7):
        rank = evaluate_best5(combo)
        counts[rank] += 1

    return counts
