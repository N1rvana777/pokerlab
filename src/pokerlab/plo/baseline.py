"""Fixed, reproducible baseline policy for heads-up play ("baseline-v1").

It is used in two places:
* agents play preflop, flop and turn with it (``BaselineAgent`` also plays the river with it);
* the river range derivation uses it as the model of how a player acted on earlier streets.

The policy is deliberately simple and is not tuned for strength.  Action categories are
FOLD (only when facing a bet), PASSIVE (check/call) and AGGRESSIVE (bet/raise).  For a hand
with strength s in [0, 1] and temperature T:

    facing a bet:    logit(fold) = (t_fold - s)/T, logit(passive) = 0, logit(aggr) = (s - t_raise)/T
    nothing to call: logit(passive) = 0, logit(aggr) = (s - t_bet)/T

Unavailable categories get probability 0.  Available ones are floored at ``eps`` and
renormalised, so a Bayes update with this model never empties a range.  An aggressive
action uses the 2/3-pot size of the shared pot-limit formula, clamped to the legal window.
The category likelihood ignores the bet size, so an observed amount does not affect the
update.  That is a modelling simplification.

Strength:
* preflop: percentile of a crude preflop heuristic (``agents.preflop_score``) among all
  270,725 hands;
* flop/turn/river: percentile of the current made-hand rank among all hands avoiding the
  board.  Draws are ignored.

Everything is vectorised over hands, so the same function gives an agent's own action
probabilities and the likelihood of a public action for every possible opponent hand.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from fractions import Fraction
from functools import lru_cache
from typing import Sequence

import numpy as np

from pokerlab.plo.agents import BaseAgent
from pokerlab.plo.betting import fraction_raise_to
from pokerlab.plo.cards import all_hands
from pokerlab.plo.engine import Action, ActionType, Observation, PREFLOP
from pokerlab.plo.evaluator import plo_rank_batch

FOLD, PASSIVE, AGGRESSIVE = 0, 1, 2
CATEGORY_NAMES = ("fold", "passive", "aggressive")


def category_of_action(action_type: ActionType) -> int:
    if action_type is ActionType.FOLD:
        return FOLD
    if action_type in (ActionType.CHECK, ActionType.CALL):
        return PASSIVE
    return AGGRESSIVE


@lru_cache(maxsize=1)
def every_hand() -> np.ndarray:
    """All 270,725 four-card hands (int16, rows ascending)."""
    return all_hands(4)


def preflop_scores(hands: np.ndarray) -> np.ndarray:
    """Vectorised ``pokerlab.plo.agents.preflop_score``."""
    hands = np.asarray(hands, dtype=np.int64)
    ranks = hands >> 2
    suits = hands & 3
    rank_counts = (ranks[:, :, None] == np.arange(13)).sum(axis=1)
    suit_counts = (suits[:, :, None] == np.arange(4)).sum(axis=1)
    score = ranks.sum(axis=1) / 4.0
    score += ((rank_counts == 2) * (2.0 + np.arange(13) / 3.0)).sum(axis=1)
    score -= 4.0 * (rank_counts.max(axis=1) >= 3)
    score += 2.0 * (suit_counts == 2).sum(axis=1)
    score -= 1.0 * (suit_counts.max(axis=1) >= 3)
    present = rank_counts > 0
    distinct = present.sum(axis=1)
    top = 12 - np.argmax(present[:, ::-1], axis=1)
    bottom = np.argmax(present, axis=1)
    span = top - bottom
    score += np.where((distinct == 4) & (span <= 4), 3.0,
                      np.where((distinct >= 3) & (span <= 4), 1.5, 0.0))
    return score


@lru_cache(maxsize=1)
def _sorted_preflop_scores() -> np.ndarray:
    return np.sort(preflop_scores(every_hand()))


@lru_cache(maxsize=64)
def _sorted_board_ranks(board: tuple[int, ...]) -> np.ndarray:
    hands = every_hand()
    live = hands[~np.isin(hands, np.asarray(board)).any(axis=1)]
    return np.sort(plo_rank_batch(live, board))


def _percentile(sorted_values: np.ndarray, values: np.ndarray) -> np.ndarray:
    left = np.searchsorted(sorted_values, values, side="left")
    right = np.searchsorted(sorted_values, values, side="right")
    return (left + right) / (2.0 * len(sorted_values))


def hand_strength(street: int, board: Sequence[int], hands: np.ndarray) -> np.ndarray:
    hands = np.asarray(hands)
    if street == PREFLOP:
        return _percentile(_sorted_preflop_scores(), preflop_scores(hands))
    key = tuple(sorted(int(c) for c in board))
    return _percentile(_sorted_board_ranks(key), plo_rank_batch(hands, key))


@dataclass(frozen=True)
class BaselinePolicy:
    version: str = "baseline-v1"
    temperature: float = 0.08
    preflop_fold: float = 0.35
    preflop_raise: float = 0.80
    preflop_open: float = 0.75       # big blind with nothing to call: raise threshold
    postflop_fold: float = 0.45
    postflop_raise: float = 0.90
    postflop_bet: float = 0.70
    size_fraction: str = "2/3"
    eps: float = 0.01

    def describe(self) -> dict:
        return asdict(self)

    def category_probs(self, street: int, facing_bet: bool, can_raise: bool,
                       strength: np.ndarray) -> np.ndarray:
        s = np.asarray(strength, dtype=np.float64)
        pre = street == PREFLOP
        logits = np.zeros((len(s), 3))
        available = np.array([facing_bet, True, can_raise])
        if facing_bet:
            logits[:, FOLD] = ((self.preflop_fold if pre else self.postflop_fold) - s) / self.temperature
            logits[:, AGGRESSIVE] = (s - (self.preflop_raise if pre else self.postflop_raise)) / self.temperature
        else:
            logits[:, AGGRESSIVE] = (s - (self.preflop_open if pre else self.postflop_bet)) / self.temperature
        logits[:, ~available] = -np.inf
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        probs = np.where(available, np.maximum(probs, self.eps), 0.0)
        return probs / probs.sum(axis=1, keepdims=True)

    def own_probs(self, obs: Observation) -> np.ndarray:
        s = hand_strength(obs.street, obs.board, np.array([obs.hole_cards]))
        return self.category_probs(obs.street, obs.to_call > 0, obs.legal.can_raise, s)[0]

    def to_action(self, category: int, obs: Observation) -> Action:
        legal = obs.legal
        if category == FOLD:
            return Action.fold()
        if category == PASSIVE:
            return Action.check() if legal.can_check else Action.call()
        to = fraction_raise_to(obs.limit_pot, obs.committed_street[obs.seat], obs.to_call,
                               Fraction(self.size_fraction))
        return Action(legal.raise_type, max(legal.min_to, min(legal.max_to, to)))


class BaselineAgent(BaseAgent):
    """Plays every street with ``BaselinePolicy`` (category sampled with its own seeded RNG)."""
    name = "baseline"
    version = "baseline-v1"

    def __init__(self, seed: int = 0, **policy) -> None:
        self.seed = seed
        self.policy = BaselinePolicy(**policy)
        self.version = self.policy.version
        self.rng = random.Random(seed)

    def params(self) -> dict:
        return {"seed": self.seed, "policy": self.policy.describe()}

    def act(self, obs: Observation) -> Action:
        probs = self.policy.own_probs(obs)
        category = self.rng.choices(range(3), weights=probs.tolist())[0]
        return self.policy.to_action(category, obs)
