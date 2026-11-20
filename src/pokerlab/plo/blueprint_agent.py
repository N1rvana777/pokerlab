"""Heads-up agent that plays every street from a trained blueprint (``pokerlab.plo.blueprint``).

The public history is walked down the blueprint tree; opponent sizes outside the tree are translated
to the nearest in-tree size of the same kind (logged).  The hand's bucket on the current street selects
a row of the average strategy.  The blueprint is trained at one effective stack; other depths are
played with translated sizes and are not validated.
"""
from __future__ import annotations

import random
import time

from pokerlab.plo.agents import BaseAgent
from pokerlab.plo.baseline import CATEGORY_NAMES, BaselinePolicy
from pokerlab.plo.blueprint import BlueprintPolicy, OutOfTree
from pokerlab.plo.engine import Action, ActionType, Observation


def blueprint_action(label: str, obs: Observation) -> Action:
    """Engine action for a blueprint label, adjusted only where the real legal set differs."""
    legal = obs.legal
    if label == "fold":
        return Action.fold() if not legal.can_check else Action.check()
    if label in ("check", "call"):
        return Action.check() if legal.can_check else Action.call()
    if not legal.can_raise:
        return Action.check() if legal.can_check else Action.call()
    amount = min(max(int(label.split(":")[1]), legal.min_to), legal.max_to)
    return Action(legal.raise_type, amount)


class BlueprintAgent(BaseAgent):
    name = "blueprint_v0"
    version = "blueprint-v0"
    depth_validation = ("all streets from the blueprint, trained at its single effective stack only; other "
                        "depths are played with translated sizes and are not validated")
    range_model_caveat = "no opponent model: the blueprint is played as trained"

    def __init__(self, seed: int = 0, checkpoint: str | None = None) -> None:
        if checkpoint is None:
            raise ValueError("blueprint_v0 needs a trained blueprint checkpoint")
        self.seed, self.checkpoint = seed, checkpoint
        self.policy = BlueprintPolicy.load(checkpoint)
        self.fallback = BaselinePolicy()
        self.rng = random.Random(seed)
        self.decisions: list[dict] = []

    def params(self) -> dict:
        return {"seed": self.seed, "checkpoint": self.checkpoint, "blueprint": self.policy.game.spec.describe(),
                "buckets": self.policy.buckets.describe, "iterations": self.policy.trainer.iteration}

    def act(self, obs: Observation) -> Action:
        if obs.num_players != 2:
            raise ValueError("BlueprintAgent is heads-up only")
        start = time.perf_counter()
        try:
            actions, probs, info = self.policy.probs(obs)
        except OutOfTree as exc:                       # the hand left the blueprint's tree: logged fallback
            p = self.fallback.own_probs(obs)
            category = self.rng.choices(range(3), weights=p.tolist())[0]
            action = self.fallback.to_action(category, obs)
            self.decisions.append({"hand_id": obs.hand_id, "seat": obs.seat, "street": obs.street,
                                   "source": "baseline-v1 (blueprint out of tree)", "reason": str(exc),
                                   "action": [action.type.value, action.to],
                                   "category_probs": dict(zip(CATEGORY_NAMES, map(float, p))),
                                   "latency_ms": {"total_decision": 1000 * (time.perf_counter() - start)}})
            return action
        label = self.rng.choices(actions, weights=probs.tolist())[0]
        action = blueprint_action(label, obs)
        obs.legal.validate(action)
        self.decisions.append({"hand_id": obs.hand_id, "seat": obs.seat, "street": obs.street,
                               "source": self.version, "label": label, "action": [action.type.value, action.to],
                               "probabilities": dict(zip(actions, map(float, probs))), **info,
                               "stack_matches_blueprint": min(obs.starting_stacks) == self.policy.game.spec.stack,
                               "latency_ms": {"total_decision": 1000 * (time.perf_counter() - start)}})
        return action
