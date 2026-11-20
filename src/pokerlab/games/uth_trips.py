"""Ultimate Texas Hold'em — Trips Bet Analysis.

The Trips bet is a popular side bet in UTH. It pays based ONLY on the
player's best 5-card hand (from 2 hole cards + 5 community cards),
regardless of the dealer's hand. This makes it mathematically clean:
we just need to enumerate all C(52,7) = 133,784,560 possible 7-card hands.

Common Vegas Paytable (used in this analysis):
    Royal Flush:     50 to 1
    Straight Flush:  40 to 1
    Four of a Kind:  30 to 1
    Full House:       8 to 1
    Flush:            6 to 1
    Straight:         5 to 1
    Three of a Kind:  3 to 1
    Loss:            -1 (player loses their bet)

Note: "50 to 1" means you win 50 units and keep your 1 unit bet.
"""

from dataclasses import dataclass
from pokerlab.math.evaluator import HandRank, HAND_RANK_NAMES
from pokerlab.math.combinatorics import count_7card_by_rank
import math


# Paytable: maps HandRank -> net payout per unit bet
# Positive = player wins that many units, -1 = player loses bet
TRIPS_PAYTABLE: dict[HandRank, int] = {
    HandRank.ROYAL_FLUSH: 50,
    HandRank.STRAIGHT_FLUSH: 40,
    HandRank.FOUR_OF_A_KIND: 30,
    HandRank.FULL_HOUSE: 8,
    HandRank.FLUSH: 6,
    HandRank.STRAIGHT: 5,
    HandRank.THREE_OF_A_KIND: 3,
    # Everything below trips loses
    HandRank.TWO_PAIR: -1,
    HandRank.ONE_PAIR: -1,
    HandRank.HIGH_CARD: -1,
}

# Winning hands (payout > 0) for hit frequency calculation
WINNING_RANKS = {
    rank for rank, payout in TRIPS_PAYTABLE.items() if payout > 0
}


@dataclass
class ParSheetRow:
    """One row of a par sheet (probability/payout table).

    Attributes
    ----------
    hand_name : str
        Human-readable hand name.
    combinations : int
        Exact number of 7-card hands that produce this outcome.
    probability : float
        Probability of this outcome (combinations / total).
    payout : int
        Net payout per unit bet.
    contribution : float
        Expected return contribution = probability * payout.
    """
    hand_name: str
    combinations: int
    probability: float
    payout: int
    contribution: float


@dataclass
class TripsParSheet:
    """Complete par sheet for the UTH Trips bet.

    Attributes
    ----------
    rows : list[ParSheetRow]
        One row per hand ranking.
    total_combinations : int
        Total 7-card combinations (should be 133,784,560).
    house_edge : float
        House edge as a decimal (e.g., 0.0185 = 1.85%).
    rtp : float
        Return to player (1 - house_edge).
    hit_frequency : float
        Probability of any winning outcome.
    volatility_index : float
        Standard deviation of outcome per unit bet.
    """
    rows: list[ParSheetRow]
    total_combinations: int
    house_edge: float
    rtp: float
    hit_frequency: float
    volatility_index: float


def compute_trips_par_sheet(
    counts: dict[HandRank, int] | None = None
) -> TripsParSheet:
    """Compute the complete par sheet for the UTH Trips bet.

    Parameters
    ----------
    counts : dict or None
        Pre-computed 7-card hand counts by rank. If None, will enumerate
        all C(52,7) hands (takes several minutes in pure Python).

    Returns
    -------
    TripsParSheet
        Complete par sheet with all statistics.
    """
    if counts is None:
        counts = count_7card_by_rank()

    total = sum(counts.values())

    rows: list[ParSheetRow] = []
    ev = 0.0                 # Expected value (sum of probability * payout)
    hit_combos = 0           # Combinations that win
    variance_sum = 0.0       # For volatility calculation

    # Build par sheet rows in order (strongest hand first)
    for rank in [
        HandRank.ROYAL_FLUSH,
        HandRank.STRAIGHT_FLUSH,
        HandRank.FOUR_OF_A_KIND,
        HandRank.FULL_HOUSE,
        HandRank.FLUSH,
        HandRank.STRAIGHT,
        HandRank.THREE_OF_A_KIND,
        HandRank.TWO_PAIR,
        HandRank.ONE_PAIR,
        HandRank.HIGH_CARD,
    ]:
        combo_count = counts[rank]
        prob = combo_count / total
        payout = TRIPS_PAYTABLE[rank]
        contribution = prob * payout

        rows.append(ParSheetRow(
            hand_name=HAND_RANK_NAMES[rank],
            combinations=combo_count,
            probability=prob,
            payout=payout,
            contribution=contribution,
        ))

        ev += contribution

        if rank in WINNING_RANKS:
            hit_combos += combo_count

        # Variance: E[X^2] contribution
        variance_sum += prob * (payout ** 2)

    # House Edge = -EV (positive number means house wins)
    house_edge = -ev
    rtp = 1.0 - house_edge
    hit_frequency = hit_combos / total

    # Volatility Index = standard deviation per unit bet
    # Var(X) = E[X^2] - (E[X])^2
    variance = variance_sum - (ev ** 2)
    volatility_index = math.sqrt(variance)

    return TripsParSheet(
        rows=rows,
        total_combinations=total,
        house_edge=house_edge,
        rtp=rtp,
        hit_frequency=hit_frequency,
        volatility_index=volatility_index,
    )


def print_par_sheet(sheet: TripsParSheet) -> None:
    """Print a formatted par sheet to console.

    Parameters
    ----------
    sheet : TripsParSheet
        The par sheet to display.
    """
    print("=" * 80)
    print("ULTIMATE TEXAS HOLD'EM — TRIPS BET PAR SHEET")
    print("=" * 80)
    print()

    # Header
    print(f"{'Hand':<20} {'Combos':>15} {'Probability':>12} "
          f"{'Payout':>8} {'Return':>10}")
    print("-" * 70)

    # Rows
    for row in sheet.rows:
        print(f"{row.hand_name:<20} {row.combinations:>15,} "
              f"{row.probability:>11.6%} {row.payout:>7}:1 "
              f"{row.contribution:>+10.6f}")

    print("-" * 70)
    print(f"{'TOTAL':<20} {sheet.total_combinations:>15,} "
          f"{'100.000000%':>12} {'':>8} {-sheet.house_edge:>+10.6f}")

    print()
    print(f"  House Edge:       {sheet.house_edge:.4%}")
    print(f"  RTP:              {sheet.rtp:.4%}")
    print(f"  Hit Frequency:    {sheet.hit_frequency:.4%}")
    print(f"  Volatility Index: {sheet.volatility_index:.4f}")
    print("=" * 80)
