"""Tests for Connector Bonus side bet (Step 8)."""

from pokerlab.games.connector_bonus import longest_run, connector_payout, simulate_connector_bonus


class TestLongestRun:
    def test_no_run(self):
        # Ace adds 1, which is adjacent to 2, so [2,5,8,11,14] has run of 2 (A-2)
        assert longest_run([3, 6, 9, 12]) == 1

    def test_pair(self):
        """Duplicate ranks don't extend a run."""
        assert longest_run([5, 5, 5, 5]) == 1

    def test_run_of_3(self):
        assert longest_run([2, 3, 4, 8, 12]) == 3

    def test_run_of_5(self):
        assert longest_run([6, 7, 8, 9, 10, 2, 14]) == 5

    def test_run_of_7(self):
        assert longest_run([2, 3, 4, 5, 6, 7, 8]) == 7

    def test_ace_low_straight(self):
        """A-2-3-4-5 should be a run of 5."""
        assert longest_run([14, 2, 3, 4, 5]) == 5

    def test_ace_high_run(self):
        """Q-K-A should be a run of 3."""
        assert longest_run([12, 13, 14, 3, 7]) == 3

    def test_ace_does_not_wrap(self):
        """K-A-2 should NOT be a run of 3 (no wrap-around)."""
        assert longest_run([13, 14, 2]) == 2

    def test_two_separate_runs(self):
        """Pick the longer run."""
        assert longest_run([2, 3, 4, 9, 10, 11, 12]) == 4


class TestConnectorPayout:
    def test_loss(self):
        """No run of 3+ -> loss."""
        assert connector_payout([3, 6, 9, 12, 4, 8, 11]) == -1  # longest run is 2 (3-4)

    def test_push(self):
        """3-card run = push (0 payout)."""
        assert connector_payout([2, 3, 4, 8, 11, 13, 9]) == 0  # run of 3: 2-3-4, also 8-9

    def test_win_4(self):
        assert connector_payout([5, 6, 7, 8, 12, 14, 2]) == 1

    def test_win_5(self):
        assert connector_payout([5, 6, 7, 8, 9, 12, 14]) == 3


class TestMCConnectorBonus:
    def test_house_edge_reasonable(self):
        result = simulate_connector_bonus(n_simulations=500_000, seed=99)
        he = result["house_edge"]
        # Should be in 0-5% range
        assert -0.02 < he < 0.06, f"House edge {he:.4%} out of range"

    def test_all_run_lengths_present(self):
        result = simulate_connector_bonus(n_simulations=500_000, seed=99)
        dist = result["run_distribution"]
        # Should see runs of 1 through at least 6
        for r in [1, 2, 3, 4, 5, 6]:
            assert r in dist, f"Run of {r} not observed"
