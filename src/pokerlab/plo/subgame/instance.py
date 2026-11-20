"""Subgame instances: betting tree + private hands + chance weights + showdown oracle.

The PLO river instance is the first-round target: a heads-up PLO4 river with a
fixed board, explicit (or seeded-sampled) private ranges, a pot and stacks, and
a discrete pot-limit betting abstraction.  Ranges are inputs (assumptions), not
derived from a blueprint, so a solution is an equilibrium of *this* subgame only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from pokerlab.plo.betting import DEFAULT_SIZES
from pokerlab.plo.cards import (
    CardConflictError, all_hands, format_cards, parse_cards,
)
from pokerlab.plo.evaluator import plo_rank_batch, plo_rank_reference
from pokerlab.plo.subgame.showdown import DenseShowdown, InclusionExclusionShowdown, win_matrix
from pokerlab.plo.subgame.tree import BettingConfig, BettingTree, RootState

DENSE_LIMIT = 4_000_000  # n0 * n1 above this uses inclusion-exclusion by default


@dataclass
class SubgameInstance:
    name: str
    tree: BettingTree
    labels: tuple[tuple[str, ...], tuple[str, ...]]
    weights: tuple[np.ndarray, np.ndarray]
    showdown: DenseShowdown | InclusionExclusionShowdown
    pair_outcome: Callable[[int, int], tuple[bool, float]]  # independent scalar oracle
    big_blind: int
    description: dict
    fingerprint: str
    hands: tuple[np.ndarray, np.ndarray] | None = None
    _index: list[dict] = field(default_factory=list, repr=False)

    @property
    def pot(self) -> int:
        return self.tree.config.pot

    def size(self, player: int) -> int:
        return len(self.weights[player])

    def hand_index(self, player: int, hand: str | Sequence[int]) -> int:
        if not self._index:
            self._index = [dict() for _ in range(2)]
            for p in range(2):
                for i, label in enumerate(self.labels[p]):
                    self._index[p][self._key(label)] = i
        key = self._key(hand)
        if key not in self._index[player]:
            raise KeyError(f"hand {hand!r} is not in player {player}'s range")
        return self._index[player][key]

    def _key(self, hand: str | Sequence[int]):
        if isinstance(hand, str):
            if self.hands is None:
                return hand
            hand = parse_cards(hand)
        return tuple(sorted(int(c) for c in hand))


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _chips(spec: dict, key: str, big_blind: int) -> int | list[int]:
    if key in spec:
        return spec[key]
    if f"{key}_bb" in spec:
        value = spec[f"{key}_bb"]
        if isinstance(value, list):
            return [int(round(v * big_blind)) for v in value]
        return int(round(value * big_blind))
    raise KeyError(f"missing {key!r} (chips) or {key + '_bb'!r}")


def build_range(spec: dict, board: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    """Range from ``{"hands": [...], "weights": [...]}``, ``{"sample": k, "seed": s}`` or ``{"all": true}``."""
    board_set = set(board)
    if "hands" in spec:
        hands = [tuple(sorted(parse_cards(h))) for h in spec["hands"]]
        if any(len(h) != 4 for h in hands):
            raise ValueError("PLO4 range hands need exactly 4 cards")
        if any(board_set & set(h) for h in hands):
            raise CardConflictError("a range hand uses a board card")
        if len(set(hands)) != len(hands):
            raise ValueError("duplicate hand in range")
        weights = np.asarray(spec.get("weights", [1.0] * len(hands)), dtype=np.float64)
        arr = np.array(hands, dtype=np.int16).reshape(-1, 4)
    elif spec.get("all"):
        arr = all_hands(4, board)
        weights = np.ones(len(arr))
    elif "sample" in spec:
        pool = all_hands(4, board)
        k = int(spec["sample"])
        if not 0 < k <= len(pool):
            raise ValueError(f"sample size must be in 1..{len(pool)}")
        rng = np.random.default_rng(int(spec.get("seed", 0)))
        arr = pool[np.sort(rng.choice(len(pool), size=k, replace=False))]
        weights = np.ones(k)
    else:
        raise ValueError("range needs 'hands', 'sample' or 'all'")
    if weights.shape != (len(arr),) or not np.all(np.isfinite(weights)) or (weights < 0).any():
        raise ValueError("weights must be finite, non-negative and one per hand")
    if weights.sum() <= 0:
        raise ValueError("range has zero total weight")
    return arr, weights


def betting_config(spec: dict, pot: int, stacks: tuple[int, int], big_blind: int) -> BettingConfig:
    """Betting abstraction from a spec; defaults are the four exact sizes 1/3, 1/2, 2/3, 1 pot.

    ``include_all_in`` is accepted as the older name of ``include_max_raise``.
    """
    return BettingConfig(
        pot=pot, stacks=stacks,
        bet_sizes=tuple(spec.get("bet_sizes", DEFAULT_SIZES)),
        raise_sizes=tuple(spec.get("raise_sizes", DEFAULT_SIZES)),
        include_min_raise=bool(spec.get("include_min_raise", True)),
        include_max_raise=bool(spec.get("include_max_raise", spec.get("include_all_in", True))),
        max_raises=int(spec.get("max_raises", 2)),
        min_bet=int(spec.get("min_bet", big_blind)))


def plo_river_instance(spec: dict) -> SubgameInstance:
    """Build a heads-up PLO4 river subgame from a JSON-style spec (amounts in chips or *_bb)."""
    board = parse_cards(spec["board"])
    if len(board) != 5:
        raise ValueError("river subgame needs a 5-card board")
    bb = int(spec.get("big_blind", 100))
    pot = int(_chips(spec, "pot", bb))
    stacks = _chips(spec, "stacks", bb)
    betting = betting_config(spec, pot, (int(stacks[0]), int(stacks[1])), bb)
    tree = BettingTree(betting, RootState(**spec["root"]) if "root" in spec else RootState())
    if len(spec["ranges"]) != 2:
        raise ValueError("need two ranges: [OOP, IP]")
    (h0, w0), (h1, w1) = (build_range(r, board) for r in spec["ranges"])
    s0, s1 = plo_rank_batch(h0, board), plo_rank_batch(h1, board)
    kind = spec.get("showdown", "auto")
    if kind == "auto":
        kind = "dense" if len(h0) * len(h1) <= DENSE_LIMIT else "inclusion_exclusion"
    if kind == "dense":
        showdown = DenseShowdown.from_hands(h0, s0, h1, s1)
    elif kind == "inclusion_exclusion":
        showdown = InclusionExclusionShowdown(h0, s0, h1, s1)
    else:
        raise ValueError(f"unknown showdown kind {kind!r}")

    labels = (tuple(format_cards(h) for h in h0), tuple(format_cards(h) for h in h1))
    tuples = ([tuple(int(c) for c in h) for h in h0], [tuple(int(c) for c in h) for h in h1])
    rank_cache: dict[tuple, int] = {}

    def reference_rank(hand: tuple) -> int:
        if hand not in rank_cache:
            rank_cache[hand] = plo_rank_reference(hand, board)
        return rank_cache[hand]

    def pair_outcome(i: int, j: int) -> tuple[bool, float]:
        a, b = tuples[0][i], tuples[1][j]
        if set(a) & set(b):
            return False, 0.0
        ra, rb = reference_rank(a), reference_rank(b)
        return True, 1.0 if ra > rb else (0.5 if ra == rb else 0.0)

    description = {
        "kind": "plo4-river", "board": format_cards(board), "big_blind": bb,
        "betting": betting.describe(), "tree": tree.summary(), "showdown": kind,
        "range_sizes": [len(h0), len(h1)],
        "range_specs": [{k: v for k, v in r.items() if k not in ("hands", "weights")} | (
            {"explicit_hands": len(r["hands"])} if "hands" in r else {}) for r in spec["ranges"]],
        "abstraction": ("exact cards and hands (no card abstraction); discrete pot-limit bet sizes; "
                        "ranges are given inputs, not derived from a blueprint"),
    }
    fp = fingerprint({"description": description, "labels": labels,
                      "weights": [w0.tolist(), w1.tolist()]})
    return SubgameInstance(
        name=spec.get("name", "plo4-river"), tree=tree, labels=labels, weights=(w0, w1),
        showdown=showdown, pair_outcome=pair_outcome, big_blind=bb, description=description,
        fingerprint=fp, hands=(h0, h1))


KUHN_VALUE_P0 = 17.0 / 18.0  # constant-sum convention: antes are the sunk pot of 2


def kuhn_instance() -> SubgameInstance:
    """Kuhn poker expressed as a one-street subgame (algorithm sanity check only).

    Each player antes 1 (pot 2) and holds one of J/Q/K; one bet of 1, no raises.
    Player 0's equilibrium value is -1/18 in zero-sum terms, i.e. 17/18 here.
    """
    tree = BettingTree(BettingConfig(pot=2, stacks=(1, 1), bet_sizes=("1/2",), raise_sizes=("1",),
                                     include_min_raise=False, max_raises=0, min_bet=1))
    ranks = np.arange(3)
    compat = ~np.eye(3, dtype=bool)
    showdown = DenseShowdown(compat, win_matrix(ranks, ranks))
    labels = (("J", "Q", "K"), ("J", "Q", "K"))
    weights = (np.ones(3), np.ones(3))

    def pair_outcome(i: int, j: int) -> tuple[bool, float]:
        return (i != j), (1.0 if i > j else 0.0)

    description = {"kind": "kuhn", "betting": tree.config.describe(), "tree": tree.summary()}
    return SubgameInstance("kuhn", tree, labels, weights, showdown, pair_outcome, 1, description,
                           fingerprint({"description": description}))


def dense_from_outcomes(instance: SubgameInstance) -> DenseShowdown:
    """Rebuild a dense showdown from the scalar oracle (independent of the vectorised evaluator)."""
    n0, n1 = instance.size(0), instance.size(1)
    compat = np.zeros((n0, n1), dtype=bool)
    win = np.zeros((n0, n1))
    for i in range(n0):
        for j in range(n1):
            compat[i, j], win[i, j] = instance.pair_outcome(i, j)
    return DenseShowdown(compat, win)
