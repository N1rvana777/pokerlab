"""Minimal heads-up PLO4 blueprint: external-sampling MCCFR over preflop, flop, turn and river.

Game: two players, blinds and a fixed effective stack, a limited pot-limit action abstraction per
street (``pokerlab.plo.betting``, the engine's formula), chance = the hole cards and the five board
cards.  Player 0 is the big blind (out of position after the flop), player 1 the button/small blind,
who acts first preflop.

Public tree: one ``BettingTree`` per street and per (pot, remaining stack); a street ends at a
check-check or a call (preflop: also the big blind's check after a limp) and continues on the next
street with pot + 2 * commitment, or goes to showdown when someone is all-in or the river ended.
The turn and river trees are built exactly as ``subgame.turn`` builds them, so a blueprint started on
the turn has the same node ids as the exact joint solver (used by the validation).

Training (external sampling, alternating players, linear weighting of regrets and average strategy):
each iteration samples one deal (hands from the ranges, or uniformly; the remaining board uniformly),
then for each traverser explores all its actions and samples one action at opponent nodes.  An
information set is (public node, bucket of the acting player's hand on that street).

Abstraction: pluggable ``bucket(player, street, hand, board)``.  ``IdentityBuckets`` keeps every hand
(and on the river every river card) distinct -- exact information sets, used to validate against the
full-width solvers.  ``CoarseBuckets`` is the first full-game abstraction: preflop strength quantiles;
on later streets the board-relative strength percentile of the best 2 + 3 hand, plus a flush-draw flag
(flop/turn) and a nut-flush-blocker flag.  Buckets are computed per street independently, so players
can forget earlier buckets: this abstraction does NOT keep perfect recall and MCCFR's convergence
guarantee does not apply to it; the identity version keeps perfect recall.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from pokerlab.plo.baseline import every_hand, preflop_scores
from pokerlab.plo.cards import DECK, format_cards
from pokerlab.plo.evaluator import HOLE_PAIRS, _PAIR_ID, best_pair_ranks, plo_rank_batch
from pokerlab.plo.subgame.cfr import regret_matching
from pokerlab.plo.subgame.instance import betting_config
from pokerlab.plo.subgame.tree import DECISION, FOLD, SHOWDOWN, BettingConfig, BettingTree, RootState

PREFLOP, FLOP, TURN, RIVER = 0, 1, 2, 3
BOARD_AT = (0, 3, 4, 5)
CHECKPOINT_SCHEMA = "pokerlab.plo.blueprint-checkpoint/1"


# ------------------------------------------------------------------ preflop tree
@dataclass(frozen=True)
class PreflopConfig(BettingConfig):
    """Preflop: nothing is in the pot before the street; the blinds are street commitments."""

    def __post_init__(self) -> None:
        if int(self.pot) != 0 or len(self.stacks) != 2 or min(self.stacks) <= 0:
            raise ValueError("preflop config: pot 0 and two positive stacks")
        values = {k: getattr(self, k) for k in BettingConfig.__dataclass_fields__}
        checked = BettingConfig(**{**values, "pot": 1})          # validates sizes and caps
        object.__setattr__(self, "bet_sizes", checked.bet_sizes)
        object.__setattr__(self, "raise_sizes", checked.raise_sizes)


class PreflopTree(BettingTree):
    """Preflop betting: the small blind acts first; after a limp the big blind may check or raise."""

    def _build(self, commit, actor, current_bet, last_increment, raises, history, checked):
        cfg = self.config
        node = self._new(kind=DECISION, player=actor, commit=commit, history=history,
                         current_bet=current_bet, raises=raises)
        other = 1 - actor
        to_call = current_bet - commit[actor]
        stack = cfg.effective_stack
        labels, children, all_in = [], [], []

        def add(label, child, shove):
            labels.append(label)
            children.append(child)
            all_in.append(shove)

        if to_call == 0:                                     # the big blind's option after a limp
            add("check", self._new(kind=SHOWDOWN, player=-1, commit=commit, history=history + ("check",)).id, False)
            if raises < cfg.max_raises:
                for to in self.targets(commit, actor, current_bet, last_increment):
                    new = list(commit)
                    new[actor] = to
                    label = f"raise:{to}"
                    add(label, self._build(tuple(new), other, to, max(to - current_bet, last_increment),
                                           raises + 1, history + (label,), checked), to == stack)
        else:
            add("fold", self._new(kind=FOLD, player=actor, commit=commit, history=history + ("fold",)).id, False)
            called = (current_bet, current_bet)
            if not history and actor == 1:                   # small blind limps: the big blind still acts
                add("call", self._build(called, other, current_bet, last_increment, raises,
                                        history + ("call",), checked), False)
            else:
                add("call", self._new(kind=SHOWDOWN, player=-1, commit=called, history=history + ("call",)).id,
                    False)
            if raises < cfg.max_raises:
                for to in self.targets(commit, actor, current_bet, last_increment):
                    new = list(commit)
                    new[actor] = to
                    label = f"raise:{to}"
                    add(label, self._build(tuple(new), other, to, max(to - current_bet, last_increment),
                                           raises + 1, history + (label,), checked), to == stack)
        node.actions, node.children, node.all_in = tuple(labels), tuple(children), tuple(all_in)
        return node.id


# ------------------------------------------------------------------ game
@dataclass(frozen=True)
class StreetSizes:
    bet_sizes: tuple[str, ...] = ("1/2", "1")
    raise_sizes: tuple[str, ...] = ("1",)
    include_min_raise: bool = False
    include_max_raise: bool = True
    max_raises: int = 1


@dataclass
class BlueprintSpec:
    big_blind: int = 100
    small_blind: int = 50
    stack: int = 2000                         # effective stack in chips (both players)
    preflop: StreetSizes = field(default_factory=lambda: StreetSizes((), ("1",), False, True, 2))
    postflop: StreetSizes = field(default_factory=StreetSizes)
    start_street: int = PREFLOP               # PREFLOP, or TURN / RIVER for validation subgames
    board: tuple[int, ...] = ()               # fixed board prefix when start_street > PREFLOP
    pot: int = 0                              # pot at the start of start_street (> 0 unless preflop)
    turn_max_raises: int | None = None        # per-street caps (validation: match the exact solver)
    river_max_raises: int | None = None

    def describe(self) -> dict:
        d = asdict(self)
        d["board"] = format_cards(self.board) if self.board else ""
        return d


class BlueprintGame:
    """Multi-street public tree built from per-street betting trees."""

    def __init__(self, spec: BlueprintSpec) -> None:
        self.spec = spec
        self.trees: dict[tuple, BettingTree] = {}
        self.street_of: dict[tuple, int] = {}
        if spec.start_street == PREFLOP:
            s = spec.preflop
            cfg = PreflopConfig(pot=0, stacks=(spec.stack, spec.stack), bet_sizes=s.bet_sizes or ("1",),
                                raise_sizes=s.raise_sizes, include_min_raise=s.include_min_raise,
                                include_max_raise=s.include_max_raise, max_raises=s.max_raises,
                                min_bet=spec.big_blind)
            root = RootState(commit=(spec.big_blind, spec.small_blind), actor=1, current_bet=spec.big_blind,
                             last_increment=spec.big_blind, raises=0, checked=False)
            self.root = ("pre",)
            self.trees[self.root] = PreflopTree(cfg, root)
            self.street_of[self.root] = PREFLOP
            self.root_contrib = 0
        else:
            self.root = self._street_tree(spec.start_street, spec.pot, spec.stack)
            self.root_contrib = 0             # utilities measured from the start of start_street (pot sunk)

    def _street_tree(self, street: int, pot: int, remaining: int) -> tuple:
        key = (street, pot, remaining)
        if key not in self.trees:
            s = self.spec.postflop
            caps = {TURN: self.spec.turn_max_raises, RIVER: self.spec.river_max_raises}
            cap = caps.get(street)
            spec = {"bet_sizes": list(s.bet_sizes), "raise_sizes": list(s.raise_sizes),
                    "include_min_raise": s.include_min_raise, "include_max_raise": s.include_max_raise,
                    "max_raises": s.max_raises if cap is None else cap, "min_bet": self.spec.big_blind}
            self.trees[key] = BettingTree(betting_config(spec, pot, (remaining, remaining), self.spec.big_blind))
            self.street_of[key] = street
        return key

    def next_street(self, key: tuple, node) -> tuple | None:
        """Tree that follows a street-ending node, or None for a showdown (river ended or all-in)."""
        street = self.street_of[key]
        tree = self.trees[key]
        cfg = tree.config
        commit = node.commit[0]
        remaining = cfg.effective_stack - commit
        if street == RIVER or remaining <= 0:
            return None
        return self._street_tree(street + 1, cfg.pot + 2 * commit, remaining)

    def build_all(self) -> dict:
        """Expand every reachable street tree; returns size counts."""
        todo, seen = [self.root], set()
        while todo:
            key = todo.pop()
            if key in seen:
                continue
            seen.add(key)
            for node in self.trees[key].nodes:
                if node.kind == SHOWDOWN:
                    nxt = self.next_street(key, node)
                    if nxt is not None:
                        todo.append(nxt)
        counts = {s: 0 for s in range(4)}
        nodes = {s: 0 for s in range(4)}
        for key in seen:
            counts[self.street_of[key]] += 1
            nodes[self.street_of[key]] += len(self.trees[key].decision_nodes())
        return {"street_trees": counts, "decision_nodes": nodes, "keys": len(seen)}


# ------------------------------------------------------------------ buckets
class IdentityBuckets:
    """Exact information sets for validation subgames: hand index; on the river (card index, hand index)."""

    def __init__(self, hands: tuple[np.ndarray, np.ndarray], river_cards: np.ndarray | None = None) -> None:
        self.index = [{tuple(sorted(int(c) for c in h)): i for i, h in enumerate(hs)} for hs in hands]
        self.n = [len(h) for h in hands]
        self.river_cards = None if river_cards is None else {int(c): k for k, c in enumerate(river_cards)}
        self.describe = {"kind": "identity", "perfect_recall": True}

    def count(self, player: int, street: int) -> int:
        if street == RIVER and self.river_cards is not None:
            return len(self.river_cards) * self.n[player]
        return self.n[player]

    def bucket(self, player: int, street: int, hand, board) -> int:
        i = self.index[player][tuple(sorted(int(c) for c in hand))]
        if street == RIVER and self.river_cards is not None:
            return self.river_cards[int(board[4])] * self.n[player] + i
        return i


class CoarseBuckets:
    """First full-game abstraction (coarse; per street, so no perfect recall).

    Strength on a board = percentile of the hand's best 2 + 3 rank among the best ranks of all live
    2-card hole pairs on that board (one ``best_pair_ranks`` table per board, shared by both players and
    by the showdown).  Flop/turn add a flush-draw flag (two cards of a suit with two on the board) and
    every postflop street a nut-flush-blocker flag (the ace of the suit with the most board cards, when
    that suit has at least two cards on the flop/turn or three on the river).
    """

    def __init__(self, preflop: int = 16, strength: int = 8, river_strength: int = 12) -> None:
        scores = np.sort(preflop_scores(every_hand()))
        self.pre_edges = scores[(np.arange(1, preflop) * len(scores)) // preflop]
        self.sizes = {PREFLOP: preflop, FLOP: strength * 4, TURN: strength * 4, RIVER: river_strength * 2}
        self.strength, self.river_strength = strength, river_strength
        self.describe = {"kind": "coarse", "preflop_quantiles": preflop,
                         "flop_turn": f"{strength} strength bins x flush draw x nut-flush blocker",
                         "river": f"{river_strength} strength bins x nut-flush blocker",
                         "strength": "percentile of the best 2+3 rank among all live 2-card hole pairs on the board",
                         "perfect_recall": False}

    def count(self, player: int, street: int) -> int:
        return self.sizes[street]

    def preflop_bucket(self, hand) -> int:
        score = float(preflop_scores(np.asarray([sorted(hand)], dtype=np.int16))[0])
        return int(np.searchsorted(self.pre_edges, score, side="right"))

    def deal(self, hands, board, first_street: int):
        """Buckets of both players on every street from ``first_street``, and both river ranks."""
        out, ranks = {}, None
        for street in range(first_street, 4):
            if street == PREFLOP:
                for p in (0, 1):
                    out[(p, PREFLOP)] = self.preflop_bucket(hands[p])
                continue
            b = tuple(int(c) for c in board[:BOARD_AT[street]])
            table = best_pair_ranks(b)
            live = np.sort(table[table >= 0])
            board_suits = _suit_counts(b)
            flush_suit = int(np.argmax(board_suits))
            need = 3 if street == RIVER else 2
            best = []
            for p in (0, 1):
                h = hands[p]
                r = int(table[_PAIR_ID[[h[i] for i, _ in HOLE_PAIRS], [h[j] for _, j in HOLE_PAIRS]]].max())
                best.append(r)
                pct = float(np.searchsorted(live, r, side="right")) / len(live)
                blocker = int(board_suits[flush_suit] >= need and (4 * 12 + flush_suit) in h)
                if street == RIVER:
                    out[(p, street)] = min(int(pct * self.river_strength), self.river_strength - 1) * 2 + blocker
                else:
                    hs = _suit_counts(h)
                    draw = int(any(board_suits[x] == 2 and hs[x] >= 2 for x in range(4)))
                    out[(p, street)] = ((min(int(pct * self.strength), self.strength - 1) * 2 + draw) * 2
                                        + blocker)
            if street == RIVER:
                ranks = best
        return out, ranks

    def bucket(self, player: int, street: int, hand, board) -> int:
        hands = (tuple(hand), tuple(hand)) if player == 0 else (tuple(hand), tuple(hand))
        return self.deal(hands, board, street)[0][(player, street)]


def _suit_counts(cards) -> list[int]:
    counts = [0, 0, 0, 0]
    for c in cards:
        counts[int(c) % 4] += 1
    return counts


def _triples(board: tuple) -> list[tuple]:
    from itertools import combinations
    return list(combinations(board, 3))


# ------------------------------------------------------------------ trainer
class BlueprintTrainer:
    """External-sampling MCCFR with linear weighting over a ``BlueprintGame``."""

    def __init__(self, game: BlueprintGame, buckets, ranges: tuple | None = None, seed: int = 0) -> None:
        self.game, self.buckets, self.seed = game, buckets, seed
        self.ranges = ranges                     # ((hands0, weights0), (hands1, weights1)) or None: uniform
        self.rng = np.random.default_rng(seed)
        self.iteration = 0
        self.elapsed = 0.0
        self.regret: dict[tuple, np.ndarray] = {}
        self.strategy_sum: dict[tuple, np.ndarray] = {}
        self._all_hands = every_hand() if ranges is None else None
        if ranges is not None:
            self._cdf = [np.cumsum(w / w.sum()) for _, w in ranges]

    # ---- tables
    def _table(self, key: tuple, nid: int, player: int, street: int, n_actions: int):
        k = (key, nid)
        if k not in self.regret:
            shape = (self.buckets.count(player, street), n_actions)
            self.regret[k] = np.zeros(shape)
            self.strategy_sum[k] = np.zeros(shape)
        return k

    # ---- chance
    def _deal(self):
        board_fixed = tuple(self.game.spec.board)
        while True:
            if self.ranges is None:
                hands = self._all_hands[self.rng.integers(len(self._all_hands), size=2)]
                h0, h1 = tuple(int(c) for c in hands[0]), tuple(int(c) for c in hands[1])
            else:
                i = int(np.searchsorted(self._cdf[0], self.rng.random(), side="right"))
                j = int(np.searchsorted(self._cdf[1], self.rng.random(), side="right"))
                h0 = tuple(int(c) for c in self.ranges[0][0][min(i, len(self._cdf[0]) - 1)])
                h1 = tuple(int(c) for c in self.ranges[1][0][min(j, len(self._cdf[1]) - 1)])
            used = set(h0) | set(h1) | set(board_fixed)
            if len(used) == 8 + len(board_fixed):
                break
        rest = [c for c in DECK if c not in used]
        extra = self.rng.choice(len(rest), size=5 - len(board_fixed), replace=False)
        board = board_fixed + tuple(int(rest[x]) for x in extra)
        return (h0, h1), board

    # ---- traversal
    def iterate(self, iterations: int, callback=None) -> None:
        for _ in range(int(iterations)):
            start = time.perf_counter()
            t = self.iteration + 1
            hands, board = self._deal()
            first = self.game.street_of[self.game.root]
            if hasattr(self.buckets, "deal"):
                bucket, ranks = self.buckets.deal(hands, board, first)
            else:
                bucket = {(p, s): self.buckets.bucket(p, s, hands[p], board) for p in (0, 1) for s in range(first, 4)}
                ranks = plo_rank_batch(np.array([sorted(hands[0]), sorted(hands[1])], dtype=np.int16), board)
            result = int(np.sign(int(ranks[0]) - int(ranks[1])))
            base = self.game.spec.pot / 2.0         # each player's share of a sunk starting pot
            for p in (0, 1):
                self._walk(self.game.root, 0, p, bucket, result, base, float(t))
            self.iteration = t
            self.elapsed += time.perf_counter() - start
            if callback is not None:
                callback(self)

    def _walk(self, key, nid, p, bucket, result, base, weight) -> float:
        """Value for traverser p: chips won, counting each player's contribution ``base`` before this street."""
        tree = self.game.trees[key]
        node = tree.nodes[nid]
        if node.kind == FOLD:
            folder = node.player
            return float(-(base + node.commit[p]) if folder == p else base + node.commit[folder])
        if node.kind == SHOWDOWN:
            nxt = self.game.next_street(key, node)
            if nxt is not None:
                return self._walk(nxt, self.game.trees[nxt].root, p, bucket, result, base + node.commit[0], weight)
            paid = base + node.commit[0]                     # equal commitments at a showdown
            share = result if p == 0 else -result
            return float(share * paid)
        street = self.game.street_of[key]
        actor = node.player
        k = self._table(key, nid, actor, street, len(node.children))
        b = bucket[(actor, street)]
        sigma = regret_matching(self.regret[k][b])
        if actor == p:
            values = np.array([self._walk(key, child, p, bucket, result, base, weight) for child in node.children])
            ev = float(values @ sigma)
            self.regret[k][b] += weight * (values - ev)
            return ev
        self.strategy_sum[k][b] += weight * sigma
        a = int(min(np.searchsorted(np.cumsum(sigma), self.rng.random() * sigma.sum(), side="right"),
                    len(sigma) - 1))
        return self._walk(key, node.children[a], p, bucket, result, base, weight)

    # ---- strategies
    def average(self, key, nid) -> np.ndarray:
        s = self.strategy_sum[(key, nid)]
        tot = s.sum(axis=1, keepdims=True)
        return np.where(tot > 0, s / np.where(tot > 0, tot, 1.0), 1.0 / s.shape[1])

    def stats(self) -> dict:
        entries = sum(a.size for a in self.regret.values())
        return {"iterations": self.iteration, "elapsed_s": round(self.elapsed, 2), "infoset_tables": len(self.regret),
                "table_entries": int(entries), "table_mib": round(2 * entries * 8 / 2**20, 2)}

    # ---- checkpoint
    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        keys = sorted(self.regret, key=repr)
        meta = {"schema": CHECKPOINT_SCHEMA, "spec": self.game.spec.describe(), "buckets": self.buckets.describe,
                "seed": self.seed, "iteration": self.iteration, "elapsed_s": self.elapsed,
                "keys": [repr(k) for k in keys], "rng": self.rng.bit_generator.state}
        arrays = {"meta": np.array(json.dumps(meta, default=str))}
        for i, k in enumerate(keys):
            arrays[f"r{i}"], arrays[f"s{i}"] = self.regret[k], self.strategy_sum[k]
        partial = path.with_name(path.name + ".partial")
        with open(partial, "wb") as fh:
            np.savez(fh, **arrays)
        os.replace(partial, path)
        return path

    def load(self, path) -> None:
        with np.load(Path(path), allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            if meta["schema"] != CHECKPOINT_SCHEMA or meta["spec"] != json.loads(json.dumps(self.game.spec.describe(), default=str)):
                raise ValueError("checkpoint belongs to a different blueprint game")
            for i, rk in enumerate(meta["keys"]):
                k = eval_key(rk)
                self.regret[k], self.strategy_sum[k] = data[f"r{i}"].copy(), data[f"s{i}"].copy()
            self.iteration, self.elapsed = int(meta["iteration"]), float(meta["elapsed_s"])
            self.rng.bit_generator.state = meta["rng"]


def eval_key(text: str) -> tuple:
    """Parse a table key written by ``repr`` (tuples of ints and strings only)."""
    import ast
    return ast.literal_eval(text)


# ------------------------------------------------------------------ vectorised buckets (range tracking)
def coarse_hand_buckets(buckets: CoarseBuckets, street: int, board, hands: np.ndarray) -> np.ndarray:
    """``CoarseBuckets`` bucket of many hands on one street (equal to ``deal`` for each hand)."""
    hands = np.asarray(hands, dtype=np.int64)
    if street == PREFLOP:
        return np.searchsorted(buckets.pre_edges, preflop_scores(hands), side="right").astype(np.int64)
    b = tuple(int(c) for c in board[:BOARD_AT[street]])
    table = best_pair_ranks(b)
    live = np.sort(table[table >= 0])
    ids = _PAIR_ID[hands[:, [i for i, _ in HOLE_PAIRS]], hands[:, [j for _, j in HOLE_PAIRS]]]
    best = table[ids].max(axis=1)
    pct = np.searchsorted(live, best, side="right") / len(live)
    board_suits = np.array(_suit_counts(b))
    flush_suit = int(np.argmax(board_suits))
    need = 3 if street == RIVER else 2
    blocker = ((board_suits[flush_suit] >= need) & (hands == 4 * 12 + flush_suit).any(axis=1)).astype(np.int64)
    if street == RIVER:
        return np.minimum((pct * buckets.river_strength).astype(np.int64), buckets.river_strength - 1) * 2 + blocker
    hs = ((hands % 4)[:, :, None] == np.arange(4)).sum(axis=1)
    draw = ((board_suits[None, :] == 2) & (hs >= 2)).any(axis=1).astype(np.int64)
    strength = np.minimum((pct * buckets.strength).astype(np.int64), buckets.strength - 1)
    return (strength * 2 + draw) * 2 + blocker


# ------------------------------------------------------------------ policy query
class OutOfTree(ValueError):
    """The real hand left the blueprint's action abstraction (e.g. more raises than the tree allows)."""


class BlueprintPolicy:
    """Strategy query for real hands: maps an Observation's public history onto the blueprint tree."""

    def __init__(self, trainer: BlueprintTrainer) -> None:
        self.trainer, self.game, self.buckets = trainer, trainer.game, trainer.buckets

    @classmethod
    def load(cls, checkpoint, spec: BlueprintSpec | None = None, buckets=None) -> "BlueprintPolicy":
        trainer = BlueprintTrainer(BlueprintGame(spec or BlueprintSpec()), buckets or CoarseBuckets())
        trainer.load(checkpoint)
        return cls(trainer)

    @staticmethod
    def tree_player(obs_button: int, seat: int) -> int:
        return 0 if seat == (obs_button + 1) % 2 else 1           # 0 = big blind

    def walk(self, history, button: int, until_street: int):
        """Yield (record, key, node, label_used, translated) along the history; return the final position."""
        key = self.game.root
        node = self.game.trees[key].nodes[0]
        street = self.game.street_of[key]
        steps = []
        for record in history:
            while record.street > street:
                key, node, street = self._advance(key, node)
            if node.kind != DECISION or node.player != self.tree_player(button, record.seat):
                raise OutOfTree(f"tree and hand diverged before {record.type.value} on street {record.street}")
            label, translated = self._label(record, node, self.game.trees[key].config.effective_stack)
            steps.append((record, key, node, label, translated))
            node = self.game.trees[key].nodes[node.children[node.actions.index(label)]]
        while street < until_street and node.kind == SHOWDOWN:
            key, node, street = self._advance(key, node)
        return steps, key, node, street

    def _advance(self, key, node):
        if node.kind != SHOWDOWN:
            raise OutOfTree("the hand reached a new street where the blueprint tree did not")
        nxt = self.game.next_street(key, node)
        if nxt is None:
            raise OutOfTree("history continues after the blueprint tree ended (all-in or river)")
        return nxt, self.game.trees[nxt].nodes[0], self.game.street_of[nxt]

    @staticmethod
    def _label(record, node, effective_stack: int) -> tuple[str, bool]:
        kind = record.type.value
        label = kind if kind in ("check", "call", "fold") else f"{kind}:{min(record.to, effective_stack)}"
        if label in node.actions:
            return label, False
        sized = [a for a in node.actions if a.startswith(kind + ":")]
        if sized:                                                   # nearest in-tree size of the same kind
            return min(sized, key=lambda a: abs(int(a.split(":")[1]) - record.to)), True
        raise OutOfTree(f"{kind} to {record.to} has no counterpart in the blueprint tree "
                        f"(available: {', '.join(node.actions)})")

    def probs(self, obs) -> tuple[tuple[str, ...], np.ndarray, dict]:
        steps, key, node, street = self.walk(obs.history, obs.button, obs.street)
        if node.kind != DECISION or node.player != self.tree_player(obs.button, obs.seat):
            raise OutOfTree("blueprint tree is not at this player's decision")
        bucket = int(coarse_hand_buckets(self.buckets, street, obs.board, np.array([sorted(obs.hole_cards)]))[0]) \
            if isinstance(self.buckets, CoarseBuckets) else self.buckets.bucket(node.player, street, obs.hole_cards, obs.board)
        k = (key, node.id)
        table = self.trainer.average(*k) if k in self.trainer.strategy_sum else None
        probs = table[bucket] if table is not None else np.full(len(node.actions), 1.0 / len(node.actions))
        return node.actions, probs, {"street": street, "bucket": bucket, "tree_key": list(key), "node": node.id,
                                     "trained": table is not None,
                                     "translations": [(r.type.value, r.to, lab) for r, _, _, lab, tr in steps if tr]}

    def log_likelihood(self, history, button: int, seat: int, board, candidates: np.ndarray, before: int,
                       floor: float = 1e-3) -> tuple[np.ndarray, list[dict]]:
        """Bayes log-weights of ``candidates`` for ``seat``'s actions on streets before ``before``."""
        steps, _, _, _ = self.walk([r for r in history if r.street < before], button, PREFLOP)
        player = self.tree_player(button, seat)
        logw = np.zeros(len(candidates))
        trace = []
        for record, key, node, label, translated in steps:
            if record.seat != seat:
                continue
            street = self.game.street_of[key]
            b = coarse_hand_buckets(self.buckets, street, board, candidates)
            k = (key, node.id)
            table = self.trainer.average(*k) if k in self.trainer.strategy_sum else \
                np.full((self.buckets.count(player, street), len(node.actions)), 1.0 / len(node.actions))
            lik = np.maximum(table[b, node.actions.index(label)], floor)
            logw += np.log(lik)
            w = np.exp(logw - logw.max())
            trace.append({"street": street, "action": label, "translated": translated,
                          "effective_hands": float(w.sum() ** 2 / (w ** 2).sum())})
        return logw, trace
