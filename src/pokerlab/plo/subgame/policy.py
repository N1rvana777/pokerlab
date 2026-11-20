"""Strategy query and local re-solving interfaces for solved subgames.

``StrategyQuery`` and ``SubgameResolver`` are the two interfaces implemented in
this round.  Blueprint and opponent-model interfaces are deliberately absent
from the code: see ``pokerlab.plo.status`` for their status.
"""
from __future__ import annotations

from typing import Protocol, Sequence

import numpy as np

from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig
from pokerlab.plo.subgame.instance import SubgameInstance, plo_river_instance
from pokerlab.plo.subgame.tree import DECISION


class StrategyQuery(Protocol):
    def query(self, history: Sequence[str], hand: str | Sequence[int]) -> dict: ...


class SubgameResolver(Protocol):
    def resolve(self, spec: dict, iterations: int) -> StrategyQuery: ...


class SubgamePolicy:
    """Read-only table: (public action history, own hand) -> action probabilities."""

    def __init__(self, instance: SubgameInstance, profile: dict[int, np.ndarray],
                 reached: dict[int, np.ndarray] | None = None, source: str = "") -> None:
        self.inst = instance
        self.profile = profile
        self.reached = reached
        self.source = source

    @classmethod
    def from_solver(cls, solver: CFRSolver, average: bool = True) -> "SubgamePolicy":
        profile = solver.average_profile() if average else solver.current_profile()
        kind = "average" if average else "current"
        return cls(solver.inst, profile, solver.reached(),
                   f"{solver.config.algorithm} {kind} strategy after {solver.iteration} iterations")

    def node(self, history: Sequence[str]) -> int:
        nid = self.inst.tree.find(history)
        if self.inst.tree.nodes[nid].kind != DECISION:
            raise KeyError(f"history {list(history)} ends at a terminal node")
        return nid

    def query(self, history: Sequence[str], hand: str | Sequence[int]) -> dict:
        nid = self.node(history)
        node = self.inst.tree.nodes[nid]
        i = self.inst.hand_index(node.player, hand)
        probs = self.profile[nid][i]
        reached = None if self.reached is None else bool(self.reached[nid][i])
        return {"player": node.player, "actions": dict(zip(node.actions, map(float, probs))),
                "reached_in_training": reached, "source": self.source}

    def own_reach(self, nid: int) -> np.ndarray:
        """Range weight times the acting player's own action probabilities along the path."""
        tree = self.inst.tree
        player = tree.nodes[nid].player
        reach = self.inst.weights[player].copy()
        current = tree.nodes[tree.root]
        for label in tree.nodes[nid].history:
            a = current.actions.index(label)
            if current.player == player:
                reach = reach * self.profile[current.id][:, a]
            current = tree.nodes[current.children[a]]
        return reach

    def frequencies(self, history: Sequence[str] = ()) -> dict:
        """Range-weighted action frequencies of the acting player at a node (own reach only)."""
        nid = self.node(history)
        node = self.inst.tree.nodes[nid]
        reach = self.own_reach(nid)
        total = reach.sum()
        freq = (reach @ self.profile[nid]) / total if total > 0 else np.full(len(node.actions), np.nan)
        return {"player": node.player, "reach_mass": float(total),
                "actions": dict(zip(node.actions, map(float, freq)))}


class RiverResolver:
    """Unsafe re-solve of a heads-up PLO4 river from given ranges.

    No safe/nested gadget, no gift margins, no handling of off-tree opponent
    sizes: the ranges are taken as given, so the result is an equilibrium of the
    stated subgame only.
    """

    def __init__(self, config: SolverConfig = SolverConfig()) -> None:
        self.config = config

    def resolve(self, spec: dict, iterations: int) -> SubgamePolicy:
        solver = CFRSolver(plo_river_instance(spec), self.config)
        solver.run(iterations)
        return SubgamePolicy.from_solver(solver)
