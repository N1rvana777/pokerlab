"""Pot-limit betting arithmetic shared by the engine and the subgame trees.

Notation, in integer chips, for the player about to act:

    P  pot before the action, including every chip already put in this round
    h  chips this player has already put in this round
    c  chips this player still has to call       (current bet = h + c)

    pot after calling        P + c
    pot-limit max raise-to   h + P + 2c           (= current bet + (P + c))
    fraction-f raise-to      h + c + f (P + c)    (f = 1 is the pot-size raise; an opening
                                                   bet has h = c = 0, i.e. f P)
    minimum raise-to         current bet + last full increment (big blind when nobody bet)

A short all-in below the minimum is legal; an all-in above the pot limit is not.  The
engine and the subgame trees both call these functions, so they cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import floor
from typing import Iterable, Sequence

DEFAULT_SIZES: tuple[Fraction, ...] = (Fraction(1, 3), Fraction(1, 2), Fraction(2, 3), Fraction(1))


def parse_fraction(value) -> Fraction:
    """Exact pot fraction from "1/3", 0.5, 1 or a Fraction; pot limit means 0 < f <= 1."""
    f = value if isinstance(value, Fraction) else Fraction(str(value).strip())
    if not 0 < f <= 1:
        raise ValueError(f"pot-limit size fraction must be in (0, 1], got {value!r}")
    return f


def parse_sizes(values: Iterable) -> tuple[Fraction, ...]:
    return tuple(sorted({parse_fraction(v) for v in values}))


def round_chips(amount: Fraction) -> int:
    """Nearest whole chip, halves rounded up (exact rational arithmetic, no floats)."""
    return floor(amount + Fraction(1, 2))


def max_raise_to(P: int, h: int, c: int) -> int:
    return h + P + 2 * c


def fraction_raise_to(P: int, h: int, c: int, f: Fraction) -> int:
    return round_chips(h + c + f * (P + c))


@dataclass(frozen=True)
class RaiseWindow:
    """Legal raise-to interval for one player (raise-to = street commitment after acting)."""
    min_to: int
    max_to: int
    pot_max_to: int     # pot-limit cap before the stack limit
    all_in_to: int

    @property
    def max_is_all_in(self) -> bool:
        return self.max_to == self.all_in_to


def raise_window(P: int, h: int, c: int, stack: int, last_full_increment: int,
                 big_blind: int) -> RaiseWindow | None:
    """Raise-to window, or None when the stack does not go beyond a call.

    ``stack`` is what the player has behind before acting.  Raise *rights* (reopening,
    a live opponent, raise caps) are the caller's business.
    """
    current = h + c
    all_in_to = h + stack
    if all_in_to <= current:
        return None
    full_min = big_blind if current == 0 else current + last_full_increment
    pot_max = max(max_raise_to(P, h, c), full_min)
    return RaiseWindow(min(full_min, all_in_to), min(pot_max, all_in_to), pot_max, all_in_to)


def abstract_targets(P: int, h: int, c: int, window: RaiseWindow, fractions: Sequence[Fraction],
                     include_min: bool = True, include_max: bool = True) -> list[int]:
    """Raise-to amounts of the action abstraction at one decision.

    Fractional sizes outside the legal window are dropped (not clamped); the window's
    boundaries are added as explicit actions: the minimum legal bet/raise (or a short
    all-in below it) and the maximum (the pot-size raise, or the short all-in when the
    stack is below the pot limit).  Duplicates collapse.
    """
    out = {t for t in (fraction_raise_to(P, h, c, f) for f in fractions)
           if window.min_to <= t <= window.max_to}
    if include_min:
        out.add(window.min_to)
    if include_max:
        out.add(window.max_to)
    return sorted(out)
