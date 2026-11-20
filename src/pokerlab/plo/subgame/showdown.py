"""Showdown / card-removal oracles for two-player subgames.

For player p's hand i and an opponent reach vector r, solvers need

* ``compat[i] = sum_j r[j] * [hands i and j share no card]``
* ``win[i]    = sum_j r[j] * [no shared card] * (1 if i beats j, 0.5 if tie, 0 if loses)``

``DenseShowdown`` stores explicit n0 x n1 matrices (exact, small ranges, also the
cross-check).  ``InclusionExclusionShowdown`` handles full PLO4 ranges without a
quadratic matrix: opponent hands are sorted by strength once, and card removal
is applied with inclusion-exclusion over the 15 non-empty subsets of each
4-card hand, using prefix sums restricted to "weaker than" / "not stronger
than" thresholds.  This generalises the usual Hold'em blocker trick to four
hole cards.
"""
from __future__ import annotations

from itertools import combinations
from math import comb

import numpy as np


def hand_masks(hands: np.ndarray) -> np.ndarray:
    """uint64 bitmask per hand (bit c set for card c)."""
    hands = np.asarray(hands, dtype=np.uint64)
    return np.bitwise_or.reduce(np.left_shift(np.uint64(1), hands), axis=1)


def win_matrix(s_me: np.ndarray, s_opp: np.ndarray) -> np.ndarray:
    a = np.asarray(s_me)[:, None]
    b = np.asarray(s_opp)[None, :]
    return np.where(a > b, 1.0, np.where(a == b, 0.5, 0.0))


class DenseShowdown:
    kind = "dense"

    def __init__(self, compat: np.ndarray, win0: np.ndarray) -> None:
        self.compat = np.asarray(compat, dtype=np.float64)
        self.win0 = np.asarray(win0, dtype=np.float64) * self.compat
        self.win1t = (self.compat - self.win0).T.copy()
        self.compat_t = self.compat.T.copy()

    @classmethod
    def from_hands(cls, h0: np.ndarray, s0: np.ndarray, h1: np.ndarray, s1: np.ndarray) -> "DenseShowdown":
        m0, m1 = hand_masks(h0), hand_masks(h1)
        compat = (m0[:, None] & m1[None, :]) == 0
        return cls(compat, win_matrix(s0, s1))

    def masses(self, player: int, opp_reach: np.ndarray,
               need_win: bool = True) -> tuple[np.ndarray, np.ndarray | None]:
        compat, win = (self.compat, self.win0) if player == 0 else (self.compat_t, self.win1t)
        return compat @ opp_reach, (win @ opp_reach if need_win else None)

    def versus(self, player: int, j: int) -> tuple[np.ndarray, np.ndarray]:
        """Compatibility and win share of every hand of ``player`` against opponent hand ``j``."""
        if player == 0:
            return self.compat[:, j], self.win0[:, j]
        return self.compat_t[:, j], self.win1t[:, j]

    def memory_bytes(self) -> int:
        return self.compat.nbytes * 4


# subset key offsets: singles, pairs, triples, quads
_OFFSETS = (0, 52, 52 + comb(52, 2), 52 + comb(52, 2) + comb(52, 3))
_SUBSETS = [tuple(s) for size in (1, 2, 3, 4) for s in combinations(range(4), size)]
_SIGNS = np.array([(-1.0) ** len(s) for s in _SUBSETS])
_COMB = np.array([[comb(n, k) for n in range(53)] for k in range(5)], dtype=np.int64)


def subset_keys(hands: np.ndarray) -> np.ndarray:
    """(N, 15) integer keys of every non-empty subset of each 4-card hand."""
    h = np.sort(np.asarray(hands, dtype=np.int64), axis=1)
    keys = np.empty((h.shape[0], len(_SUBSETS)), dtype=np.int64)
    for col, subset in enumerate(_SUBSETS):
        index = np.zeros(h.shape[0], dtype=np.int64)
        for k, pos in enumerate(subset):
            index += _COMB[k + 1][h[:, pos]]
        keys[:, col] = _OFFSETS[len(subset) - 1] + index
    return keys


class _Side:
    """Precomputed event/query layout for one querying player."""

    def __init__(self, h_me, s_me, h_opp, s_opp) -> None:
        m = h_opp.shape[0]
        self.order = np.argsort(s_opp, kind="stable")
        sorted_strength = np.asarray(s_opp)[self.order]
        opp_keys = subset_keys(np.asarray(h_opp)[self.order])            # (m, 15)
        positions = np.repeat(np.arange(m, dtype=np.int64), opp_keys.shape[1])
        flat = opp_keys.ravel()
        event_order = np.lexsort((positions, flat))
        combined = flat[event_order] * (m + 1) + positions[event_order]
        self.event_src = self.order[positions[event_order]]               # opp hand per event
        self.t_less = np.searchsorted(sorted_strength, s_me, side="left")
        self.t_leq = np.searchsorted(sorted_strength, s_me, side="right")
        my_keys = subset_keys(h_me) * (m + 1)                               # (n, 15)
        self.q_start = np.searchsorted(combined, my_keys)
        self.q_all = np.searchsorted(combined, my_keys + m)
        self.q_less = np.searchsorted(combined, my_keys + self.t_less[:, None])
        self.q_leq = np.searchsorted(combined, my_keys + self.t_leq[:, None])
        self.h_me = np.asarray(h_me)
        self.mask_me = hand_masks(h_me)
        self.s_me = np.asarray(s_me)

    def nbytes(self) -> int:
        return sum(getattr(self, k).nbytes for k in
                   ("order", "event_src", "t_less", "t_leq", "q_start", "q_all", "q_less", "q_leq"))


class InclusionExclusionShowdown:
    kind = "inclusion_exclusion"

    def __init__(self, h0: np.ndarray, s0: np.ndarray, h1: np.ndarray, s1: np.ndarray) -> None:
        self.sides = (_Side(h0, s0, h1, s1), _Side(h1, s1, h0, s0))
        self.masks = (hand_masks(h0), hand_masks(h1))
        self.strength = (np.asarray(s0), np.asarray(s1))

    def masses(self, player: int, opp_reach: np.ndarray,
               need_win: bool = True) -> tuple[np.ndarray, np.ndarray | None]:
        side = self.sides[player]
        cumulative = np.concatenate(([0.0], np.cumsum(opp_reach[side.event_src])))
        prefix = np.concatenate(([0.0], np.cumsum(opp_reach[side.order])))
        base = cumulative[side.q_start]

        def adjusted(q_idx: np.ndarray, totals) -> np.ndarray:
            return totals + (cumulative[q_idx] - base) @ _SIGNS

        compat = adjusted(side.q_all, prefix[-1])
        if not need_win:
            return compat, None
        less = adjusted(side.q_less, prefix[side.t_less])
        leq = adjusted(side.q_leq, prefix[side.t_leq])
        return compat, 0.5 * (less + leq)

    def versus(self, player: int, j: int) -> tuple[np.ndarray, np.ndarray]:
        other = 1 - player
        compat = ((self.masks[player] & self.masks[other][j]) == 0).astype(np.float64)
        s = self.strength[player]
        sj = self.strength[other][j]
        win = np.where(s > sj, 1.0, np.where(s == sj, 0.5, 0.0)) * compat
        return compat, win

    def memory_bytes(self) -> int:
        return sum(side.nbytes() for side in self.sides)
