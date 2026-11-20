"""Joint turn + river solving for heads-up PLO4 (one chance node: the river card).

Game: a fixed 4-card turn board, explicit weighted ranges, a pot and stacks, and the same
exact pot-fraction abstraction on both streets.  The turn betting tree is a ``BettingTree``;
every turn leaf where both players are still in (check-check or a call) becomes a chance
node over all river cards that are not on the board, followed by a river betting tree built
for that leaf's pot and remaining stack (or a direct showdown when someone is all-in).

Chance: a hand holding the river card c cannot reach any node below c.  Every disjoint pair
of hands leaves exactly 52 - 4 - 8 = 40 possible river cards, so the deal probability is 1/40
per valid card and the pair distribution itself is unchanged by the river.

River trees have the same structure for every river card, so river nodes keep arrays of shape
(cards, hands, actions) and every operation is batched across cards.  Turn and river strategies
are optimised together by one CFR loop; nothing is solved separately and spliced.

Showdown and fold masses come from a backend: per-card dense matrices (small instances, the
reference) or inclusion-exclusion card removal per river card (memory linear in the ranges).
The backend is a computation choice, not part of the game, so it is not in the fingerprint.

Utilities are measured from the start of the turn with the starting pot sunk: u0 + u1 = pot.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import scipy.sparse as sp

from pokerlab.plo.cards import DECK, format_cards, parse_cards
from pokerlab.plo.evaluator import plo_rank_batch, plo_rank_reference
from pokerlab.plo.subgame.cfr import SolverConfig, regret_matching, terminal_values
from pokerlab.plo.subgame.instance import betting_config, build_range, _chips
from pokerlab.plo.subgame.showdown import _SIGNS, _Side, hand_masks, subset_keys, win_matrix
from pokerlab.plo.subgame.tree import DECISION, FOLD, SHOWDOWN, BettingConfig, BettingTree, RootState

CHECKPOINT_SCHEMA = "pokerlab.plo.turn-checkpoint/1"
DENSE_TURN_LIMIT = 250_000        # n0 * n1 above which "auto" picks inclusion-exclusion


class CheckpointMismatch(ValueError):
    pass


@dataclass
class RiverLeaf:
    turn_node: int
    commit: int                       # chips each player put in on the turn
    tree: BettingTree | None          # None: someone is all-in, straight to showdown


@dataclass
class TurnRiverGame:
    name: str
    board: tuple[int, ...]
    big_blind: int
    pot: int
    effective_stack: int
    hands: tuple[np.ndarray, np.ndarray]
    weights: tuple[np.ndarray, np.ndarray]
    labels: tuple[tuple[str, ...], tuple[str, ...]]
    turn_tree: BettingTree
    leaves: dict[int, RiverLeaf]
    river_cards: np.ndarray
    masks: tuple[np.ndarray, np.ndarray]          # (cards, n_p): hand does not hold the card
    ranks: tuple[np.ndarray, np.ndarray]          # (cards, n_p): river rank key, -1 if the hand holds the card
    showdown: "DenseTurnShowdown | InclusionExclusionTurnShowdown"
    description: dict
    fingerprint: str
    valid_cards_per_pair: int = 40

    def size(self, player: int) -> int:
        return len(self.weights[player])

    def card_index(self, card: int) -> int:
        return int(np.flatnonzero(self.river_cards == card)[0])

    def pair_outcome(self, i: int, j: int, card: int) -> tuple[bool, float]:
        """Scalar oracle (reference solvers only): compatibility and player 0's share."""
        a, b = tuple(int(c) for c in self.hands[0][i]), tuple(int(c) for c in self.hands[1][j])
        if set(a) & set(b) or card in a or card in b:
            return False, 0.0
        ra, rb = self._reference_rank(a, card), self._reference_rank(b, card)
        return True, 1.0 if ra > rb else (0.5 if ra == rb else 0.0)

    def _reference_rank(self, hand: tuple, card: int) -> int:
        cache = self.__dict__.setdefault("_rank_cache", {})
        if (hand, card) not in cache:
            cache[(hand, card)] = plo_rank_reference(hand, self.board + (card,))
        return cache[(hand, card)]

    def nodes_summary(self) -> dict:
        river = [leaf.tree.summary() for leaf in self.leaves.values() if leaf.tree is not None]
        river_decision = sum(r["decision"] for r in river)
        return {"turn_tree": self.turn_tree.summary(), "turn_leaves": len(self.leaves),
                "all_in_leaves": sum(leaf.tree is None for leaf in self.leaves.values()),
                "river_trees": len(river), "river_cards": int(len(self.river_cards)),
                "river_decision_nodes_per_card": river_decision,
                "river_decision_nodes_total": river_decision * int(len(self.river_cards)),
                "river_nodes_total": sum(r["nodes"] for r in river) * int(len(self.river_cards))}


def turn_river_game(spec: dict) -> TurnRiverGame:
    board = parse_cards(spec["board"])
    if len(board) != 4:
        raise ValueError("turn subgame needs a 4-card board")
    if spec.get("river_cards", "all") != "all":
        raise ValueError("only river_cards='all' (full enumeration) is implemented")
    bb = int(spec.get("big_blind", 100))
    pot = int(_chips(spec, "pot", bb))
    stacks = _chips(spec, "stacks", bb)
    effective = int(min(stacks))
    turn_spec = dict(spec, max_raises=int(spec.get("turn_max_raises", spec.get("max_raises", 1))))
    river_raises = int(spec.get("river_max_raises", spec.get("max_raises", 1)))
    turn_tree = BettingTree(betting_config(turn_spec, pot, (effective, effective), bb),
                            RootState(**spec["root"]) if "root" in spec else RootState())
    leaves: dict[int, RiverLeaf] = {}
    river_trees: dict[tuple[int, int], BettingTree] = {}
    for node in turn_tree.nodes:
        if node.kind != SHOWDOWN:
            continue
        commit = node.commit[0]
        remaining = effective - commit
        tree = None
        if remaining > 0:
            key = (pot + 2 * commit, remaining)
            if key not in river_trees:
                river_trees[key] = BettingTree(betting_config(
                    dict(spec, max_raises=river_raises), key[0], (remaining, remaining), bb))
            tree = river_trees[key]
        leaves[node.id] = RiverLeaf(node.id, commit, tree)

    (h0, w0), (h1, w1) = (build_range(r, board) for r in spec["ranges"])
    kind = spec.get("showdown", "auto")
    if kind == "auto":
        kind = "dense" if len(h0) * len(h1) <= DENSE_TURN_LIMIT else "inclusion_exclusion"
    if kind == "dense" and len(h0) * len(h1) > DENSE_TURN_LIMIT:
        raise ValueError(f"ranges too large for the dense per-card showdown (n0*n1 <= {DENSE_TURN_LIMIT}); "
                         "use showdown 'inclusion_exclusion'")
    if kind not in ("dense", "inclusion_exclusion"):
        raise ValueError(f"unknown showdown {kind!r}")
    cards = np.array([c for c in DECK if c not in board])
    masks = (np.stack([~(h0 == c).any(axis=1) for c in cards]).astype(np.float64),
             np.stack([~(h1 == c).any(axis=1) for c in cards]).astype(np.float64))
    ranks = (np.full((len(cards), len(h0)), -1, dtype=np.int64), np.full((len(cards), len(h1)), -1, dtype=np.int64))
    for k, c in enumerate(cards):
        river_board = board + (int(c),)
        for p, h in enumerate((h0, h1)):
            live = masks[p][k] > 0
            ranks[p][k, live] = plo_rank_batch(h[live], river_board)
    if kind == "dense":
        compat = ((hand_masks(h0)[:, None] & hand_masks(h1)[None, :]) == 0).astype(np.float64)
        compat_k = compat[None, :, :] * masks[0][:, :, None] * masks[1][:, None, :]
        win0_k = np.empty_like(compat_k)
        for k in range(len(cards)):
            win0_k[k] = win_matrix(ranks[0][k], ranks[1][k]) * compat_k[k]
        showdown = DenseTurnShowdown(compat, compat_k, win0_k)
    else:
        showdown = InclusionExclusionTurnShowdown((h0, h1), ranks, masks)

    labels = (tuple(format_cards(h) for h in h0), tuple(format_cards(h) for h in h1))
    description = {
        "kind": "plo4-turn-river", "board": format_cards(board), "big_blind": bb, "pot": pot,
        "stacks": [int(s) for s in stacks], "effective_stack": effective,
        "abstraction": betting_config(spec, pot, (effective, effective), bb).describe(),
        "turn_max_raises": turn_tree.config.max_raises, "river_max_raises": river_raises,
        "range_sizes": [len(h0), len(h1)],
        "range_specs": [{k: v for k, v in r.items() if k not in ("hands", "weights")} | (
            {"explicit_hands": len(r["hands"])} if "hands" in r else {}) for r in spec["ranges"]],
        "river_cards": "all 48 cards not on the turn board, enumerated (no sampling)",
        "chance": "uniform over the 40 river cards not held by either player (1/40 per valid card)",
        "abstraction_note": "exact cards and hands; discrete pot-limit sizes on both streets; ranges are inputs",
    }
    if "root" in spec:
        description["turn_root"] = dict(spec["root"])
    payload = {"description": description, "labels": labels, "weights": [w0.tolist(), w1.tolist()]}
    fp = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    # Neither tree uses the base config's max_raises; report the caps by street.  Done after hashing
    # so that fingerprints (and checkpoints) of earlier runs stay valid.
    description["abstraction"] = dict(description["abstraction"],
                                      max_raises={"turn": turn_tree.config.max_raises, "river": river_raises})
    description["showdown"] = showdown.kind               # computation choice: after hashing
    game = TurnRiverGame(spec.get("name", "plo4-turn-river"), board, bb, pot, effective, (h0, h1),
                         (w0, w1), labels, turn_tree, leaves, cards, masks, ranks, showdown,
                         description, fp)
    game.description["nodes"] = game.nodes_summary()
    return game


# ------------------------------------------------------------------ showdown backends
class DenseTurnShowdown:
    """Per-card dense matrices: compat and player 0's share for every (card, hand0, hand1)."""
    kind = "dense"

    def __init__(self, compat: np.ndarray, compat_k: np.ndarray, win0_k: np.ndarray) -> None:
        self.workers = 1
        self.compat, self.compat_t = compat, compat.T.copy()
        self.compat_k, self.win0_k = compat_k, win0_k
        self.compat_kt = np.ascontiguousarray(compat_k.transpose(0, 2, 1))
        self.win1t_k = np.ascontiguousarray((compat_k - win0_k).transpose(0, 2, 1))

    def turn_masses(self, p: int, reach_o: np.ndarray) -> np.ndarray:
        return (self.compat if p == 0 else self.compat_t) @ reach_o

    def river_masses(self, p: int, ro: np.ndarray, need_win: bool):
        compat = self.compat_k if p == 0 else self.compat_kt
        c = np.matmul(compat, ro[:, :, None])[:, :, 0]
        if not need_win:
            return c, None
        win = self.win0_k if p == 0 else self.win1t_k
        return c, np.matmul(win, ro[:, :, None])[:, :, 0]

    def set_workers(self, workers: int) -> None:
        """Dense products already run on the BLAS thread pool; nothing is split here."""
        self.workers = 1

    def memory(self) -> dict:
        return {"showdown_structures": sum(a.nbytes for a in (self.compat, self.compat_t, self.compat_k,
                                                               self.win0_k, self.compat_kt, self.win1t_k))}


class _SparseCompat:
    """Compatible opponent mass by inclusion-exclusion, as two sparse products.

    ``compat(i) = sum_j r_j + sum_{S subset of hand i} (-1)^|S| sum_{j contains S} r_j``.  E maps
    opponent hands to the card subsets they contain, Q maps own hands to theirs with the signs, so
    ``compat = total + (r @ E) @ Q^T``.  Nothing depends on the river card: dead hands have zero
    opponent reach and their own masses are zeroed by the caller.
    """

    def __init__(self, h_me: np.ndarray, h_opp: np.ndarray) -> None:
        ko, km = subset_keys(h_opp), subset_keys(h_me)
        keys, column = np.unique(ko.ravel(), return_inverse=True)
        self.E = sp.csr_matrix((np.ones(ko.size), (np.repeat(np.arange(len(h_opp)), ko.shape[1]), column)),
                               shape=(len(h_opp), len(keys)))
        pos = np.minimum(np.searchsorted(keys, km.ravel()), len(keys) - 1)
        present = keys[pos] == km.ravel()
        rows = np.repeat(np.arange(len(h_me)), km.shape[1])[present]
        self.QT = sp.csr_matrix((np.tile(_SIGNS, len(h_me))[present], (pos[present], rows)),
                                shape=(len(keys), len(h_me)))

    def __call__(self, reach_o: np.ndarray) -> np.ndarray:
        total = reach_o.sum(axis=-1, keepdims=reach_o.ndim > 1)
        return total + (reach_o @ self.E) @ self.QT

    def nbytes(self) -> int:
        return sum(m.data.nbytes + m.indices.nbytes + m.indptr.nbytes for m in (self.E, self.QT))


class _WinIndex:
    """Strength-ordered inclusion-exclusion for one querying player over all river cards.

    Row k is ``showdown._Side`` built on river card k with every hand kept (hands holding the card
    have rank -1 and zero reach), stored as flat indices into the row-stacked work arrays so that
    any block of rows can be computed on its own.
    """

    def __init__(self, h_me, s_me_k, h_opp, s_opp_k) -> None:
        k_cards, n_me, n_opp = len(s_me_k), len(h_me), len(h_opp)
        self.n_me, self.n_opp, self.width = n_me, n_opp, 15 * n_opp + 1
        self.events = np.empty((k_cards, 15 * n_opp), dtype=np.int64)
        self.order = np.empty((k_cards, n_opp), dtype=np.int64)
        self.queries = np.empty((k_cards, 3, n_me, 15), dtype=np.int64)
        self.t_less = np.empty((k_cards, n_me), dtype=np.int64)
        self.t_leq = np.empty((k_cards, n_me), dtype=np.int64)
        for k in range(k_cards):
            side = _Side(h_me, s_me_k[k], h_opp, s_opp_k[k])
            self.events[k] = k * n_opp + side.event_src
            self.order[k] = k * n_opp + side.order
            for j, q in enumerate((side.q_start, side.q_less, side.q_leq)):
                self.queries[k, j] = k * self.width + q
            self.t_less[k] = k * (n_opp + 1) + side.t_less
            self.t_leq[k] = k * (n_opp + 1) + side.t_leq
        self.queries = self.queries.reshape(k_cards, -1)

    def rows(self, ro_flat, cumulative, prefix, out, a: int, b: int) -> None:
        """Win masses of rows a..b into ``out``; rows are independent, so any split gives the same bits."""
        np.cumsum(ro_flat[self.events[a:b]], axis=1, out=cumulative[a:b, 1:])
        np.cumsum(ro_flat[self.order[a:b]], axis=1, out=prefix[a:b, 1:])
        g = (cumulative.ravel()[self.queries[a:b]].reshape(b - a, 3, self.n_me, 15) * _SIGNS).sum(axis=3)
        flat = prefix.ravel()
        out[a:b] = 0.5 * ((flat[self.t_less[a:b]] + g[:, 1] - g[:, 0]) + (flat[self.t_leq[a:b]] + g[:, 2] - g[:, 0]))

    def nbytes(self) -> int:
        return sum(a.nbytes for a in (self.events, self.order, self.queries, self.t_less, self.t_leq))


class InclusionExclusionTurnShowdown:
    """Card removal by inclusion-exclusion over the 15 subsets of each 4-card hand, per river card.

    Memory is linear in the range sizes (no n0 x n1 matrix); the dense backend stays as the
    reference for small instances.  ``set_workers(w)`` splits the river cards into w row blocks
    computed by a thread pool; every block runs the same per-row operations, so results do not
    depend on w.
    """
    kind = "inclusion_exclusion"

    def __init__(self, hands, ranks_k, masks) -> None:
        h0, h1 = hands
        self.masks = masks
        self.compat = (_SparseCompat(h0, h1), _SparseCompat(h1, h0))
        self.win = (_WinIndex(h0, ranks_k[0], h1, ranks_k[1]), _WinIndex(h1, ranks_k[1], h0, ranks_k[0]))
        self.workers, self._pool, self._blocks = 1, None, [(0, len(masks[0]))]

    def set_workers(self, workers: int) -> None:
        workers = max(1, int(workers))
        if self._pool is not None:
            self._pool.shutdown()
        self.workers = workers
        self._pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
        bounds = np.linspace(0, len(self.masks[0]), workers + 1).round().astype(int)
        self._blocks = [(int(a), int(b)) for a, b in zip(bounds[:-1], bounds[1:]) if b > a]

    def turn_masses(self, p: int, reach_o: np.ndarray) -> np.ndarray:
        return self.compat[p](reach_o)

    def river_masses(self, p: int, ro: np.ndarray, need_win: bool):
        mine = self.masks[p]
        compat = self.compat[p](ro) * mine
        if not need_win:
            return compat, None
        index = self.win[p]
        cards = ro.shape[0]
        ro_flat = np.ascontiguousarray(ro).ravel()
        cumulative = np.empty((cards, index.width))
        cumulative[:, 0] = 0.0
        prefix = np.empty((cards, index.n_opp + 1))
        prefix[:, 0] = 0.0
        win = np.empty((cards, index.n_me))
        if self._pool is None:
            index.rows(ro_flat, cumulative, prefix, win, 0, cards)
        else:
            list(self._pool.map(lambda ab: index.rows(ro_flat, cumulative, prefix, win, *ab), self._blocks))
        return compat, win * mine

    def memory(self) -> dict:
        return {"showdown_structures": sum(c.nbytes() for c in self.compat) + sum(w.nbytes() for w in self.win)}


# ------------------------------------------------------------------- traversal
class TurnRiverSolver:
    """Joint CFR over turn and river.  ``frozen_river`` fixes river strategies (diagnostics only)."""

    def __init__(self, game: TurnRiverGame, config: SolverConfig = SolverConfig(),
                 frozen_river: dict | None = None, workers: int | None = None) -> None:
        if config.algorithm == "es-mccfr":
            raise ValueError("turn solver supports cfr, cfr+, lcfr and dcfr")
        self.g = game
        self.config = config
        self.frozen_river = frozen_river
        self.ev = game.showdown
        if workers is not None:                       # threads over river-card blocks; results do not depend on it
            self.ev.set_workers(workers)
        self.workers = self.ev.workers
        self.iteration = 0
        self.elapsed = 0.0
        self.turn_regret: dict[int, np.ndarray] = {}
        self.turn_strategy: dict[int, np.ndarray] = {}
        self.river_regret: dict[tuple[int, int], np.ndarray] = {}
        self.river_strategy: dict[tuple[int, int], np.ndarray] = {}
        cards = len(game.river_cards)
        for nid in game.turn_tree.decision_nodes():
            node = game.turn_tree.nodes[nid]
            shape = (self._turn_rows(node.player), len(node.children))
            self.turn_regret[nid] = np.zeros(shape)
            self.turn_strategy[nid] = np.zeros(shape)
        for leaf in game.leaves.values():
            if leaf.tree is None:
                continue
            for rid in leaf.tree.decision_nodes():
                node = leaf.tree.nodes[rid]
                shape = (cards, self._river_rows(node.player), len(node.children))
                self.river_regret[(leaf.turn_node, rid)] = np.zeros(shape)
                self.river_strategy[(leaf.turn_node, rid)] = np.zeros(shape)

    # ------------------------------------------------------------ training
    def run(self, iterations: int, callback: Callable | None = None,
            should_stop: Callable | None = None) -> None:
        """Run up to ``iterations`` iterations; ``should_stop(solver)`` is checked after each one."""
        for _ in range(int(iterations)):
            start = time.perf_counter()
            t = self.iteration + 1
            for p in (0, 1):
                self._turn(self.g.turn_tree.root, p, self.g.weights[p], self.g.weights[1 - p], t)
            if self.config.algorithm == "dcfr":
                self._discount(t)
            self.iteration = t
            self.elapsed += time.perf_counter() - start
            if callback is not None:
                callback(self)
            if should_stop is not None and should_stop(self):
                break

    # Array rows, strategy and update hooks (overridden by abstraction solvers; one row per hand here).
    def _turn_rows(self, player: int) -> int:
        return self.g.size(player)

    def _river_rows(self, player: int) -> int:
        return self.g.size(player)

    def _turn_sigma(self, nid: int) -> np.ndarray:
        return regret_matching(self.turn_regret[nid])

    def _river_sigma(self, key: tuple[int, int]) -> np.ndarray:
        return regret_matching(self.river_regret[key])

    def _turn_update(self, nid: int, inst_regret, contribution, t) -> None:
        self._update(self.turn_regret[nid], self.turn_strategy[nid], inst_regret, contribution, t)

    def _river_update(self, key: tuple[int, int], inst_regret, contribution, t) -> None:
        self._update(self.river_regret[key], self.river_strategy[key], inst_regret, contribution, t)

    def _update(self, regret, strategy, inst_regret, contribution, t) -> None:
        a = self.config.algorithm
        if a == "cfr+":
            regret += inst_regret
            np.maximum(regret, 0.0, out=regret)
            strategy += t * contribution
        elif a == "lcfr":
            regret += t * inst_regret
            strategy += t * contribution
        else:
            regret += inst_regret
            strategy += contribution

    def _discount(self, t: int) -> None:
        c = self.config
        positive = t ** c.alpha / (t ** c.alpha + 1.0)
        negative = t ** c.beta / (t ** c.beta + 1.0)
        keep = (t / (t + 1.0)) ** c.gamma
        for regrets, strategies in ((self.turn_regret, self.turn_strategy),
                                    (self.river_regret, self.river_strategy)):
            for key, regret in regrets.items():
                regret *= np.where(regret > 0.0, positive, negative)
                strategies[key] *= keep

    def _turn(self, nid: int, p: int, reach_p: np.ndarray, reach_o: np.ndarray, t: int) -> np.ndarray:
        g = self.g
        node = g.turn_tree.nodes[nid]
        if node.kind == FOLD:
            return terminal_values(node, p, g.pot, self.ev.turn_masses(p, reach_o), None)
        if node.kind == SHOWDOWN:
            return self._chance(g.leaves[nid], p, reach_p, reach_o, t)
        sigma = self._turn_sigma(nid)
        if node.player == p:
            values = np.empty((len(reach_p), len(node.children)))
            for a, child in enumerate(node.children):
                values[:, a] = self._turn(child, p, reach_p * sigma[:, a], reach_o, t)
            ev = np.einsum("ia,ia->i", values, sigma)
            self._turn_update(nid, values - ev[:, None], reach_p[:, None] * sigma, t)
            return ev
        total = np.zeros(len(reach_p))
        for a, child in enumerate(node.children):
            total += self._turn(child, p, reach_p, reach_o * sigma[:, a], t)
        return total

    def _chance(self, leaf: RiverLeaf, p: int, reach_p, reach_o, t) -> np.ndarray:
        g = self.g
        mp, mo = g.masks[p], g.masks[1 - p]
        rp, ro = reach_p[None, :] * mp, reach_o[None, :] * mo
        if leaf.tree is None:
            compat, win = self.ev.river_masses(p, ro, True)
            values = (g.pot + 2 * leaf.commit) * win - leaf.commit * compat
        else:
            values = self._river(leaf, leaf.tree.root, p, rp, ro, t)
        return (values * mp).sum(axis=0) / g.valid_cards_per_pair

    def _river(self, leaf: RiverLeaf, rid: int, p: int, rp, ro, t) -> np.ndarray:
        node = leaf.tree.nodes[rid]
        if node.kind != DECISION:
            compat, win = self.ev.river_masses(p, ro, node.kind == SHOWDOWN)
            return terminal_values(node, p, leaf.tree.config.pot, compat, win) - leaf.commit * compat
        key = (leaf.turn_node, rid)
        frozen = self.frozen_river is not None
        sigma = self.frozen_river[key] if frozen else self._river_sigma(key)
        if node.player == p:
            values = np.empty(sigma.shape)
            for a, child in enumerate(node.children):
                values[:, :, a] = self._river(leaf, child, p, rp * sigma[:, :, a], ro, t)
            ev = np.einsum("kia,kia->ki", values, sigma)
            if not frozen:
                self._river_update(key, values - ev[:, :, None], rp[:, :, None] * sigma, t)
            return ev
        total = np.zeros(rp.shape)
        for a, child in enumerate(node.children):
            total += self._river(leaf, child, p, rp, ro * sigma[:, :, a], t)
        return total

    def solve_rivers_with_prior_ranges(self, iterations: int) -> dict:
        """The "spliced" shortcut, for comparison only: every river subgame is solved on its own
        with the turn-start ranges (masked by the river card), ignoring what the turn line says
        about the ranges.  Returns the river average strategies."""
        g = self.g
        for leaf in g.leaves.values():
            if leaf.tree is None:
                continue
            prior = [g.weights[p][None, :] * g.masks[p] for p in (0, 1)]
            for t in range(1, int(iterations) + 1):
                for p in (0, 1):
                    self._river(leaf, leaf.tree.root, p, prior[p], prior[1 - p], t)
                if self.config.algorithm == "dcfr":
                    c = self.config
                    positive = t ** c.alpha / (t ** c.alpha + 1.0)
                    negative = t ** c.beta / (t ** c.beta + 1.0)
                    keep = (t / (t + 1.0)) ** c.gamma
                    for rid in leaf.tree.decision_nodes():
                        regret = self.river_regret[(leaf.turn_node, rid)]
                        regret *= np.where(regret > 0.0, positive, negative)
                        self.river_strategy[(leaf.turn_node, rid)] *= keep
        return {k: self._normalise(v) for k, v in self.river_strategy.items()}

    # ---------------------------------------------------------- strategies
    @staticmethod
    def _normalise(s: np.ndarray) -> np.ndarray:
        total = s.sum(axis=-1, keepdims=True)
        return np.where(total > 0.0, s / np.where(total > 0.0, total, 1.0), 1.0 / s.shape[-1])

    def average_profile(self) -> dict:
        return {"turn": {k: self._normalise(v) for k, v in self.turn_strategy.items()},
                "river": {k: self._normalise(v) for k, v in self.river_strategy.items()}}

    def current_profile(self) -> dict:
        return {"turn": {k: regret_matching(v) for k, v in self.turn_regret.items()},
                "river": {k: regret_matching(v) for k, v in self.river_regret.items()}}

    def memory(self) -> dict:
        """Bytes held by this process, by category (temporaries are not counted here)."""
        g = self.g
        turn = sum(a.nbytes for d in (self.turn_regret, self.turn_strategy) for a in d.values())
        river = sum(a.nbytes for d in (self.river_regret, self.river_strategy) for a in d.values())
        return {"regret_and_average_strategy_turn": turn, "regret_and_average_strategy_river": river,
                **g.showdown.memory(),
                "masks_ranks_ranges": sum(a.nbytes for a in (*g.masks, *g.ranks, *g.hands, *g.weights))}

    def memory_bytes(self) -> int:
        return sum(self.memory().values())

    # ---------------------------------------------------------- checkpoint
    def save_checkpoint(self, path: str | os.PathLike) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"schema": CHECKPOINT_SCHEMA, "fingerprint": self.g.fingerprint,
                "config": asdict(self.config), "iteration": self.iteration, "elapsed_s": self.elapsed,
                "turn_nodes": sorted(self.turn_regret),
                "river_nodes": sorted([list(k) for k in self.river_regret])}
        arrays = {"meta": np.array(json.dumps(meta))}
        for nid in self.turn_regret:
            arrays[f"turn_regret_{nid}"] = self.turn_regret[nid]
            arrays[f"turn_strategy_{nid}"] = self.turn_strategy[nid]
        for (leaf, rid) in self.river_regret:
            arrays[f"river_regret_{leaf}_{rid}"] = self.river_regret[(leaf, rid)]
            arrays[f"river_strategy_{leaf}_{rid}"] = self.river_strategy[(leaf, rid)]
        partial = path.with_name(path.name + ".partial")
        with open(partial, "wb") as fh:
            np.savez(fh, **arrays)
        os.replace(partial, path)
        return path

    @classmethod
    def load_checkpoint(cls, path: str | os.PathLike, game: TurnRiverGame,
                        workers: int | None = None) -> "TurnRiverSolver":
        with np.load(Path(path), allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            if meta.get("schema") != CHECKPOINT_SCHEMA:
                raise CheckpointMismatch(f"unknown checkpoint schema {meta.get('schema')!r}")
            if meta["fingerprint"] != game.fingerprint:
                raise CheckpointMismatch("checkpoint belongs to a different turn subgame")
            solver = cls(game, SolverConfig(**meta["config"]), workers=workers)
            for nid in solver.turn_regret:
                solver.turn_regret[nid] = data[f"turn_regret_{nid}"].copy()
                solver.turn_strategy[nid] = data[f"turn_strategy_{nid}"].copy()
            for (leaf, rid) in solver.river_regret:
                solver.river_regret[(leaf, rid)] = data[f"river_regret_{leaf}_{rid}"].copy()
                solver.river_strategy[(leaf, rid)] = data[f"river_strategy_{leaf}_{rid}"].copy()
        solver.iteration = int(meta["iteration"])
        solver.elapsed = float(meta.get("elapsed_s", 0.0))
        return solver


# ------------------------------------------------------------------ evaluation
def _value(g: TurnRiverGame, profile: dict, p: int, best: bool) -> np.ndarray:
    ev = g.showdown

    def turn(nid: int, reach_o: np.ndarray) -> np.ndarray:
        node = g.turn_tree.nodes[nid]
        if node.kind == FOLD:
            return terminal_values(node, p, g.pot, ev.turn_masses(p, reach_o), None)
        if node.kind == SHOWDOWN:
            return chance(g.leaves[nid], reach_o)
        sigma = profile["turn"][nid]
        if node.player == p:
            values = np.stack([turn(c, reach_o) for c in node.children], axis=1)
            return values.max(axis=1) if best else np.einsum("ia,ia->i", values, sigma)
        return sum(turn(c, reach_o * sigma[:, a]) for a, c in enumerate(node.children))

    def chance(leaf: RiverLeaf, reach_o: np.ndarray) -> np.ndarray:
        mp, mo = g.masks[p], g.masks[1 - p]
        ro = reach_o[None, :] * mo
        if leaf.tree is None:
            compat, win = ev.river_masses(p, ro, True)
            values = (g.pot + 2 * leaf.commit) * win - leaf.commit * compat
        else:
            values = river(leaf, leaf.tree.root, ro)
        return (values * mp).sum(axis=0) / g.valid_cards_per_pair

    def river(leaf: RiverLeaf, rid: int, ro: np.ndarray) -> np.ndarray:
        node = leaf.tree.nodes[rid]
        if node.kind != DECISION:
            compat, win = ev.river_masses(p, ro, node.kind == SHOWDOWN)
            return terminal_values(node, p, leaf.tree.config.pot, compat, win) - leaf.commit * compat
        sigma = profile["river"][(leaf.turn_node, rid)]
        if node.player == p:
            values = np.stack([river(leaf, c, ro) for c in node.children], axis=2)
            return values.max(axis=2) if best else np.einsum("kia,kia->ki", values, sigma)
        return sum(river(leaf, c, ro * sigma[:, :, a]) for a, c in enumerate(node.children))

    return turn(g.turn_tree.root, g.weights[1 - p])


def turn_frequencies(game: TurnRiverGame, profile: dict) -> list[dict]:
    """Range-weighted action frequencies (own reach only) at every turn decision node."""
    out = []

    def walk(nid: int, reach: list[np.ndarray]) -> None:
        node = game.turn_tree.nodes[nid]
        if node.kind != DECISION:
            return
        sigma = profile["turn"][nid]
        r = reach[node.player]
        total = r.sum()
        freq = (r @ sigma) / total if total > 0 else np.full(len(node.actions), np.nan)
        out.append({"history": list(node.history), "player": ["OOP", "IP"][node.player],
                    "reach_mass": float(total), "actions": dict(zip(node.actions, map(float, freq)))})
        for a, child in enumerate(node.children):
            new = list(reach)
            new[node.player] = r * sigma[:, a]
            walk(child, new)

    walk(game.turn_tree.root, [game.weights[0].copy(), game.weights[1].copy()])
    return out


def save_average_strategy(game: TurnRiverGame, profile: dict, path: str | os.PathLike) -> Path:
    """All average-strategy arrays plus the labels needed to read them."""
    path = Path(path)
    index = {"hands": [list(game.labels[0]), list(game.labels[1])],
             "river_cards": [format_cards([int(c)]) for c in game.river_cards],
             "turn_nodes": {str(n): {"history": list(game.turn_tree.nodes[n].history),
                                     "player": game.turn_tree.nodes[n].player,
                                     "actions": list(game.turn_tree.nodes[n].actions)}
                            for n in profile["turn"]},
             "river_nodes": {f"{leaf}_{rid}": {
                 "turn_history": list(game.turn_tree.nodes[leaf].history),
                 "river_history": list(game.leaves[leaf].tree.nodes[rid].history),
                 "player": game.leaves[leaf].tree.nodes[rid].player,
                 "actions": list(game.leaves[leaf].tree.nodes[rid].actions)}
                 for (leaf, rid) in profile["river"]},
             "layout": "turn_<node>: (hands, actions); river_<turn leaf>_<node>: (river cards, hands, actions)"}
    arrays = {"index": np.array(json.dumps(index))}
    arrays.update({f"turn_{n}": a for n, a in profile["turn"].items()})
    arrays.update({f"river_{leaf}_{rid}": a for (leaf, rid), a in profile["river"].items()})
    partial = path.with_name(path.name + ".partial")
    with open(partial, "wb") as fh:
        np.savez_compressed(fh, **arrays)
    os.replace(partial, path)
    return path


def evaluate_turn_profile(game: TurnRiverGame, profile: dict) -> dict:
    z = float(game.weights[0] @ game.showdown.turn_masses(0, game.weights[1]))
    value = [float(game.weights[p] @ _value(game, profile, p, False)) / z for p in (0, 1)]
    br = [float(game.weights[p] @ _value(game, profile, p, True)) / z for p in (0, 1)]
    exploitability = (br[0] + br[1] - game.pot) / 2.0
    return {"value": value, "best_response_value": br,
            "value_net_of_equal_sunk_share": [v - game.pot / 2.0 for v in value],
            "nash_conv_chips": br[0] + br[1] - game.pot,
            "exploitability_chips": exploitability,
            "exploitability_bb": exploitability / game.big_blind,
            "exploitability_pct_pot": 100.0 * exploitability / game.pot,
            "constant_sum_check": value[0] + value[1] - game.pot}
