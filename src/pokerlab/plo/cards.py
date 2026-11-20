"""Card encoding shared by the PLO module.

Cards are integers 0..51: ``card = 4 * rank + suit`` with rank 0..12 = 2..A and
suit 0..3 = c, d, h, s.  This is the convention of ``pokerlab.math.fast_eval``
and of the pinned postflop-solver engine, so card ids mean the same thing
across the repository.
"""
from __future__ import annotations

from itertools import combinations
from math import comb
from typing import Iterable, Sequence

import numpy as np

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK: tuple[int, ...] = tuple(range(52))


class CardConflictError(ValueError):
    """The same physical card was assigned twice."""


def parse_card(text: str) -> int:
    text = text.strip()
    if len(text) != 2:
        raise ValueError(f"card must have two characters, got {text!r}")
    rank = RANKS.find(text[0].upper())
    suit = SUITS.find(text[1].lower())
    if rank < 0 or suit < 0:
        raise ValueError(f"unknown card {text!r}")
    return 4 * rank + suit


def parse_cards(text: str | Iterable[str]) -> tuple[int, ...]:
    """Parse ``"AsKd Qh"``-style text (or a list of card strings); rejects duplicates."""
    if isinstance(text, str):
        compact = "".join(text.split())
        if len(compact) % 2:
            raise ValueError(f"cards must have two characters each: {text!r}")
        parts = [compact[i:i + 2] for i in range(0, len(compact), 2)]
    else:
        parts = list(text)
    cards = tuple(parse_card(p) for p in parts)
    if len(set(cards)) != len(cards):
        raise CardConflictError(f"duplicate card in {text!r}")
    return cards


def format_card(card: int) -> str:
    if not 0 <= int(card) < 52:
        raise ValueError(f"card id out of range: {card}")
    return RANKS[int(card) >> 2] + SUITS[int(card) & 3]


def format_cards(cards: Iterable[int]) -> str:
    return "".join(format_card(c) for c in cards)


def validate_disjoint(*groups: Sequence[int]) -> None:
    """Raise CardConflictError if any card id appears twice across all groups."""
    seen: set[int] = set()
    for group in groups:
        for card in group:
            card = int(card)
            if not 0 <= card < 52:
                raise ValueError(f"card id out of range: {card}")
            if card in seen:
                raise CardConflictError(f"card {format_card(card)} used twice")
            seen.add(card)


def combo_index(cards: Sequence[int]) -> int:
    """Combinatorial-number-system index of a card set (order independent)."""
    return sum(comb(c, k + 1) for k, c in enumerate(sorted(int(c) for c in cards)))


def combo_index_array(cards: np.ndarray) -> np.ndarray:
    """Vectorised ``combo_index`` for an (N, k) array; rows need not be sorted."""
    s = np.sort(np.asarray(cards, dtype=np.int64), axis=1)
    out = np.zeros(s.shape[0], dtype=np.int64)
    for k in range(s.shape[1]):
        out += _COMB_TABLE[k + 1][s[:, k]]
    return out


# _COMB_TABLE[k][n] = C(n, k) for n in 0..52, k in 0..5
_COMB_TABLE = np.array([[comb(n, k) for n in range(53)] for k in range(6)], dtype=np.int64)


def all_hands(size: int = 4, dead: Iterable[int] = ()) -> np.ndarray:
    """All ``size``-card hands avoiding ``dead`` cards, rows sorted ascending.

    Rows follow ``itertools.combinations`` order over the live cards, so the
    result is deterministic.  For PLO4 on a river board this is C(47,4)=178,365.
    """
    dead_set = {int(c) for c in dead}
    live = [c for c in DECK if c not in dead_set]
    return np.array(list(combinations(live, size)), dtype=np.int16).reshape(-1, size)


def hand_mask(hand: Iterable[int]) -> int:
    mask = 0
    for c in hand:
        mask |= 1 << int(c)
    return mask
