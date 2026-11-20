"""Connector Bonus — An Original Side Bet Design.

GAME CONCEPT:
    The "Connector Bonus" is an original side bet for Texas Hold'em variants.
    It pays based on the longest sequence of consecutive-ranked cards
    (connectors) found in the player's best 7-card hand.

    This is inspired by the poker concept of "connected cards" (like 7-8, T-J),
    which recreational players find exciting. The bet rewards hands that
    contain long runs of consecutive ranks.

DESIGN RATIONALE:
    - Appeals to recreational players who love "connected" boards
    - Easy to understand: "the more connectors, the more you win"
    - Mathematically interesting: connector probability is non-trivial
    - Target house edge: 3-6% (typical for casino side bets)

PAYTABLE (v3, tuned to ~2.1% house edge):
    7-card run (7 consecutive):  75 to 1
    6-card run:                  12 to 1
    5-card run:                   3 to 1
    4-card run:                   1 to 1
    3-card run:                   push (0, bet returned)
    Less than 3-card run:        -1 (loss)

NOTE: A "run" considers only rank consecutiveness, ignoring suits.
      Ace can be high (Q-K-A) or low (A-2-3) but not wrap (K-A-2).
"""

from dataclasses import dataclass
from pokerlab.math.evaluator import HandRank


def longest_run(ranks: list[int]) -> int:
    """Find the longest sequence of consecutive ranks in a set of cards.

    Parameters
    ----------
    ranks : list[int]
        Card ranks (2-14, where 14=Ace). Duplicates are allowed but
        only count once for run purposes.

    Returns
    -------
    int
        Length of the longest consecutive run.

    Examples
    --------
    >>> longest_run([2, 3, 4, 8, 9])  # run of 3 (2-3-4)
    3
    >>> longest_run([10, 11, 12, 13, 14])  # run of 5 (T-J-Q-K-A)
    5
    >>> longest_run([14, 2, 3, 4, 5])  # Ace-low: A-2-3-4-5 = run of 5
    5
    """
    # Deduplicate and sort
    unique_ranks = sorted(set(ranks))

    # Handle ace-low: if Ace (14) is present, also consider it as 1
    if 14 in unique_ranks:
        unique_ranks = [1] + unique_ranks  # Add ace-low at the front

    # Find longest consecutive sequence
    best = 1
    current = 1
    for i in range(1, len(unique_ranks)):
        if unique_ranks[i] == unique_ranks[i - 1] + 1:
            current += 1
            best = max(best, current)
        else:
            current = 1

    return best


# Connector Bonus paytable (v2, tuned for ~4% house edge)
# Only runs of 4+ pay — this keeps the hit frequency at ~18%
# which is similar to UTH Trips (~15%) and feels rewarding but not too frequent
CONNECTOR_PAYTABLE: dict[int, int] = {
    7: 75,     # 7-card run (~0.1%, extremely rare)
    6: 12,     # 6-card run (~0.8%)
    5: 3,      # 5-card run (~3.9%)
    4: 1,      # 4-card run (~13.7%, even money)
    3: 0,      # 3-card run (~36.2%, push — bet returned)
}
CONNECTOR_LOSS = -1  # Less than 4-card run


def connector_payout(ranks: list[int]) -> int:
    """Determine the Connector Bonus payout for a 7-card hand.

    Parameters
    ----------
    ranks : list[int]
        The 7 card ranks.

    Returns
    -------
    int
        Net payout per unit bet.
    """
    run = longest_run(ranks)
    return CONNECTOR_PAYTABLE.get(run, CONNECTOR_LOSS)


def simulate_connector_bonus(
    n_simulations: int = 1_000_000,
    seed: int = 42,
) -> dict:
    """Monte Carlo simulation of the Connector Bonus side bet.

    Returns
    -------
    dict
        Results including EV, house edge, and run length distribution.
    """
    import random
    import math
    from pokerlab.core.deck import Deck

    rng = random.Random(seed)
    all_cards = Deck.full_deck()

    total_payout = 0.0
    total_payout_sq = 0.0
    run_counts: dict[int, int] = {}  # longest run -> count

    for _ in range(n_simulations):
        hand = rng.sample(all_cards, 7)
        ranks = [c.rank for c in hand]
        run_len = longest_run(ranks)
        payout = CONNECTOR_PAYTABLE.get(run_len, CONNECTOR_LOSS)

        total_payout += payout
        total_payout_sq += payout * payout
        run_counts[run_len] = run_counts.get(run_len, 0) + 1

    ev = total_payout / n_simulations
    mean_sq = total_payout_sq / n_simulations
    variance = mean_sq - ev * ev
    std_error = math.sqrt(variance / n_simulations)

    return {
        "ev": ev,
        "house_edge": -ev,
        "std_error": std_error,
        "n_simulations": n_simulations,
        "run_distribution": dict(sorted(run_counts.items())),
    }
