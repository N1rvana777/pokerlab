"""Monte Carlo simulation framework for casino game analysis.

Monte Carlo simulation estimates expected values by random sampling.
For the Trips bet: deal random 7-card hands, evaluate, look up payout,
and average over millions of trials.

Why both analytic AND Monte Carlo?
    - Analytic gives the EXACT answer (required for a par sheet)
    - Monte Carlo VALIDATES the analytic answer (catches bugs)
    - In a job interview, showing both proves you understand the difference
"""

import random
import math
from dataclasses import dataclass

from pokerlab.core.deck import Deck
from pokerlab.math.evaluator import evaluate_best5, HandRank


@dataclass
class MCResult:
    """Results from a Monte Carlo simulation run.

    Attributes
    ----------
    ev : float
        Estimated expected value per unit bet.
    std_error : float
        Standard error of the EV estimate (shrinks with more samples).
    ci_lower : float
        Lower bound of 95% confidence interval.
    ci_upper : float
        Upper bound of 95% confidence interval.
    n_simulations : int
        Number of simulations run.
    hand_counts : dict[HandRank, int]
        Count of each hand ranking observed.
    """
    ev: float
    std_error: float
    ci_lower: float
    ci_upper: float
    n_simulations: int
    hand_counts: dict[HandRank, int]


def simulate_trips_bet(
    n_simulations: int = 1_000_000,
    paytable: dict[HandRank, int] | None = None,
    seed: int = 42,
) -> MCResult:
    """Run Monte Carlo simulation of the UTH Trips bet.

    Parameters
    ----------
    n_simulations : int
        Number of random 7-card hands to deal.
    paytable : dict or None
        Payout table mapping HandRank -> net payout. Uses default if None.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    MCResult
        Simulation results with EV estimate and confidence interval.
    """
    if paytable is None:
        # Default Vegas paytable
        paytable = {
            HandRank.ROYAL_FLUSH: 50,
            HandRank.STRAIGHT_FLUSH: 40,
            HandRank.FOUR_OF_A_KIND: 30,
            HandRank.FULL_HOUSE: 8,
            HandRank.FLUSH: 6,
            HandRank.STRAIGHT: 5,
            HandRank.THREE_OF_A_KIND: 3,
            HandRank.TWO_PAIR: -1,
            HandRank.ONE_PAIR: -1,
            HandRank.HIGH_CARD: -1,
        }

    rng = random.Random(seed)
    all_cards = Deck.full_deck()

    # Accumulators for running statistics
    total_payout = 0.0
    total_payout_sq = 0.0  # For variance calculation
    hand_counts: dict[HandRank, int] = {rank: 0 for rank in HandRank}

    for _ in range(n_simulations):
        # Deal 7 random cards (sample without replacement)
        hand = rng.sample(all_cards, 7)
        rank = evaluate_best5(hand)
        payout = paytable[rank]

        total_payout += payout
        total_payout_sq += payout * payout
        hand_counts[rank] += 1

    # Calculate statistics
    ev = total_payout / n_simulations

    # Variance: Var = E[X^2] - E[X]^2
    mean_sq = total_payout_sq / n_simulations
    variance = mean_sq - ev * ev

    # Standard error = sqrt(variance / n)
    std_error = math.sqrt(variance / n_simulations)

    # 95% confidence interval: EV ± 1.96 * SE
    ci_lower = ev - 1.96 * std_error
    ci_upper = ev + 1.96 * std_error

    return MCResult(
        ev=ev,
        std_error=std_error,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        n_simulations=n_simulations,
        hand_counts=hand_counts,
    )
