"""Hand abstraction v1 for heads-up PLO4 subgames: information abstraction with exact payoffs.

Only what a player can tell apart is abstracted.  Hands in the same bucket share one regret vector and
one strategy at every node of a street; payoffs, card compatibility, blockers and chance probabilities
stay exact per hand, because the solver still computes per-hand counterfactual values with the real
card removal.  The strategy of any hand is the strategy of its bucket, so the solved profile is a
profile of the original game and is evaluated there with exact best responses.

Features (exact card removal against the opponent's range in the subgame):

River (5-card board)
  eq     showdown equity against the opponent range: win mass / compatible mass;
  b_top  blocker ratio: share of the opponent's strongest ``q_top`` (by weight, ordered by river rank)
         left compatible with the hand, divided by the share of the whole range left compatible
         (< 1: the hand removes strong hands more than average);
  b_bot  the same for the opponent's weakest ``q_bot``.
  bucket = eq (``q_eq`` equal-mass bins over the player's range) x b_top (3) x b_bot (2).
  Showdown rank alone ignores b_top / b_bot: equal-rank hands with different blockers can now differ.

Turn (4-card board, river to come)
  eq_k    per river card k, eq on the river board (hands holding k excluded);
  eq_turn sum_k win_k / sum_k compat_k: equity with the river dealt with its true probabilities;
  spread  weighted standard deviation of eq_k across river cards: how much the value changes with the
          river (draws and vulnerable made hands: large; nuts and air: small);
  b_top   blocker ratio at the turn against the opponent's strongest ``q_top`` by their eq_turn.
  turn bucket = eq_turn (``q_turn`` bins) x spread (3) x b_top (2).
  river bucket under card k = (turn bucket, eq_k bin among hands alive under k, b_top_k bin), numbered
  densely per card.  It refines the turn bucket, so a player always remembers their turn bucket and own
  actions: the abstract game keeps perfect recall, and CFR's convergence (to an equilibrium of the
  abstract game) applies.  Nothing guarantees how exploitable that abstract equilibrium is in the
  original game; that is what the evaluation measures.

Scope: the hands of the subgame's two ranges carry the stored buckets; ``bucket_of_hand`` computes the
same features for any other legal hand (no board conflict) and returns its bucket with the same bin edges.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from pokerlab.plo.cards import parse_cards
from pokerlab.plo.evaluator import plo_rank_batch
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, regret_matching
from pokerlab.plo.subgame.instance import SubgameInstance
from pokerlab.plo.subgame.showdown import hand_masks
from pokerlab.plo.subgame.turn import TurnRiverGame, TurnRiverSolver

Q_TOP, Q_BOT = 0.2, 0.3


# ------------------------------------------------------------------ binning
def weighted_edges(x: np.ndarray, w: np.ndarray, q: int) -> np.ndarray:
    """Interior edges of ``q`` equal-weight bins of ``x`` (weighted quantiles)."""
    keep = np.isfinite(x) & (w > 0)
    xs, ws = x[keep], w[keep]
    order = np.argsort(xs, kind="stable")
    xs, ws = xs[order], ws[order]
    c = np.cumsum(ws)
    c /= c[-1]
    return np.array([xs[min(int(np.searchsorted(c, i / q)), len(xs) - 1)] for i in range(1, q)])


def to_bin(x: np.ndarray, edges: np.ndarray) -> np.ndarray:
    return np.searchsorted(edges, np.nan_to_num(x, nan=-1.0), side="right").astype(np.int64)


def _top_mask(strength: np.ndarray, w: np.ndarray, q: float, top: bool) -> np.ndarray:
    """Hands forming the strongest (or weakest) share ``q`` of the weight."""
    order = np.argsort(-strength if top else strength, kind="stable")
    c = np.cumsum(w[order]) / w.sum()
    mask = np.zeros(len(w), dtype=bool)
    mask[order[: int(np.searchsorted(c, q)) + 1]] = True
    return mask


def _ratio(part: np.ndarray, whole: np.ndarray, w_part: float, w_whole: float) -> np.ndarray:
    return np.where(whole > 0, (part / w_part) / np.maximum(whole / w_whole, 1e-300), 1.0)


@dataclass
class Buckets:
    ids: np.ndarray            # bucket per hand (river abstraction of a turn game: per card, see TurnAbstraction)
    count: int
    mode: str
    edges: dict


# ------------------------------------------------------------------ river
def river_features(inst: SubgameInstance, player: int) -> dict:
    opp = 1 - player
    w_opp = inst.weights[opp]
    board = tuple(parse_cards(inst.description["board"]))
    compat, win = inst.showdown.masses(player, w_opp, True)
    eq = np.where(compat > 0, win / np.maximum(compat, 1e-300), 0.5)
    rank_opp = plo_rank_batch(inst.hands[opp], board).astype(np.float64)
    top, bot = _top_mask(rank_opp, w_opp, Q_TOP, True), _top_mask(rank_opp, w_opp, Q_BOT, False)
    c_top = inst.showdown.masses(player, w_opp * top, False)[0]
    c_bot = inst.showdown.masses(player, w_opp * bot, False)[0]
    W = w_opp.sum()
    return {"eq": eq, "b_top": _ratio(c_top, compat, w_opp[top].sum(), W),
            "b_bot": _ratio(c_bot, compat, w_opp[bot].sum(), W),
            "rank": plo_rank_batch(inst.hands[player], board), "opp_top": top, "opp_bot": bot}


def river_buckets(inst: SubgameInstance, player: int, mode: str = "v1", q_eq: int = 16) -> Buckets:
    """``v1``: eq x b_top x b_bot; ``eq_only``: the same number of equal-mass eq bins; ``rank``: one bucket
    per distinct river rank (the old showdown-rank grouping, no blocker information)."""
    f = river_features(inst, player)
    w = inst.weights[player]
    if mode == "rank":
        _, ids = np.unique(f["rank"], return_inverse=True)
        return Buckets(ids.astype(np.int64), int(ids.max()) + 1, mode, {})
    if mode == "eq_only":
        e = weighted_edges(f["eq"], w, q_eq * 6)
        return Buckets(to_bin(f["eq"], e), q_eq * 6, mode, {"eq": e})
    edges = {"eq": weighted_edges(f["eq"], w, q_eq), "b_top": weighted_edges(f["b_top"], w, 3),
             "b_bot": weighted_edges(f["b_bot"], w, 2)}
    ids = (to_bin(f["eq"], edges["eq"]) * 6 + to_bin(f["b_top"], edges["b_top"]) * 2
           + to_bin(f["b_bot"], edges["b_bot"]))
    return Buckets(ids, q_eq * 6, mode, edges)


def _onehot(ids: np.ndarray, count: int) -> sp.csr_matrix:
    n = len(ids)
    return sp.csr_matrix((np.ones(n), (ids, np.arange(n))), shape=(count, n))


class TiedRiverSolver(CFRSolver):
    """Full-width CFR in which every hand plays its bucket's strategy (regrets summed per bucket)."""

    def __init__(self, instance: SubgameInstance, buckets: tuple[Buckets, Buckets],
                 config: SolverConfig = SolverConfig()) -> None:
        if config.algorithm == "es-mccfr":
            raise ValueError("abstraction solver is full-width only")
        self.buckets = buckets                     # before the base class allocates bucket-sized arrays
        self.M = tuple(_onehot(b.ids, b.count) for b in buckets)
        super().__init__(instance, config)

    def _rows(self, player: int) -> int:
        return self.buckets[player].count

    def _player(self, nid: int) -> int:
        return self.tree.nodes[nid].player

    def _sigma(self, nid: int) -> np.ndarray:
        return regret_matching(self.regret[nid])[self.buckets[self._player(nid)].ids]

    def _update(self, nid: int, inst_regret: np.ndarray, contribution: np.ndarray, t: int) -> None:
        M = self.M[self._player(nid)]
        super()._update(nid, M @ inst_regret, M @ contribution, t)

    def average_strategy(self, nid: int) -> np.ndarray:
        s = self.strategy_sum[nid]
        total = s.sum(axis=1, keepdims=True)
        avg = np.where(total > 0.0, s / np.where(total > 0.0, total, 1.0), 1.0 / s.shape[1])
        return avg[self.buckets[self._player(nid)].ids]

    def current_profile(self) -> dict[int, np.ndarray]:
        return {nid: self._sigma(nid) for nid in self.regret}

    def save_checkpoint(self, path):
        raise NotImplementedError("checkpoints of abstraction solves are not supported yet")


# ------------------------------------------------------------------ turn
def _card_masses(game: TurnRiverGame, player: int, opp_reach_k: np.ndarray, need_win: bool):
    return game.showdown.river_masses(player, opp_reach_k, need_win)


def turn_features(game: TurnRiverGame) -> list[dict]:
    """Per player: eq_turn, spread, eq_k, the turn blocker ratio and per-card blocker ratios."""
    out = []
    for p in (0, 1):
        o = 1 - p
        ro = game.weights[o][None, :] * game.masks[o]
        compat_k, win_k = _card_masses(game, p, ro, True)
        tot = compat_k.sum(axis=0)
        eq_turn = np.where(tot > 0, win_k.sum(axis=0) / np.maximum(tot, 1e-300), 0.5)
        eq_k = np.where(compat_k > 0, win_k / np.maximum(compat_k, 1e-300), np.nan)
        dev = np.where(compat_k > 0, (eq_k - eq_turn[None, :]) ** 2, 0.0)
        spread = np.sqrt(np.where(tot > 0, (compat_k * dev).sum(axis=0) / np.maximum(tot, 1e-300), 0.0))
        out.append({"eq_turn": eq_turn, "spread": spread, "eq_k": eq_k, "compat_k": compat_k})
    for p in (0, 1):
        o = 1 - p
        w_o = game.weights[o]
        top = _top_mask(out[o]["eq_turn"], w_o, Q_TOP, True)
        whole = game.showdown.turn_masses(p, w_o)
        part = game.showdown.turn_masses(p, w_o * top)
        out[p]["b_top"] = _ratio(part, whole, w_o[top].sum(), w_o.sum())
        # per river card: the opponent's strongest q_top among hands alive under that card, by their eq_k
        tops = np.zeros_like(game.masks[o], dtype=bool)
        for k in range(len(game.river_cards)):
            alive = game.masks[o][k] > 0
            strength = np.where(alive, np.nan_to_num(out[o]["eq_k"][k], nan=-1.0), -1.0)
            tops[k] = _top_mask(strength, w_o * alive, Q_TOP, True) & alive
        ro_top = w_o[None, :] * game.masks[o] * tops
        part_k = _card_masses(game, p, ro_top, False)[0]
        w_top_k = (w_o[None, :] * game.masks[o] * tops).sum(axis=1, keepdims=True)
        w_k = (w_o[None, :] * game.masks[o]).sum(axis=1, keepdims=True)
        out[p]["b_top_k"] = np.where(out[p]["compat_k"] > 0, (part_k / np.maximum(w_top_k, 1e-300)) /
                                     np.maximum(out[p]["compat_k"] / w_k, 1e-300), np.nan)
    return out


@dataclass
class TurnAbstraction:
    mode: str
    turn: tuple[Buckets, Buckets]
    river_ids: tuple[np.ndarray, np.ndarray]    # (cards, n_p): dense bucket id per card, refines the turn bucket
    river_width: tuple[int, int]                # max number of river buckets on any card
    river_turn_of: tuple[list, list]            # per card: river bucket -> turn bucket (perfect-recall check)
    edges: dict

    def size(self) -> dict:
        return {"turn_buckets": [b.count for b in self.turn],
                "turn_buckets_used": [int(len(np.unique(b.ids))) for b in self.turn],
                "river_buckets_per_card_max": list(self.river_width),
                "river_buckets_per_card_mean": [float(np.mean([len(m) for m in self.river_turn_of[p]]))
                                                for p in (0, 1)]}


def turn_abstraction(game: TurnRiverGame, mode: str = "v1", q_turn: int = 8, q_river: int = 4) -> TurnAbstraction:
    """``v1``: turn (eq_turn x spread x b_top), river (turn bucket, eq_k bin, b_top_k bin).
    ``eq_only``: the same bucket counts from equity alone (turn: eq_turn; river: turn bucket x eq_k)."""
    feats = turn_features(game)
    turn, river_ids, widths, turn_of, edges = [], [], [], [], {}
    for p in (0, 1):
        f, w = feats[p], game.weights[p]
        if mode == "v1":
            e = {"eq_turn": weighted_edges(f["eq_turn"], w, q_turn), "spread": weighted_edges(f["spread"], w, 3),
                 "b_top": weighted_edges(f["b_top"], w, 2)}
            t_ids = (to_bin(f["eq_turn"], e["eq_turn"]) * 6 + to_bin(f["spread"], e["spread"]) * 2
                     + to_bin(f["b_top"], e["b_top"]))
        elif mode == "eq_only":
            e = {"eq_turn": weighted_edges(f["eq_turn"], w, q_turn * 6)}
            t_ids = to_bin(f["eq_turn"], e["eq_turn"])
        else:
            raise ValueError(f"unknown turn abstraction mode {mode!r}")
        edges[p] = {k: v.tolist() for k, v in e.items()}
        turn.append(Buckets(t_ids, q_turn * 6, mode, e))
        ids_k = np.zeros(game.masks[p].shape, dtype=np.int64)
        maps = []
        for k in range(len(game.river_cards)):
            alive = game.masks[p][k] > 0
            wk = w * alive
            e_eq = weighted_edges(f["eq_k"][k], wk, q_river if mode == "v1" else q_river * 2)
            key = t_ids * 64 + to_bin(f["eq_k"][k], e_eq) * 2
            if mode == "v1":
                key = key + to_bin(f["b_top_k"][k], weighted_edges(f["b_top_k"][k], wk, 2))
            key = np.where(alive, key, -1)
            uniq, dense = np.unique(key[alive], return_inverse=True)
            ids_k[k, alive] = dense
            maps.append((uniq // 64).tolist())
        widths.append(int(max(len(m) for m in maps)))
        river_ids.append(ids_k)
        turn_of.append(maps)
    return TurnAbstraction(mode, tuple(turn), tuple(river_ids), tuple(widths), tuple(turn_of), edges)


class TiedTurnRiverSolver(TurnRiverSolver):
    """Joint turn + river CFR in which every hand plays its bucket's strategy on each street."""

    def __init__(self, game: TurnRiverGame, abstraction: TurnAbstraction,
                 config: SolverConfig = SolverConfig(), workers: int | None = None) -> None:
        self.abs = abstraction                     # before the base class allocates bucket-sized arrays
        cards = len(game.river_cards)
        self.Mt = tuple(_onehot(b.ids, b.count) for b in abstraction.turn)
        self.river_flat, self.Mr = [], []
        for p in (0, 1):
            width = abstraction.river_width[p]
            flat = (np.arange(cards)[:, None] * width + abstraction.river_ids[p]).ravel()
            self.river_flat.append(flat)
            self.Mr.append(_onehot(flat, cards * width))
        super().__init__(game, config, workers=workers)

    def _turn_rows(self, player: int) -> int:
        return self.abs.turn[player].count

    def _river_rows(self, player: int) -> int:
        return self.abs.river_width[player]

    def _tp(self, nid: int) -> int:
        return self.g.turn_tree.nodes[nid].player

    def _rp(self, key) -> int:
        return self.g.leaves[key[0]].tree.nodes[key[1]].player

    def _expand_turn(self, nid: int, arr: np.ndarray) -> np.ndarray:
        return arr[self.abs.turn[self._tp(nid)].ids]

    def _expand_river(self, key, arr: np.ndarray) -> np.ndarray:
        p = self._rp(key)
        cards, width, a = arr.shape
        return arr.reshape(cards * width, a)[self.river_flat[p]].reshape(cards, -1, a)

    def _turn_sigma(self, nid: int) -> np.ndarray:
        return self._expand_turn(nid, regret_matching(self.turn_regret[nid]))

    def _river_sigma(self, key) -> np.ndarray:
        return self._expand_river(key, regret_matching(self.river_regret[key]))

    def _turn_update(self, nid: int, inst_regret, contribution, t) -> None:
        M = self.Mt[self._tp(nid)]
        self._update(self.turn_regret[nid], self.turn_strategy[nid], M @ inst_regret, M @ contribution, t)

    def _river_update(self, key, inst_regret, contribution, t) -> None:
        p = self._rp(key)
        cards, n, a = inst_regret.shape
        shape = self.river_regret[key].shape
        M = self.Mr[p]
        self._update(self.river_regret[key], self.river_strategy[key],
                     (M @ inst_regret.reshape(cards * n, a)).reshape(shape),
                     (M @ contribution.reshape(cards * n, a)).reshape(shape), t)

    def average_profile(self) -> dict:
        return {"turn": {k: self._expand_turn(k, self._normalise(v)) for k, v in self.turn_strategy.items()},
                "river": {k: self._expand_river(k, self._normalise(v)) for k, v in self.river_strategy.items()}}

    def current_profile(self) -> dict:
        return {"turn": {k: self._turn_sigma(k) for k in self.turn_regret},
                "river": {k: self._river_sigma(k) for k in self.river_regret}}

    def save_checkpoint(self, path):
        raise NotImplementedError("checkpoints of abstraction solves are not supported yet")


def perfect_recall_holds(abstraction: TurnAbstraction, game: TurnRiverGame) -> bool:
    """Every river bucket on every card contains hands of a single turn bucket."""
    for p in (0, 1):
        t_ids = abstraction.turn[p].ids
        for k, mapping in enumerate(abstraction.river_turn_of[p]):
            ids = abstraction.river_ids[p][k]
            alive = game.masks[p][k] > 0
            if not np.array_equal(np.asarray(mapping)[ids[alive]], t_ids[alive]):
                return False
    return True


# ------------------------------------------------------------------ any legal hand
def river_bucket_of_hand(inst: SubgameInstance, player: int, hand, buckets: Buckets) -> int:
    """Bucket of any hand that avoids the board (in the range or not), with the stored bin edges."""
    board = tuple(parse_cards(inst.description["board"]))
    h = np.sort(np.asarray(hand, dtype=np.int16))[None, :]
    if set(board) & set(h[0].tolist()):
        raise ValueError("hand conflicts with the board")
    opp = 1 - player
    w = inst.weights[opp]
    compat = ((hand_masks(inst.hands[opp]) & hand_masks(h)[0]) == 0).astype(np.float64)
    rank_me = int(plo_rank_batch(h, board)[0])
    rank_opp = plo_rank_batch(inst.hands[opp], board)
    share = np.where(rank_me > rank_opp, 1.0, np.where(rank_me == rank_opp, 0.5, 0.0))
    c = (w * compat).sum()
    if buckets.mode == "rank":
        raise ValueError("rank buckets are defined only for hands of the range")
    eq = (w * compat * share).sum() / c if c > 0 else 0.5
    f = river_features(inst, player)
    W = w.sum()
    b_top = ((w * compat * f["opp_top"]).sum() / w[f["opp_top"]].sum()) / (c / W)
    b_bot = ((w * compat * f["opp_bot"]).sum() / w[f["opp_bot"]].sum()) / (c / W)
    if buckets.mode == "eq_only":
        return int(to_bin(np.array([eq]), buckets.edges["eq"])[0])
    e = buckets.edges
    return int(to_bin(np.array([eq]), e["eq"])[0] * 6 + to_bin(np.array([b_top]), e["b_top"])[0] * 2
               + to_bin(np.array([b_bot]), e["b_bot"])[0])
