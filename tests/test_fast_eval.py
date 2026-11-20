"""Tests for fast integer-based evaluator (Step A).

CRITICAL: The fast evaluator MUST produce identical results to the original.
If any count differs, our fast code has a bug.
"""

import pytest
from pokerlab.math.fast_eval import (
    evaluate_5card_fast,
    evaluate_best5_fast,
    count_5card_by_rank_fast,
)
from pokerlab.math.evaluator import HandRank


class TestFastEval5Card:
    """Test individual hand classifications using integer encoding.

    Card encoding reminder: card = rank * 4 + suit
    rank: 0=2, 1=3, ..., 12=A    suit: 0=c, 1=d, 2=h, 3=s
    So: As=51, Ah=50, Ad=49, Ac=48, Ks=47, Kh=46, ...
    """

    def test_royal_flush(self):
        # Ah Kh Qh Jh Th = 50, 46, 42, 38, 34
        assert evaluate_5card_fast(50, 46, 42, 38, 34) == 9

    def test_straight_flush(self):
        # 9d 8d 7d 6d 5d = 29, 25, 21, 17, 13
        assert evaluate_5card_fast(29, 25, 21, 17, 13) == 8

    def test_wheel_straight_flush(self):
        # Ac 2c 3c 4c 5c = 48, 0, 4, 8, 12
        assert evaluate_5card_fast(48, 0, 4, 8, 12) == 8

    def test_four_of_a_kind(self):
        # Ks Kh Kd Kc 2s = 47, 46, 45, 44, 3
        assert evaluate_5card_fast(47, 46, 45, 44, 3) == 7

    def test_full_house(self):
        # Qs Qh Qd Jc Jh = 43, 42, 41, 38, 37
        # Wait, let me recalculate. Q=rank10, J=rank9
        # Qs=10*4+3=43, Qh=10*4+2=42, Qd=10*4+1=41
        # Jc=9*4+0=36, Jh=9*4+2=38
        assert evaluate_5card_fast(43, 42, 41, 36, 38) == 6

    def test_flush(self):
        # As Js 9s 7s 2s = 51, 39, 31, 23, 3
        # Wait: A=rank12, J=rank9, 9=rank7, 7=rank5, 2=rank0
        # As=12*4+3=51, Js=9*4+3=39, 9s=7*4+3=31, 7s=5*4+3=23, 2s=0*4+3=3
        assert evaluate_5card_fast(51, 39, 31, 23, 3) == 5

    def test_straight(self):
        # Ts 9h 8d 7c 6s = 34+1=35? Let me recalc
        # T=rank8: 8*4+3=35(Ts), 9h=7*4+2=30, 8d=6*4+1=25, 7c=5*4+0=20, 6s=4*4+3=19
        assert evaluate_5card_fast(35, 30, 25, 20, 19) == 4

    def test_wheel_straight(self):
        # As 2h 3d 4c 5s = 51, 2, 5, 8, 15
        # A=12: 12*4+3=51, 2=0: 0*4+2=2, 3=1: 1*4+1=5, 4=2: 2*4+0=8, 5=3: 3*4+3=15
        assert evaluate_5card_fast(51, 2, 5, 8, 15) == 4

    def test_three_of_a_kind(self):
        # 7s 7h 7d Kc 2s = 5*4+3=23, 5*4+2=22, 5*4+1=21, 11*4+0=44, 0*4+3=3
        assert evaluate_5card_fast(23, 22, 21, 44, 3) == 3

    def test_two_pair(self):
        # As Ah Kd Kc 2s = 51, 50, 45, 44, 3
        assert evaluate_5card_fast(51, 50, 45, 44, 3) == 2

    def test_one_pair(self):
        # Js Jh 9d 7c 2s = 9*4+3=39, 9*4+2=38, 7*4+1=29, 5*4+0=20, 0*4+3=3
        assert evaluate_5card_fast(39, 38, 29, 20, 3) == 1

    def test_high_card(self):
        # As Jh 9d 7c 2s = 51, 38, 29, 20, 3 — wait, that's same as one_pair test
        # Let's use: As Jh 9d 7c 3s = 51, 38, 29, 20, 7
        # A=12,J=9,9=7,7=5,3=1: 51,38,29,20,7
        assert evaluate_5card_fast(51, 38, 29, 20, 7) == 0


class TestFastCount5Card:
    """Verify fast 5-card enumeration matches known exact values.

    This is the ultimate correctness test: if all 2,598,960 hands
    are classified identically to the original evaluator, the fast
    version is provably correct.
    """

    @pytest.fixture(scope="class")
    def counts(self):
        return count_5card_by_rank_fast()

    def test_total(self, counts):
        assert sum(counts.values()) == 2_598_960

    def test_royal_flush(self, counts):
        assert counts[9] == 4

    def test_straight_flush(self, counts):
        assert counts[8] == 36

    def test_four_of_a_kind(self, counts):
        assert counts[7] == 624

    def test_full_house(self, counts):
        assert counts[6] == 3_744

    def test_flush(self, counts):
        assert counts[5] == 5_108

    def test_straight(self, counts):
        assert counts[4] == 10_200

    def test_three_of_a_kind(self, counts):
        assert counts[3] == 54_912

    def test_two_pair(self, counts):
        assert counts[2] == 123_552

    def test_one_pair(self, counts):
        assert counts[1] == 1_098_240

    def test_high_card(self, counts):
        assert counts[0] == 1_302_540


class TestFastEval7Card:
    def test_royal_in_7(self):
        # Ah Kh Qh Jh Th 2c 3d = 50,46,42,38,34, 0, 5
        assert evaluate_best5_fast([50, 46, 42, 38, 34, 0, 5]) == 9

    def test_full_house_in_7(self):
        # Ks Kh Kd Qc Qs 2h 3d = 47,46,45,40,43, 2, 5
        # K=rank11: 11*4+3=47, 11*4+2=46, 11*4+1=45
        # Q=rank10: 10*4+0=40, 10*4+3=43
        # 2h=0*4+2=2, 3d=1*4+1=5
        assert evaluate_best5_fast([47, 46, 45, 40, 43, 2, 5]) == 6
