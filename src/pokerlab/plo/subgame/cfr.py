"""Counterfactual regret minimisation for two-player subgame instances.

Vector form: each decision node stores regrets and the cumulative strategy for
every private hand of the acting player, i.e. one information set per
(hand, public node).  All variants use alternating updates.

    cfr       vanilla regret matching, uniformly weighted average strategy
    cfr+      regret matching+ with linearly weighted average (CFR+, the family
              Libratus used for subgame solving)
    lcfr      linear CFR: iteration t weighs regrets and average by t (the
              weighting Pluribus applied early in blueprint training)
    dcfr      discounted CFR: after iteration t, positive regrets x t^a/(t^a+1),
              negative regrets x t^b/(t^b+1), cumulative strategy x (t/(t+1))^g
    es-mccfr  external-sampling MCCFR: each traversal samples one opponent hand
              (chance) and the opponent's actions; the traverser's hands are
              vectorised and all traverser actions explored.  The average
              strategy is accumulated at sampled opponent nodes.  Optional
              linear weighting by t.

Utilities use the constant-sum convention of the existing workbench: at a
terminal a player receives the chips it wins (sunk starting pot plus the
opponent's new chips) minus its own new chips, so u0 + u1 = pot.
exploitability = (BR0 + BR1 - pot) / 2 = mean gain from switching to a best
response; it is exact for the given ranges and betting abstraction only.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from pokerlab.plo.subgame.instance import SubgameInstance
from pokerlab.plo.subgame.tree import DECISION, FOLD, SHOWDOWN, Node

ALGORITHMS = ("cfr", "cfr+", "lcfr", "dcfr", "es-mccfr")
CHECKPOINT_SCHEMA = "pokerlab.plo.cfr-checkpoint/1"


class CheckpointMismatch(ValueError):
    pass


@dataclass(frozen=True)
class SolverConfig:
    algorithm: str = "dcfr"
    alpha: float = 1.5
    beta: float = 0.0
    gamma: float = 2.0
    linear: bool = True  # es-mccfr: weight iteration t by t
    seed: int = 0

    def __post_init__(self) -> None:
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"algorithm must be one of {ALGORITHMS}")


def regret_matching(regret: np.ndarray) -> np.ndarray:
    positive = np.maximum(regret, 0.0)
    total = positive.sum(axis=-1, keepdims=True)
    uniform = 1.0 / regret.shape[-1]
    return np.where(total > 0.0, positive / np.where(total > 0.0, total, 1.0), uniform)


def terminal_values(node: Node, player: int, pot: int, compat: np.ndarray,
                    win: np.ndarray | None) -> np.ndarray:
    if node.kind == FOLD:
        if node.player == player:
            return -node.commit[player] * compat
        return (pot + node.commit[node.player]) * compat
    called = node.commit[0]
    return (pot + 2 * called) * win - called * compat


def _sample(probabilities: np.ndarray, u: float) -> int:
    cdf = np.cumsum(probabilities)
    return int(min(np.searchsorted(cdf, u * cdf[-1], side="right"), len(cdf) - 1))


class CFRSolver:
    def __init__(self, instance: SubgameInstance, config: SolverConfig = SolverConfig()) -> None:
        self.inst = instance
        self.config = config
        self.tree = instance.tree
        self.pot = instance.pot
        self.weights = instance.weights
        self.iteration = 0
        self.elapsed = 0.0
        self.regret: dict[int, np.ndarray] = {}
        self.strategy_sum: dict[int, np.ndarray] = {}
        for nid in self.tree.decision_nodes():
            node = self.tree.nodes[nid]
            shape = (self._rows(node.player), len(node.children))
            self.regret[nid] = np.zeros(shape)
            self.strategy_sum[nid] = np.zeros(shape)
        self.rng = np.random.default_rng(config.seed)
        self._chance_cdf = [np.cumsum(w / w.sum()) for w in self.weights]

    # -------------------------------------------------------------- training
    def run(self, iterations: int, callback=None) -> None:
        for _ in range(int(iterations)):
            start = time.perf_counter()
            self.step()
            self.elapsed += time.perf_counter() - start
            if callback is not None:
                callback(self)

    def step(self) -> None:
        t = self.iteration + 1
        if self.config.algorithm == "es-mccfr":
            for player in (0, 1):
                self._mccfr_pass(player, t)
        else:
            for player in (0, 1):
                self._traverse(self.tree.root, player, self.weights[player],
                               self.weights[1 - player], t)
            if self.config.algorithm == "dcfr":
                self._discount(t)
        self.iteration = t

    def _traverse(self, nid: int, p: int, reach_p: np.ndarray, reach_o: np.ndarray, t: int) -> np.ndarray:
        node = self.tree.nodes[nid]
        if node.kind != DECISION:
            compat, win = self.inst.showdown.masses(p, reach_o, node.kind == SHOWDOWN)
            return terminal_values(node, p, self.pot, compat, win)
        sigma = self._sigma(nid)
        if node.player == p:
            values = np.empty((len(reach_p), len(node.children)))
            for a, child in enumerate(node.children):
                values[:, a] = self._traverse(child, p, reach_p * sigma[:, a], reach_o, t)
            ev = np.einsum("ia,ia->i", values, sigma)
            self._update(nid, values - ev[:, None], reach_p[:, None] * sigma, t)
            return ev
        total = np.zeros(len(reach_p))
        reach_any = bool(reach_p.any())
        for a, child in enumerate(node.children):
            branch = reach_o * sigma[:, a]
            if reach_any or branch.any():
                total += self._traverse(child, p, reach_p, branch, t)
        return total

    def _rows(self, player: int) -> int:
        """Rows of the regret/strategy arrays: one per hand (abstraction solvers: one per bucket)."""
        return self.inst.size(player)

    def _sigma(self, nid: int) -> np.ndarray:
        """Current strategy at ``nid``, one row per hand (overridden by abstraction solvers)."""
        return regret_matching(self.regret[nid])

    def _update(self, nid: int, inst_regret: np.ndarray, contribution: np.ndarray, t: int) -> None:
        algorithm = self.config.algorithm
        regret = self.regret[nid]
        strategy = self.strategy_sum[nid]
        if algorithm == "cfr+":
            regret += inst_regret
            np.maximum(regret, 0.0, out=regret)
            strategy += t * contribution
        elif algorithm == "lcfr":
            regret += t * inst_regret
            strategy += t * contribution
        else:
            regret += inst_regret
            strategy += contribution

    def _discount(self, t: int) -> None:
        c = self.config
        positive = t ** c.alpha / (t ** c.alpha + 1.0)
        negative = t ** c.beta / (t ** c.beta + 1.0)
        strategy = (t / (t + 1.0)) ** c.gamma
        for nid, regret in self.regret.items():
            regret *= np.where(regret > 0.0, positive, negative)
            self.strategy_sum[nid] *= strategy

    def _mccfr_pass(self, p: int, t: int) -> None:
        o = 1 - p
        cdf = self._chance_cdf[o]
        j = int(min(np.searchsorted(cdf, self.rng.random(), side="right"), len(cdf) - 1))
        weight = float(t) if self.config.linear else 1.0
        self._mccfr(self.tree.root, p, j, float(self.weights[o].sum()), weight)

    def _mccfr(self, nid: int, p: int, j: int, scale: float, weight: float) -> np.ndarray:
        node = self.tree.nodes[nid]
        if node.kind != DECISION:
            compat, win = self.inst.showdown.versus(p, j)
            return scale * terminal_values(node, p, self.pot, compat, win)
        if node.player == p:
            sigma = regret_matching(self.regret[nid])
            values = np.empty(sigma.shape)
            for a, child in enumerate(node.children):
                values[:, a] = self._mccfr(child, p, j, scale, weight)
            ev = np.einsum("ia,ia->i", values, sigma)
            self.regret[nid] += weight * (values - ev[:, None])
            return ev
        sigma_j = regret_matching(self.regret[nid][j])
        self.strategy_sum[nid][j] += weight * sigma_j
        a = _sample(sigma_j, self.rng.random())
        return self._mccfr(node.children[a], p, j, scale, weight)

    # ------------------------------------------------------------ strategies
    def average_strategy(self, nid: int) -> np.ndarray:
        total = self.strategy_sum[nid].sum(axis=1, keepdims=True)
        width = self.strategy_sum[nid].shape[1]
        return np.where(total > 0.0, self.strategy_sum[nid] / np.where(total > 0.0, total, 1.0),
                        1.0 / width)

    def average_profile(self) -> dict[int, np.ndarray]:
        return {nid: self.average_strategy(nid) for nid in self.regret}

    def current_profile(self) -> dict[int, np.ndarray]:
        return {nid: regret_matching(r) for nid, r in self.regret.items()}

    def reached(self) -> dict[int, np.ndarray]:
        """Whether a hand ever accumulated average-strategy weight at a node."""
        return {nid: s.sum(axis=1) > 0.0 for nid, s in self.strategy_sum.items()}

    def memory_bytes(self) -> int:
        arrays = sum(a.nbytes for a in self.regret.values()) + sum(
            a.nbytes for a in self.strategy_sum.values())
        return arrays + self.inst.showdown.memory_bytes()

    # ------------------------------------------------------------ checkpoint
    def save_checkpoint(self, path: str | os.PathLike) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "schema": CHECKPOINT_SCHEMA, "fingerprint": self.inst.fingerprint,
            "config": asdict(self.config), "iteration": self.iteration,
            "elapsed_s": self.elapsed, "rng_state": self.rng.bit_generator.state,
            "nodes": sorted(self.regret), "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        arrays = {"meta": np.array(json.dumps(meta))}
        for nid in self.regret:
            arrays[f"regret_{nid}"] = self.regret[nid]
            arrays[f"strategy_{nid}"] = self.strategy_sum[nid]
        partial = path.with_name(path.name + ".partial")
        with open(partial, "wb") as fh:
            np.savez(fh, **arrays)
        os.replace(partial, path)
        return path

    @classmethod
    def load_checkpoint(cls, path: str | os.PathLike, instance: SubgameInstance) -> "CFRSolver":
        with np.load(Path(path), allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            if meta.get("schema") != CHECKPOINT_SCHEMA:
                raise CheckpointMismatch(f"unknown checkpoint schema {meta.get('schema')!r}")
            if meta["fingerprint"] != instance.fingerprint:
                raise CheckpointMismatch("checkpoint belongs to a different subgame (fingerprint differs)")
            solver = cls(instance, SolverConfig(**meta["config"]))
            if sorted(solver.regret) != meta["nodes"]:
                raise CheckpointMismatch("tree layout differs from checkpoint")
            for nid in solver.regret:
                regret, strategy = data[f"regret_{nid}"], data[f"strategy_{nid}"]
                expected = solver.regret[nid].shape
                if regret.shape != expected or strategy.shape != expected:
                    raise CheckpointMismatch(f"array shape differs at node {nid}")
                solver.regret[nid] = regret.copy()
                solver.strategy_sum[nid] = strategy.copy()
        solver.iteration = int(meta["iteration"])
        solver.elapsed = float(meta.get("elapsed_s", 0.0))
        solver.rng.bit_generator.state = meta["rng_state"]
        return solver


# ------------------------------------------------------------------ evaluation
def _best_response(inst: SubgameInstance, nid: int, p: int, reach_o: np.ndarray,
                   profile: dict[int, np.ndarray]) -> np.ndarray:
    node = inst.tree.nodes[nid]
    if node.kind != DECISION:
        compat, win = inst.showdown.masses(p, reach_o, node.kind == SHOWDOWN)
        return terminal_values(node, p, inst.pot, compat, win)
    if node.player == p:
        return np.max(np.stack([_best_response(inst, c, p, reach_o, profile)
                                for c in node.children]), axis=0)
    sigma = profile[nid]
    return sum(_best_response(inst, c, p, reach_o * sigma[:, a], profile)
               for a, c in enumerate(node.children))


def _expected(inst: SubgameInstance, nid: int, p: int, reach_o: np.ndarray,
              profile: dict[int, np.ndarray]) -> np.ndarray:
    node = inst.tree.nodes[nid]
    if node.kind != DECISION:
        compat, win = inst.showdown.masses(p, reach_o, node.kind == SHOWDOWN)
        return terminal_values(node, p, inst.pot, compat, win)
    sigma = profile[nid]
    if node.player == p:
        return sum(sigma[:, a] * _expected(inst, c, p, reach_o, profile)
                   for a, c in enumerate(node.children))
    return sum(_expected(inst, c, p, reach_o * sigma[:, a], profile)
               for a, c in enumerate(node.children))


def normaliser(inst: SubgameInstance) -> float:
    compat, _ = inst.showdown.masses(0, inst.weights[1], need_win=False)
    return float(inst.weights[0] @ compat)


def evaluate_profile(inst: SubgameInstance, profile: dict[int, np.ndarray]) -> dict:
    """Values, best-response values and exploitability (chips, bb and % of the starting pot)."""
    z = normaliser(inst)
    value = [float(inst.weights[p] @ _expected(inst, inst.tree.root, p, inst.weights[1 - p], profile)) / z
             for p in (0, 1)]
    br = [float(inst.weights[p] @ _best_response(inst, inst.tree.root, p, inst.weights[1 - p], profile)) / z
          for p in (0, 1)]
    exploitability = (br[0] + br[1] - inst.pot) / 2.0
    return {
        "value": value, "best_response_value": br,
        "value_net_of_equal_sunk_share": [v - inst.pot / 2.0 for v in value],
        "gain": [br[0] - value[0], br[1] - value[1]],
        "nash_conv_chips": br[0] + br[1] - inst.pot,
        "exploitability_chips": exploitability,
        "exploitability_bb": exploitability / inst.big_blind,
        "exploitability_pct_pot": 100.0 * exploitability / inst.pot,
        "constant_sum_check": value[0] + value[1] - inst.pot,
        "definitions": METRIC_DEFINITIONS,
    }


METRIC_DEFINITIONS = {
    "value": ("expected chips from the start of the subgame: chips received (sunk starting pot "
              "plus the opponent's new chips) minus own new chips, so value0 + value1 = pot"),
    "value_net_of_equal_sunk_share": ("value - pot/2: zero-sum net result when each player put "
                                      "half of the sunk pot in (heads-up street start; Kuhn antes)"),
    "best_response_value": ("value of a best response to the other player's profile strategy, "
                            "chosen per information set (own hand, public node) among the abstract "
                            "tree's actions only; opponent hands are summed, never conditioned on"),
    "nash_conv_chips": "BR0 + BR1 - pot (sum of both players' gains from deviating)",
    "exploitability_chips": "NashConv / 2 = mean gain from deviating, invariant to constant offsets",
    "exploitability_pct_pot": "100 * exploitability_chips / starting pot of the subgame",
}


def response_value(inst: SubgameInstance, profile: dict[int, np.ndarray], player: int) -> dict:
    """Value of ``player``'s profile strategy and of its best response against the opponent's."""
    z = normaliser(inst)
    o = 1 - player
    current = float(inst.weights[player] @ _expected(inst, inst.tree.root, player, inst.weights[o], profile)) / z
    best = float(inst.weights[player] @ _best_response(inst, inst.tree.root, player, inst.weights[o], profile)) / z
    return {"value": current, "best_response_value": best, "gap": best - current}
