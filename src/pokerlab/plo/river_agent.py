"""Heads-up agent: fixed baseline policy before the river, solved strategy on the river.

At its first river decision the agent:
1. replays the public betting with placeholder cards (``pokerlab.plo.public``);
2. derives both players' river-start ranges by Bayes' rule.  The prior is uniform over the
   178,365 hands that avoid the board; each player's preflop/flop/turn actions are
   weighted by the baseline policy's category likelihoods, i.e. the opponent is assumed
   to have played baseline-v1;
3. samples ``range_samples`` draws per player from those ranges (seeded multinomial,
   counts become weights) and adds its own hand to its own range if no draw picked it;
4. solves the river subgame from the start of the river with the configured exact
   pot-fraction abstraction, then plays its hand's average-strategy probabilities.

Later river decisions follow the same tree.  If the opponent makes a bet or raise that
the abstraction does not contain, the agent re-solves from the current state:
* ranges are re-weighted by the previous solution's in-tree action probabilities, floored
  at ``river_eps``;
* the off-tree action itself does not update the ranges.

This is an unsafe, independent river solve.  It is not a safe/nested re-solve of the whole
game, and nothing here implies a PLO equilibrium.  Decisions use only the Observation.
Every decision is logged with the policy version, the range-update steps, the solve
configuration and its exploitability, and latencies.
"""
from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from pokerlab.plo.agents import BaseAgent
from pokerlab.plo.baseline import (
    CATEGORY_NAMES, BaselinePolicy, category_of_action, every_hand, hand_strength,
)
from pokerlab.plo.cards import format_cards
from pokerlab.plo.engine import RIVER, Action, ActionType, Observation
from pokerlab.plo.public import PublicReplay, replay
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile
from pokerlab.plo.subgame.instance import SubgameInstance, plo_river_instance
from pokerlab.plo.subgame.tree import DECISION

BOARD_SIZE = (0, 3, 4, 5)
SCOPE = ("preflop/flop/turn: fixed baseline policy; river: unsafe solve of the river subgame "
         "from Bayes-derived public-belief ranges (opponent modelled as baseline-v1); not a "
         "global safe re-solve and no claim of a PLO equilibrium")


@dataclass(frozen=True)
class RiverSettings:
    range_samples: int = 150
    iterations: int = 200
    algorithm: str = "dcfr"
    bet_sizes: tuple[str, ...] = ("1/3", "1/2", "2/3", "1")
    raise_sizes: tuple[str, ...] = ("1/3", "1/2", "2/3", "1")
    include_min_raise: bool = True
    include_max_raise: bool = True
    max_raises: int = 2
    river_eps: float = 1e-3
    measure_exploitability: bool = True


@dataclass
class _RiverContext:
    hand_id: int
    instance: SubgameInstance
    profile: dict
    ranges: dict                      # tree player -> (hands, weights) used by ``instance``
    path: list = field(default_factory=list)
    walked: int = 0                   # river action records already placed on the path
    own_labels: list = field(default_factory=list)   # our river labels this hand (for the log)


def posterior_log_weights(policy: BaselinePolicy, decisions, seat: int, board, candidates: np.ndarray,
                          strengths: dict | None = None, before: int = RIVER) -> tuple[np.ndarray, list[dict]]:
    """Bayes update of a uniform prior over ``candidates`` by ``seat``'s public actions on streets
    before ``before`` (default: the river).

    Each action multiplies a hand's weight by the policy's probability of that action category
    in the public context it was taken in (to call or not, raise allowed or not).
    """
    strengths = {} if strengths is None else strengths
    logw = np.zeros(len(candidates))
    steps = []
    for d in decisions:
        if d.seat != seat or d.street >= before:
            continue
        if d.street not in strengths:
            strengths[d.street] = hand_strength(d.street, tuple(board)[:BOARD_SIZE[d.street]], candidates)
        probs = policy.category_probs(d.street, d.facing_bet, d.can_raise, strengths[d.street])
        category = category_of_action(d.action)
        logw += np.log(probs[:, category])
        w = np.exp(logw - logw.max())
        steps.append({"street": d.street, "action": d.action.value, "category": CATEGORY_NAMES[category],
                      "facing_bet": d.facing_bet, "can_raise": d.can_raise,
                      "effective_hands": float(w.sum() ** 2 / (w ** 2).sum())})
    return logw, steps


def sample_ranges(posterior: dict, range_samples: int, seed_parts: tuple, me: int | None,
                  own_hand) -> tuple[dict, list[dict]]:
    """The agents' range representation (shared by the river and turn agents and by evaluations).

    ``posterior[player] = (candidates, weights)``.  ``range_samples`` draws per player from the
    normalised weights, seeded by ``[*seed_parts, player]`` so the draws never depend on the agent's
    own cards; the counts become the weights.  If no draw picked the agent's own hand it is appended
    with weight 1, the weight of one draw.  ``range_samples == 0`` keeps every candidate with positive
    weight at its posterior weight (no sampling; the k = N control).
    """
    ranges, info = {}, []
    for player in (0, 1):
        candidates, w = posterior[player]
        w = np.asarray(w, dtype=np.float64)
        if range_samples == 0:
            idx = np.flatnonzero(w > 0)
            sample, weights = candidates[idx], w[idx].copy()
        else:
            rng = np.random.default_rng([*seed_parts, player])
            draws = rng.choice(len(candidates), size=range_samples, p=w / w.sum())
            idx, counts = np.unique(draws, return_counts=True)
            sample, weights = candidates[idx], counts.astype(np.float64)
        forced = False
        if player == me:
            own = np.sort(np.asarray(own_hand))
            if not (np.sort(sample, axis=1) == own).all(axis=1).any():
                sample = np.vstack([sample, own])
                weights = np.append(weights, 1.0)
                forced = True
        ranges[player] = (sample, weights)
        info.append({"draws": range_samples if range_samples else "all (no sampling)", "unique_hands": int(len(idx)),
                     "posterior_mass_of_sampled_hands": float(w[idx].sum() / w.sum()),
                     "own_hand_added": forced, "seed": [*seed_parts, player]})
    return ranges, info


def river_spec(base: dict, ranges: dict, settings: "RiverSettings", root: dict | None = None) -> dict:
    """River subgame spec the agent solves: ``base`` gives board, big_blind, pot and stacks (OOP first)."""
    spec = {"board": base["board"], "big_blind": base["big_blind"], "pot": base["pot"], "stacks": list(base["stacks"]),
            "ranges": [{"hands": [format_cards(h) for h in ranges[p][0]], "weights": ranges[p][1].tolist()}
                       for p in (0, 1)],
            "bet_sizes": list(settings.bet_sizes), "raise_sizes": list(settings.raise_sizes),
            "include_min_raise": settings.include_min_raise, "include_max_raise": settings.include_max_raise,
            "max_raises": settings.max_raises, "min_bet": base["big_blind"], "showdown": "dense"}
    if root is not None:
        spec["root"] = root
    return spec


def solve_river(spec: dict, settings: "RiverSettings", seed: int) -> tuple[SubgameInstance, dict]:
    """The agent's solve: build the instance and return its average strategy after ``settings.iterations``."""
    instance = plo_river_instance(spec)
    solver = CFRSolver(instance, SolverConfig(algorithm=settings.algorithm, seed=seed))
    solver.run(settings.iterations)
    return instance, solver.average_profile()


def _label(record, effective_stack: int) -> str:
    """Tree label of an engine action; amounts above the effective stack are all-in equivalents."""
    if record.type is ActionType.BET:
        return f"bet:{min(record.to, effective_stack)}"
    if record.type is ActionType.RAISE:
        return f"raise:{min(record.to, effective_stack)}"
    return record.type.value


class SolverRiverAgent(BaseAgent):
    name = "river_solver"
    version = "river-solver-v1"
    depth_validation = ("preflop/flop/turn: fixed baseline rules, not trained at any depth; river: "
                        "solved per decision at that hand's actual pot and stacks, with the solve's "
                        "exploitability (within the sampled ranges and abstraction) logged")
    range_model_caveat = ("river_solver derives river ranges assuming the opponent played baseline-v1 "
                          "before the river; against any other opponent that range model is misspecified")

    def __init__(self, seed: int = 0, river: dict | None = None, policy: dict | None = None) -> None:
        self.seed = seed
        self.settings = RiverSettings(**{k: (tuple(v) if isinstance(v, list) else v)
                                         for k, v in (river or {}).items()})
        self.policy = BaselinePolicy(**(policy or {}))
        self.rng = random.Random(seed)
        self.decisions: list[dict] = []
        self._ctx: _RiverContext | None = None

    def params(self) -> dict:
        return {"seed": self.seed, "early_streets": self.policy.describe(),
                "river": asdict(self.settings), "scope": SCOPE}

    # ------------------------------------------------------------------ act
    def act(self, obs: Observation) -> Action:
        if obs.num_players != 2:
            raise ValueError("SolverRiverAgent is heads-up only")
        start = time.perf_counter()
        if obs.street < RIVER:
            probs = self.policy.own_probs(obs)
            category = self.rng.choices(range(3), weights=probs.tolist())[0]
            action = self.policy.to_action(category, obs)
            self.decisions.append({
                "hand_id": obs.hand_id, "seat": obs.seat, "street": obs.street,
                "source": self.policy.version, "action": [action.type.value, action.to],
                "category_probs": dict(zip(CATEGORY_NAMES, map(float, probs))),
                "latency_ms": {"total_decision": 1000 * (time.perf_counter() - start)}})
            return action
        return self._river(obs, start)

    def _river(self, obs: Observation, start: float) -> Action:
        rep = replay(obs)
        oop_seat = (obs.button + 1) % 2
        me = 0 if obs.seat == oop_seat else 1
        timings: dict[str, float] = {}
        records = [r for r in obs.history if r.street == RIVER]
        ctx = self._ctx if self._ctx is not None and self._ctx.hand_id == obs.hand_id else None
        log: dict = {}
        if ctx is None:
            t = time.perf_counter()
            ranges, trace = self._river_ranges(obs, rep, me, oop_seat)
            timings["ranges"] = 1000 * (time.perf_counter() - t)
            ctx = self._solve(obs, rep, oop_seat, ranges, None, timings, log)
            log["range_update"] = trace
            log["resolve_reason"] = "first river decision"
            self._ctx = ctx
        # Our own river actions were put on the path when we chose them, so only opponent
        # actions are left to place.
        for record in records[ctx.walked:]:
            if record.seat == obs.seat:
                raise AssertionError("own river action was not recorded on the solved path")
            label = _label(record, ctx.instance.tree.config.effective_stack)
            node = ctx.instance.tree.nodes[ctx.instance.tree.find(ctx.path)]
            if label in node.actions:
                ctx.path.append(label)
                ctx.walked += 1
                continue
            ranges = self._reweighted(ctx)
            labels_so_far = ctx.own_labels
            ctx = self._solve(obs, rep, oop_seat, ranges, self._root(rep, oop_seat), timings, log)
            ctx.own_labels = labels_so_far
            ctx.walked = len(records)
            log["resolve_reason"] = f"opponent action {label} is not in the abstraction"
            self._ctx = ctx
            break
        t = time.perf_counter()
        nid = ctx.instance.tree.find(ctx.path)
        node = ctx.instance.tree.nodes[nid]
        if node.kind != DECISION or node.player != me:
            raise AssertionError("solved tree is not at the agent's decision")
        i = ctx.instance.hand_index(me, obs.hole_cards)
        probs = ctx.profile[nid][i]
        label = self.rng.choices(node.actions, weights=probs.tolist())[0]
        ctx.own_labels.append(label)
        ctx.path.append(label)
        ctx.walked += 1
        action = self._engine_action(label, obs, ctx.instance.tree.config.effective_stack)
        obs.legal.validate(action)
        timings["query"] = 1000 * (time.perf_counter() - t)
        timings["total_decision"] = 1000 * (time.perf_counter() - start) - timings.get(
            "exploitability_diagnostic", 0.0)
        self.decisions.append({
            "hand_id": obs.hand_id, "seat": obs.seat, "street": RIVER, "source": "river-solver",
            "early_street_policy": self.policy.version, "label": label,
            "action": [action.type.value, action.to],
            "probabilities": dict(zip(node.actions, map(float, probs))),
            **log, "latency_ms": timings, "scope": SCOPE})
        return action

    # -------------------------------------------------------------- ranges
    def _river_ranges(self, obs: Observation, rep: PublicReplay, me: int, oop_seat: int):
        board = tuple(obs.board)
        hands = every_hand()
        candidates = hands[~np.isin(hands, np.asarray(board)).any(axis=1)]
        strengths: dict[int, np.ndarray] = {}
        ranges, trace = {}, {"prior": f"uniform over the {len(candidates):,} hands avoiding the board",
                             "model": f"{self.policy.version} category likelihoods before the river",
                             "players": []}
        posterior, steps = {}, {}
        for player in (0, 1):
            seat = oop_seat if player == 0 else 1 - oop_seat
            logw, steps[player] = posterior_log_weights(self.policy, rep.decisions, seat, board, candidates, strengths)
            posterior[player] = (candidates, np.exp(logw - logw.max()))
        ranges, info = sample_ranges(posterior, self.settings.range_samples, (self.seed, obs.hand_id), me,
                                     obs.hole_cards)
        for player in (0, 1):
            trace["players"].append({"tree_player": ["OOP", "IP"][player],
                                     "seat": oop_seat if player == 0 else 1 - oop_seat,
                                     "steps": steps[player], **info[player]})
        return ranges, trace

    def _reweighted(self, ctx: _RiverContext) -> dict:
        ranges = {p: (h, w.copy()) for p, (h, w) in ctx.ranges.items()}
        node = ctx.instance.tree.nodes[ctx.instance.tree.root]
        for label in ctx.path:
            a = node.actions.index(label)
            hands, weights = ranges[node.player]
            weights *= np.maximum(ctx.profile[node.id][:, a], self.settings.river_eps)
            node = ctx.instance.tree.nodes[node.children[a]]
        return ranges

    # --------------------------------------------------------------- solve
    @staticmethod
    def _root(rep: PublicReplay, oop_seat: int) -> dict:
        state = rep.state
        tree_seat = (oop_seat, 1 - oop_seat)
        river = [d for d in rep.decisions if d.street == RIVER]
        cap = min(rep.river_stacks)   # commitments beyond the shorter stack are returned anyway
        return {"commit": [min(state.committed_street[s], cap) for s in tree_seat],
                "actor": tree_seat.index(state.to_act), "current_bet": min(state.current_bet, cap),
                "last_increment": state.last_full_raise,
                "raises": sum(d.action is ActionType.RAISE for d in river),
                "checked": any(d.action is ActionType.CHECK and d.seat == oop_seat for d in river)}

    def _solve(self, obs, rep, oop_seat, ranges, root, timings, log) -> _RiverContext:
        s = self.settings
        stacks = [rep.river_stacks[oop_seat], rep.river_stacks[1 - oop_seat]]
        spec = river_spec({"board": format_cards(obs.board), "big_blind": obs.big_blind, "pot": rep.river_pot,
                           "stacks": stacks}, ranges, s, root)
        t = time.perf_counter()
        instance, profile = solve_river(spec, s, self.seed)
        timings["solve"] = timings.get("solve", 0.0) + 1000 * (time.perf_counter() - t)
        log["solve"] = {"algorithm": s.algorithm, "iterations": s.iterations, "pot": rep.river_pot,
                        "stacks": stacks, "abstraction": instance.tree.config.describe(),
                        "tree": instance.tree.summary(), "range_sizes": [instance.size(0), instance.size(1)]}
        if s.measure_exploitability:
            t = time.perf_counter()
            metrics = evaluate_profile(instance, profile)
            log["solve"]["exploitability_pct_pot"] = metrics["exploitability_pct_pot"]
            timings["exploitability_diagnostic"] = 1000 * (time.perf_counter() - t)
        return _RiverContext(obs.hand_id, instance, profile, ranges)

    @staticmethod
    def _engine_action(label: str, obs: Observation, effective_stack: int) -> Action:
        if label in ("check", "call", "fold"):
            return {"check": Action.check, "call": Action.call, "fold": Action.fold}[label]()
        amount = int(label.split(":")[1])
        if amount == effective_stack and amount < obs.legal.min_to:
            amount = obs.legal.min_to   # covering a short opponent: the minimum legal raise
        return Action(obs.legal.raise_type, amount)
