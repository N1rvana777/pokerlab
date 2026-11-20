"""Exact hand ranking, including PLO's "exactly two hole cards + three board cards" rule.

Rank keys are integers; a larger key is a stronger hand and equal keys tie:

    key = category << 20 | k0 << 16 | k1 << 12 | k2 << 8 | k3 << 4 | k4

``category`` runs 0 (high card) .. 8 (straight flush).  ``k0..k4`` are the five
ranks (0..12 = 2..A) ordered by (multiplicity desc, rank desc); straights and
straight flushes use ``(top, 0, 0, 0, 0)`` with the wheel's top equal to 3 ('5').

Two independent implementations are kept on purpose.  ``rank5_reference`` is a
scalar Counter-based oracle used by tests and the reference solvers;
``rank5_batch`` is the vectorised version production code calls.  The legacy
``pokerlab.math`` evaluators only return categories and must not be used for
showdowns.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Sequence

import numpy as np

from pokerlab.plo.cards import CardConflictError, format_card

CATEGORY_NAMES = (
    "high card", "pair", "two pair", "three of a kind", "straight",
    "flush", "full house", "four of a kind", "straight flush",
)
HOLE_PAIRS: tuple[tuple[int, int], ...] = tuple(combinations(range(4), 2))
_RANK_CHARS = "23456789TJQKA"
_CHUNK_ROWS = 600_000


def _encode(category: int, kickers: Sequence[int]) -> int:
    k = list(kickers) + [0] * (5 - len(kickers))
    return (category << 20) | (k[0] << 16) | (k[1] << 12) | (k[2] << 8) | (k[3] << 4) | k[4]


def category_of(key: int) -> int:
    return int(key) >> 20


def describe_rank(key: int) -> str:
    key = int(key)
    ranks = [(key >> shift) & 15 for shift in (16, 12, 8, 4, 0)]
    category = key >> 20
    if category in (4, 8):
        return f"{CATEGORY_NAMES[category]}, {_RANK_CHARS[ranks[0]]} high"
    return f"{CATEGORY_NAMES[category]} ({' '.join(_RANK_CHARS[r] for r in ranks)})"


def rank5_reference(cards: Sequence[int]) -> int:
    """Scalar oracle for one 5-card hand."""
    cards = [int(c) for c in cards]
    if len(cards) != 5 or len(set(cards)) != 5 or not all(0 <= c < 52 for c in cards):
        raise ValueError(f"need 5 distinct cards, got {cards}")
    ranks = [c >> 2 for c in cards]
    counts = Counter(ranks)
    ordered = sorted(ranks, key=lambda r: (counts[r], r), reverse=True)
    flush = len({c & 3 for c in cards}) == 1
    distinct = sorted(counts, reverse=True)
    top = None
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            top = distinct[0]
        elif distinct == [12, 3, 2, 1, 0]:
            top = 3
    shape = sorted(counts.values(), reverse=True)
    if top is not None and flush:
        return _encode(8, [top])
    if shape[0] == 4:
        return _encode(7, ordered)
    if shape == [3, 2]:
        return _encode(6, ordered)
    if flush:
        return _encode(5, ordered)
    if top is not None:
        return _encode(4, [top])
    if shape[0] == 3:
        return _encode(3, ordered)
    if shape == [2, 2, 1]:
        return _encode(2, ordered)
    if shape[0] == 2:
        return _encode(1, ordered)
    return _encode(0, ordered)


def _check_plo_cards(hole: Sequence[int], board: Sequence[int]) -> None:
    if len(hole) != 4:
        raise ValueError(f"PLO4 hole must have 4 cards, got {len(hole)}")
    if not 3 <= len(board) <= 5:
        raise ValueError(f"board must have 3..5 cards, got {len(board)}")
    seen: set[int] = set()
    for c in list(hole) + list(board):
        if c in seen:
            raise CardConflictError(f"card {format_card(c)} used twice")
        seen.add(c)


def plo_rank_reference(hole: Sequence[int], board: Sequence[int]) -> int:
    """Best hand using exactly two of the four hole cards and three board cards."""
    hole = [int(c) for c in hole]
    board = [int(c) for c in board]
    _check_plo_cards(hole, board)
    return max(rank5_reference([hole[a], hole[b], *trip])
               for a, b in HOLE_PAIRS for trip in combinations(board, 3))


def rank5_batch(cards: np.ndarray) -> np.ndarray:
    """Vectorised rank keys for an (N, 5) array of card ids (no validation)."""
    cards = np.asarray(cards)
    if cards.ndim != 2 or cards.shape[1] != 5:
        raise ValueError("expected an (N, 5) array")
    out = np.empty(cards.shape[0], dtype=np.int32)
    for start in range(0, cards.shape[0], _CHUNK_ROWS):
        out[start:start + _CHUNK_ROWS] = _rank5_chunk(cards[start:start + _CHUNK_ROWS])
    return out


def _rank5_chunk(cards: np.ndarray) -> np.ndarray:
    c = cards.astype(np.int32, copy=False)
    r = c >> 2
    s = c & 3
    flush = (s == s[:, :1]).all(axis=1)
    counts = (r[:, :, None] == np.arange(13, dtype=np.int32)).sum(axis=1, dtype=np.int32)
    multiplicity = np.take_along_axis(counts, r, axis=1)
    ordered = (-np.sort(-(multiplicity * 16 + r), axis=1)) & 15
    distinct = (counts > 0).sum(axis=1)
    max_count = counts.max(axis=1)
    rank_sorted = np.sort(r, axis=1)
    five = distinct == 5
    wheel = five & (rank_sorted[:, 4] == 12) & (rank_sorted[:, 3] == 3)
    straight = (five & (rank_sorted[:, 4] - rank_sorted[:, 0] == 4)) | wheel
    top = np.where(wheel, 3, rank_sorted[:, 4])

    category = np.zeros(c.shape[0], dtype=np.int32)
    category[(max_count == 2) & (distinct == 4)] = 1
    category[(max_count == 2) & (distinct == 3)] = 2
    category[(max_count == 3) & (distinct == 3)] = 3
    category[straight] = 4
    category[flush & ~straight] = 5
    category[(max_count == 3) & (distinct == 2)] = 6
    category[max_count == 4] = 7
    category[straight & flush] = 8

    packed = ((ordered[:, 0] << 16) | (ordered[:, 1] << 12) | (ordered[:, 2] << 8)
              | (ordered[:, 3] << 4) | ordered[:, 4])
    packed = np.where(straight, top << 16, packed)
    return (category << 20) | packed


def _check_batch(holes: np.ndarray, board: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    holes = np.asarray(holes, dtype=np.int32)
    board_arr = np.asarray([int(c) for c in board], dtype=np.int32)
    if holes.ndim != 2 or holes.shape[1] != 4:
        raise ValueError("expected an (N, 4) array of hole cards")
    if not 3 <= board_arr.size <= 5 or len(set(board_arr.tolist())) != board_arr.size:
        raise ValueError("board must have 3..5 distinct cards")
    if holes.size and np.isin(holes, board_arr).any():
        raise CardConflictError("a hole card is also on the board")
    return holes, board_arr


# _PAIR_ID[a, b] = index of the unordered card pair {a, b} in 0..1325
_PAIR_ID = np.full((52, 52), -1, dtype=np.int32)
for _k, (_a, _b) in enumerate(combinations(range(52), 2)):
    _PAIR_ID[_a, _b] = _PAIR_ID[_b, _a] = _k
_ALL_PAIRS = np.array(list(combinations(range(52), 2)), dtype=np.int32)


def best_pair_ranks(board: Sequence[int]) -> np.ndarray:
    """For every 2-card hole pair, the best rank using that pair + 3 of the board (-1 if blocked)."""
    board_arr = np.asarray([int(c) for c in board], dtype=np.int32)
    triples = board_arr[np.array(list(combinations(range(board_arr.size), 3)))]
    live = ~np.isin(_ALL_PAIRS, board_arr).any(axis=1)
    pairs = _ALL_PAIRS[live]
    five = np.concatenate([np.broadcast_to(pairs[:, None, :], (len(pairs), len(triples), 2)),
                           np.broadcast_to(triples[None, :, :], (len(pairs), len(triples), 3))],
                          axis=2).reshape(-1, 5)
    best = np.full(len(_ALL_PAIRS), -1, dtype=np.int32)
    best[live] = _rank5_chunk(five).reshape(len(pairs), len(triples)).max(axis=1)
    return best


def plo_rank_batch(holes: np.ndarray, board: Sequence[int]) -> np.ndarray:
    """PLO4 rank keys for an (N, 4) array of hole cards on one 3..5 card board.

    Best(hand) = max over its 6 hole pairs of max over board triples, so a per-board table of
    the best rank of each of the <= 1,326 hole pairs turns ranking into 6 lookups per hand.
    ``plo_rank_batch_direct`` evaluates all 60 five-card combinations per hand instead.
    """
    holes, board_arr = _check_batch(holes, board)
    best = best_pair_ranks(board_arr)
    ids = _PAIR_ID[holes[:, np.array([a for a, _ in HOLE_PAIRS])],
                   holes[:, np.array([b for _, b in HOLE_PAIRS])]]
    return best[ids].max(axis=1) if holes.shape[0] else np.empty(0, dtype=np.int32)


def plo_rank_batch_direct(holes: np.ndarray, board: Sequence[int]) -> np.ndarray:
    """Same as ``plo_rank_batch`` by brute force over all 2+3 combinations (cross-check)."""
    holes, board_arr = _check_batch(holes, board)
    triples = board_arr[np.array(list(combinations(range(board_arr.size), 3)))]
    pairs = holes[:, np.array(HOLE_PAIRS)]                       # (N, 6, 2)
    per_hand = len(HOLE_PAIRS) * len(triples)
    out = np.empty(holes.shape[0], dtype=np.int32)
    step = max(1, _CHUNK_ROWS // per_hand)
    for start in range(0, holes.shape[0], step):
        p = pairs[start:start + step]
        n = p.shape[0]
        five = np.concatenate([
            np.broadcast_to(p[:, :, None, :], (n, len(HOLE_PAIRS), len(triples), 2)),
            np.broadcast_to(triples[None, None, :, :], (n, len(HOLE_PAIRS), len(triples), 3)),
        ], axis=3).reshape(-1, 5)
        out[start:start + n] = _rank5_chunk(five).reshape(n, per_hand).max(axis=1)
    return out
