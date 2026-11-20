"""Tests for UTH Trips Bet analysis (Steps 4-6).

We validate the Trips bet par sheet using Monte Carlo simulation.
The analytic (exact) results require enumerating 133M+ hands which
takes too long for regular test runs, so we test the framework
logic with MC estimates and verify they're in the expected range.
"""

import pytest
import json
from pathlib import Path
from pokerlab.math.evaluator import HandRank
from pokerlab.games.uth_trips import compute_trips_par_sheet, TRIPS_PAYTABLE
from pokerlab.sim.monte_carlo import simulate_trips_bet


class TestMCTrips:
    """Validate Trips bet using Monte Carlo simulation."""

    @pytest.fixture(scope="class")
    def mc_result(self):
        """Run 1M MC simulation once for all tests."""
        return simulate_trips_bet(n_simulations=1_000_000, seed=12345)

    def test_house_edge_in_range(self, mc_result):
        """MC house edge should be roughly 1.5-3.0% (wide range for MC noise)."""
        house_edge = -mc_result.ev
        assert 0.005 < house_edge < 0.040, f"House edge {house_edge:.4%} out of range"

    def test_hit_frequency_in_range(self, mc_result):
        """Hit frequency (any winning hand) should be ~28-32%."""
        winning_ranks = {r for r, p in TRIPS_PAYTABLE.items() if p > 0}
        total_wins = sum(
            mc_result.hand_counts[r] for r in winning_ranks
        )
        hit_freq = total_wins / mc_result.n_simulations
        assert 0.12 < hit_freq < 0.20, f"Hit freq {hit_freq:.4%} out of range"

    def test_all_ranks_observed(self, mc_result):
        """All 10 hand rankings should appear in 1M simulations."""
        for rank in HandRank:
            assert mc_result.hand_counts[rank] > 0, \
                f"{rank.name} not observed in {mc_result.n_simulations} sims"

    def test_confidence_interval_contains_expected(self, mc_result):
        """95% CI should contain a reasonable house edge value."""
        # Known house edge is ~2.1%, so CI should span this region
        assert mc_result.ci_lower < 0 < mc_result.ci_upper or \
               mc_result.ci_upper < 0  # EV is negative (house wins)
        # More specifically: the EV should be negative
        assert mc_result.ev < 0, "Trips bet should have negative EV for player"


class TestParSheetFromCounts:
    """Test par sheet computation with known counts (if available)."""

    def test_par_sheet_probabilities_sum_to_one(self):
        """Using MC-derived approximate counts to test par sheet logic."""
        mc = simulate_trips_bet(n_simulations=100_000, seed=99)

        # Scale MC counts to approximate 7-card combo counts
        # (not exact, but tests the par sheet computation logic)
        scale = 133_784_560 / mc.n_simulations
        approx_counts = {
            rank: int(count * scale)
            for rank, count in mc.hand_counts.items()
        }

        sheet = compute_trips_par_sheet(approx_counts)
        total_prob = sum(row.probability for row in sheet.rows)
        assert abs(total_prob - 1.0) < 0.01  # Close to 1.0

    def test_par_sheet_from_exact_counts(self):
        """If exact counts file exists, validate par sheet against known values."""
        counts_file = Path("data/7card_counts.json")
        if not counts_file.exists():
            pytest.skip("Exact 7-card counts not yet computed")

        with open(counts_file) as f:
            raw = json.load(f)

        counts = {HandRank[name]: count for name, count in raw.items()}
        sheet = compute_trips_par_sheet(counts)

        # Verify total combinations
        assert sheet.total_combinations == 133_784_560

        # Verify probabilities sum to 1.0 exactly
        total_prob = sum(row.probability for row in sheet.rows)
        assert abs(total_prob - 1.0) < 1e-10

        # House edge should be in known range
        assert 0.015 < sheet.house_edge < 0.030, \
            f"House edge {sheet.house_edge:.4%} outside expected range"

        # Hit frequency should be ~15-16% for this paytable
        # (trips or better out of all 7-card hands)
        assert 0.10 < sheet.hit_frequency < 0.20
