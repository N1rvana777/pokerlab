"""Baseline PLO agents for functional tests and evaluation plumbing.

They are intentionally simple.  Beating them only shows that the pipeline works
or that one local capability exists; it is never evidence of professional
strength, GTO play or real-world profit.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Protocol

from pokerlab.plo.engine import Action, ActionType, Observation, PublicHandSummary
from pokerlab.plo.evaluator import category_of, plo_rank_reference


class Agent(Protocol):
    name: str
    version: str

    def act(self, obs: Observation) -> Action: ...

    def end_hand(self, summary: PublicHandSummary, seat: int, players: tuple[int, ...]) -> None: ...

    def describe(self) -> dict: ...


class BaseAgent:
    name = "base"
    version = "0"
    depth_validation = "fixed rules; not trained or validated at any stack depth"

    def params(self) -> dict:
        return {}

    def describe(self) -> dict:
        return {"name": self.name, "version": self.version, "params": self.params(),
                "depth_validation": self.depth_validation}

    def end_hand(self, summary: PublicHandSummary, seat: int, players: tuple[int, ...]) -> None:
        """Public post-hand information; baseline agents keep no memory."""

    @staticmethod
    def passive(obs: Observation) -> Action:
        return Action.check() if obs.legal.can_check else Action.call()

    @staticmethod
    def aggressive(obs: Observation, to: int) -> Action:
        legal = obs.legal
        to = max(legal.min_to, min(legal.max_to, int(to)))
        return Action(legal.raise_type, to)


class CallingStation(BaseAgent):
    """Always checks or calls."""
    name = "calling_station"
    version = "1"

    def act(self, obs: Observation) -> Action:
        return self.passive(obs)


class RandomAgent(BaseAgent):
    """Picks an available action kind by weight, then min / half / max sizing uniformly."""
    name = "random"
    version = "1"

    def __init__(self, seed: int = 0, fold: float = 1.0, passive: float = 1.0,
                 aggressive: float = 1.0) -> None:
        self.seed = seed
        self.weights = (fold, passive, aggressive)
        self.rng = random.Random(seed)

    def params(self) -> dict:
        return {"seed": self.seed, "weights": list(self.weights)}

    def act(self, obs: Observation) -> Action:
        legal = obs.legal
        kinds = []
        if legal.can_fold:
            kinds.append(("fold", self.weights[0]))
        kinds.append(("passive", self.weights[1]))
        if legal.can_raise:
            kinds.append(("aggressive", self.weights[2]))
        names, weights = zip(*kinds)
        choice = self.rng.choices(names, weights=weights)[0]
        if choice == "fold":
            return Action.fold()
        if choice == "passive":
            return self.passive(obs)
        sizes = sorted({legal.min_to, (legal.min_to + legal.max_to) // 2, legal.max_to})
        return Action(legal.raise_type, self.rng.choice(sizes))


def preflop_score(hole: tuple[int, ...]) -> float:
    """Crude PLO starting-hand heuristic (pairs, suits, connectedness, high cards)."""
    ranks = sorted((c >> 2 for c in hole), reverse=True)
    rank_counts = Counter(ranks)
    suit_counts = Counter(c & 3 for c in hole)
    score = sum(ranks) / 4.0
    score += sum(2.0 + r / 3.0 for r, k in rank_counts.items() if k == 2)
    if max(rank_counts.values()) >= 3:
        score -= 4.0
    score += 2.0 * sum(1 for k in suit_counts.values() if k == 2)
    if max(suit_counts.values()) >= 3:
        score -= 1.0
    distinct = sorted(rank_counts)
    if len(distinct) == 4 and distinct[-1] - distinct[0] <= 4:
        score += 3.0
    elif len(distinct) >= 3 and distinct[-1] - distinct[0] <= 4:
        score += 1.5
    return score


class RuleAgent(BaseAgent):
    """Fixed rules: preflop heuristic score, postflop made-hand category with pot-odds limits."""
    name = "rule"
    version = "1"

    def __init__(self, raise_score: float = 14.0, call_score: float = 10.0) -> None:
        self.raise_score = raise_score
        self.call_score = call_score

    def params(self) -> dict:
        return {"raise_score": self.raise_score, "call_score": self.call_score}

    def act(self, obs: Observation) -> Action:
        legal = obs.legal
        if obs.street == 0:
            score = preflop_score(obs.hole_cards)
            if score >= self.raise_score and legal.can_raise:
                return self.aggressive(obs, legal.max_to)
            if score >= self.call_score and obs.to_call <= 3 * obs.big_blind:
                return self.passive(obs)
            return Action.check() if legal.can_check else Action.fold()
        category = category_of(plo_rank_reference(obs.hole_cards, obs.board))
        if category >= 4:
            return self.aggressive(obs, legal.max_to) if legal.can_raise else self.passive(obs)
        if category >= 2:
            if legal.can_check and legal.can_raise:
                return self.aggressive(obs, legal.min_to + (legal.max_to - legal.min_to) // 2)
            if obs.to_call * 2 <= obs.pot:
                return self.passive(obs)
            return Action.check() if legal.can_check else Action.fold()
        if category == 1 and (legal.can_check or obs.to_call * 3 <= obs.pot):
            return self.passive(obs)
        return Action.check() if legal.can_check else Action.fold()


AGENT_TYPES = {cls.name: cls for cls in (CallingStation, RandomAgent, RuleAgent)}


def make_agent(spec: dict) -> BaseAgent:
    """Build an agent from ``{"type": name, ...params}``."""
    from pokerlab.plo.baseline import BaselineAgent
    from pokerlab.plo.river_agent import SolverRiverAgent
    from pokerlab.plo.turn_agent import JointTurnRiverAgent
    from pokerlab.plo.blueprint_agent import BlueprintAgent

    types = {**AGENT_TYPES, BaselineAgent.name: BaselineAgent, SolverRiverAgent.name: SolverRiverAgent,
             JointTurnRiverAgent.name: JointTurnRiverAgent, BlueprintAgent.name: BlueprintAgent}
    spec = dict(spec)
    kind = spec.pop("type")
    if kind not in types:
        raise ValueError(f"unknown agent type {kind!r}; known: {sorted(types)}")
    return types[kind](**spec)


def is_aggressive(action: Action) -> bool:
    return action.type in (ActionType.BET, ActionType.RAISE)
