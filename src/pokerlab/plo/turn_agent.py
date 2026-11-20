"""Heads-up agent that plays the turn and the river from one joint turn + river solution.

Preflop and flop use the fixed baseline policy (baseline-v1, a temporary stand-in).

At its first turn decision of a hand the agent:
1. replays the public betting (``pokerlab.plo.public``) and derives both players' turn-start
   ranges by Bayes' rule from the preflop and flop actions; the prior is uniform over the hands
   avoiding the turn board and the opponent is assumed to have played baseline-v1;
2. draws ``range_samples`` seeded multinomial samples per player (counts become weights; the seed
   does not depend on the agent's cards) and adds its own hand to its own range if no draw picked it;
3. solves one joint turn + river game from the start of the turn (``subgame.turn``): the turn tree,
   all 48 river cards enumerated, and a river tree below every turn leaf, in a single CFR run;
4. walks the opponent's turn actions so far down the turn tree and plays its own hand's
   average-strategy probabilities.

On the river it reads the same joint solution at (turn leaf reached, river card, own hand); it does
not solve the river again.  Fallbacks are explicit and logged:
* opponent turn action outside the abstraction: the joint game is re-solved from the current turn
  state, ranges re-weighted by the previous joint solution's probabilities (floored at ``eps``);
* opponent river action outside the abstraction: an independent river re-solve from the current
  state (``river_agent`` machinery), ranges taken from the joint solution along the actual path.
  From then on that hand is no longer played from the joint strategy, and the log says so.

Decisions use only the Observation.  This is an unsafe solve from sampled public-belief ranges; it
does not make the full game an equilibrium and preflop/flop remain the baseline.
"""
from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from pokerlab.plo.agents import BaseAgent
from pokerlab.plo.baseline import CATEGORY_NAMES, BaselinePolicy, every_hand
from pokerlab.plo.cards import format_cards
from pokerlab.plo.engine import RIVER, TURN, Action, ActionType, Observation
from pokerlab.plo.public import PublicReplay, replay
from pokerlab.plo.river_agent import SolverRiverAgent, _label, posterior_log_weights, sample_ranges
from pokerlab.plo.subgame.cfr import SolverConfig
from pokerlab.plo.subgame.tree import DECISION, SHOWDOWN
from pokerlab.plo.subgame.turn import TurnRiverGame, TurnRiverSolver, evaluate_turn_profile, turn_river_game

SCOPE = ("preflop/flop: fixed baseline policy (temporary); turn and river: one joint turn+river solve "
         "per hand from sampled Bayes public-belief ranges (opponent modelled as baseline-v1), river "
         "read from the same solution; unsafe solve, no claim of a PLO equilibrium")
SCOPE_BLUEPRINT = ("preflop/flop: blueprint-v0 (20bb, coarse imperfect-recall abstraction; decisions outside its "
                   "tree fall back to baseline-v1, logged); turn and river: one joint turn+river solve per hand "
                   "from sampled Bayes ranges under the blueprint's likelihoods, river read from the same "
                   "solution; unsafe solve, no claim of a PLO equilibrium")


@dataclass(frozen=True)
class TurnRiverSettings:
    range_samples: int = 40
    iterations: int = 100
    algorithm: str = "dcfr"
    bet_sizes: tuple[str, ...] = ("1/3", "1/2", "2/3", "1")
    raise_sizes: tuple[str, ...] = ("1/3", "1/2", "2/3", "1")
    include_min_raise: bool = True
    include_max_raise: bool = True
    turn_max_raises: int = 1
    river_max_raises: int = 1
    showdown: str = "auto"
    workers: int = 1
    eps: float = 1e-3
    measure_exploitability: bool = True
    river_fallback_iterations: int = 200


def joint_spec(base: dict, ranges: dict, settings: TurnRiverSettings, root: dict | None = None) -> dict:
    """Turn + river game the agent solves: ``base`` gives the turn board, big_blind, pot and stacks (OOP first)."""
    spec = {"board": base["board"], "big_blind": base["big_blind"], "pot": base["pot"], "stacks": list(base["stacks"]),
            "ranges": [{"hands": [format_cards(h) for h in ranges[p][0]], "weights": ranges[p][1].tolist()}
                       for p in (0, 1)],
            "bet_sizes": list(settings.bet_sizes), "raise_sizes": list(settings.raise_sizes),
            "include_min_raise": settings.include_min_raise, "include_max_raise": settings.include_max_raise,
            "turn_max_raises": settings.turn_max_raises, "river_max_raises": settings.river_max_raises,
            "min_bet": base["big_blind"], "river_cards": "all", "showdown": settings.showdown}
    if root is not None:
        spec["root"] = root
    return spec


def solve_joint(spec: dict, settings: TurnRiverSettings, seed: int) -> tuple[TurnRiverGame, dict, int]:
    """The agent's joint solve: game, average strategy after ``settings.iterations``, worker threads used."""
    game = turn_river_game(spec)
    solver = TurnRiverSolver(game, SolverConfig(algorithm=settings.algorithm, seed=seed), workers=settings.workers)
    solver.run(settings.iterations)
    return game, solver.average_profile(), solver.workers


@dataclass
class _JointContext:
    hand_id: int
    game: TurnRiverGame
    profile: dict
    ranges: dict                          # tree player -> (hands, weights) used by ``game``
    solve: dict                           # what was solved and how (logged with every decision)
    turn_path: list = field(default_factory=list)
    turn_walked: int = 0                  # turn action records placed on ``turn_path``
    river_path: list = field(default_factory=list)
    river_walked: int = 0
    fallback: bool = False                # an independent river re-solve took over this hand


class JointTurnRiverAgent(BaseAgent):
    name = "turn_river_solver"
    version = "turn-river-joint-v1"
    depth_validation = ("preflop/flop: fixed baseline rules (temporary), not trained at any depth; "
                        "turn+river: one joint solve per hand at that hand's actual pot and stacks, with "
                        "the solve's exploitability (within the sampled ranges and abstraction) logged")
    range_model_caveat = ("turn_river_solver derives turn ranges assuming the opponent played baseline-v1 "
                          "preflop and on the flop; against any other opponent that range model is misspecified")

    def __init__(self, seed: int = 0, turn_river: dict | None = None, policy: dict | None = None,
                 early_policy: str | None = None) -> None:
        """``early_policy``: a blueprint checkpoint; then preflop/flop decisions and the turn-start range
        model come from the blueprint instead of baseline-v1."""
        self.seed = seed
        self.blueprint = None
        if early_policy is not None:
            from pokerlab.plo.blueprint import BlueprintPolicy
            self.blueprint = BlueprintPolicy.load(early_policy)
            self.early_policy_path = early_policy
            self.depth_validation = ("preflop/flop: blueprint-v0, trained at 20bb only; turn+river: one joint "
                                     "solve per hand at that hand's actual pot and stacks")
            self.range_model_caveat = ("turn ranges assume the opponent played the blueprint preflop and on "
                                       "the flop; against any other opponent that range model is misspecified")
        self.scope = SCOPE if self.blueprint is None else SCOPE_BLUEPRINT
        self.settings = TurnRiverSettings(**{k: (tuple(v) if isinstance(v, list) else v)
                                             for k, v in (turn_river or {}).items()})
        self.policy = BaselinePolicy(**(policy or {}))
        self.rng = random.Random(seed)
        self.decisions: list[dict] = []
        self._ctx: _JointContext | None = None
        self._river = SolverRiverAgent(seed=seed, policy=policy, river={
            "iterations": self.settings.river_fallback_iterations, "algorithm": self.settings.algorithm,
            "bet_sizes": list(self.settings.bet_sizes), "raise_sizes": list(self.settings.raise_sizes),
            "include_min_raise": self.settings.include_min_raise,
            "include_max_raise": self.settings.include_max_raise,
            "max_raises": self.settings.river_max_raises, "river_eps": self.settings.eps,
            "measure_exploitability": self.settings.measure_exploitability})
        self._river.rng = self.rng

    def params(self) -> dict:
        early = (self.policy.describe() if self.blueprint is None else
                 {"blueprint": self.early_policy_path, "iterations": self.blueprint.trainer.iteration,
                  "spec": self.blueprint.game.spec.describe(), "buckets": self.blueprint.buckets.describe})
        return {"seed": self.seed, "early_streets": early, "turn_river": asdict(self.settings), "scope": self.scope}

    # ------------------------------------------------------------------ act
    def act(self, obs: Observation) -> Action:
        if obs.num_players != 2:
            raise ValueError("JointTurnRiverAgent is heads-up only")
        start = time.perf_counter()
        if obs.street < TURN and self.blueprint is not None:
            from pokerlab.plo.blueprint import OutOfTree
            from pokerlab.plo.blueprint_agent import blueprint_action
            try:
                actions, probs, info = self.blueprint.probs(obs)
            except OutOfTree as exc:
                actions = None
                self._out_of_tree = (obs.hand_id, str(exc))
            if actions is None:
                probs = self.policy.own_probs(obs)
                category = self.rng.choices(range(3), weights=probs.tolist())[0]
                action = self.policy.to_action(category, obs)
                self.decisions.append({
                    "hand_id": obs.hand_id, "seat": obs.seat, "street": obs.street,
                    "source": "baseline-v1 (blueprint out of tree)", "temporary_baseline": True,
                    "reason": self._out_of_tree[1], "action": [action.type.value, action.to],
                    "category_probs": dict(zip(CATEGORY_NAMES, map(float, probs))),
                    "latency_ms": {"total_decision": 1000 * (time.perf_counter() - start)}})
                return action
            label = self.rng.choices(actions, weights=probs.tolist())[0]
            action = blueprint_action(label, obs)
            obs.legal.validate(action)
            self.decisions.append({
                "hand_id": obs.hand_id, "seat": obs.seat, "street": obs.street, "source": "blueprint-v0",
                "temporary_baseline": False, "label": label, "action": [action.type.value, action.to],
                "probabilities": dict(zip(actions, map(float, probs))), **info,
                "latency_ms": {"total_decision": 1000 * (time.perf_counter() - start)}})
            return action
        if obs.street < TURN:
            probs = self.policy.own_probs(obs)
            category = self.rng.choices(range(3), weights=probs.tolist())[0]
            action = self.policy.to_action(category, obs)
            self.decisions.append({
                "hand_id": obs.hand_id, "seat": obs.seat, "street": obs.street,
                "source": self.policy.version, "temporary_baseline": True,
                "action": [action.type.value, action.to],
                "category_probs": dict(zip(CATEGORY_NAMES, map(float, probs))),
                "latency_ms": {"total_decision": 1000 * (time.perf_counter() - start)}})
            return action
        rep = replay(obs)
        oop_seat = (obs.button + 1) % 2
        me = 0 if obs.seat == oop_seat else 1
        timings: dict[str, float] = {}
        log: dict = {"fallbacks": []}
        ctx = self._ctx if self._ctx is not None and self._ctx.hand_id == obs.hand_id else None
        if ctx is None:
            if obs.street == RIVER:            # no turn decision this hand: nothing joint to follow
                log["fallbacks"].append({"kind": "river_without_joint_solution",
                                         "reason": "the agent made no turn decision this hand"})
                return self._river_fallback_decision(obs, start, log)
            ctx = self._solve(obs, rep, oop_seat, me, None, timings, log, "first turn decision")
        if ctx.fallback:
            return self._river_fallback_decision(obs, start, log)
        ctx = self._place_turn_records(obs, rep, oop_seat, me, ctx, timings, log)
        if obs.street == TURN:
            return self._decide_turn(obs, me, ctx, start, timings, log)
        return self._decide_river(obs, rep, oop_seat, me, ctx, start, timings, log)

    # -------------------------------------------------------------- turn
    def _place_turn_records(self, obs, rep, oop_seat, me, ctx, timings, log) -> _JointContext:
        turn_records = [r for r in obs.history if r.street == TURN]
        for record in turn_records[ctx.turn_walked:]:
            if record.seat == obs.seat:
                raise AssertionError("own turn action was not recorded on the joint path")
            label = _label(record, ctx.game.effective_stack)
            node = ctx.game.turn_tree.nodes[ctx.game.turn_tree.find(ctx.turn_path)]
            if label in node.actions:
                ctx.turn_path.append(label)
                ctx.turn_walked += 1
                continue
            if obs.street != TURN:
                raise AssertionError("an off-tree turn action must be answered on the turn")
            log["fallbacks"].append({"kind": "turn_resolve", "reason": f"opponent turn action {label} is not "
                                     "in the abstraction; joint game re-solved from the current turn state",
                                     "replaces_solve": ctx.solve["id"]})
            ranges = self._reweighted_turn(ctx)
            ctx = self._solve(obs, rep, oop_seat, me, ranges, timings, log,
                              f"off-tree opponent turn action {label}", root=self._root(rep, oop_seat, TURN))
            ctx.turn_walked = len(turn_records)
            break
        return ctx

    def _decide_turn(self, obs, me, ctx, start, timings, log) -> Action:
        t = time.perf_counter()
        tree = ctx.game.turn_tree
        nid = tree.find(ctx.turn_path)
        node = tree.nodes[nid]
        if node.kind != DECISION or node.player != me:
            raise AssertionError("joint turn tree is not at the agent's decision")
        i = self._hand_index(ctx.game, me, obs.hole_cards)
        probs = ctx.profile["turn"][nid][i]
        label = self.rng.choices(node.actions, weights=probs.tolist())[0]
        ctx.turn_path.append(label)
        ctx.turn_walked += 1
        action = SolverRiverAgent._engine_action(label, obs, ctx.game.effective_stack)
        obs.legal.validate(action)
        timings["query"] = 1000 * (time.perf_counter() - t)
        return self._record(obs, ctx, "joint-turn-river", label, action, node.actions, probs, start, timings, log,
                            {"street": "turn", "turn_path": list(ctx.turn_path[:-1]), "hand_index": i})

    # ------------------------------------------------------------- river
    def _decide_river(self, obs, rep, oop_seat, me, ctx, start, timings, log) -> Action:
        game = ctx.game
        leaf_id = game.turn_tree.find(ctx.turn_path)
        if game.turn_tree.nodes[leaf_id].kind != SHOWDOWN or game.leaves[leaf_id].tree is None:
            raise AssertionError("turn betting did not end at a joint river leaf")
        leaf = game.leaves[leaf_id]
        k = game.card_index(obs.board[4])
        river_records = [r for r in obs.history if r.street == RIVER]
        for record in river_records[ctx.river_walked:]:
            if record.seat == obs.seat:
                raise AssertionError("own river action was not recorded on the joint path")
            label = _label(record, leaf.tree.config.effective_stack)
            node = leaf.tree.nodes[leaf.tree.find(ctx.river_path)]
            if label in node.actions:
                ctx.river_path.append(label)
                ctx.river_walked += 1
                continue
            log["fallbacks"].append({"kind": "river_resolve", "reason": f"opponent river action {label} is not "
                                     "in the abstraction; independent river re-solve from the current state, "
                                     "ranges from the joint solution along the actual path; the joint strategy "
                                     "is not used for the rest of this hand"})
            ranges = self._joint_ranges_at_river(ctx, leaf_id, k)
            river_log: dict = {}
            river_ctx = self._river._solve(obs, rep, oop_seat, ranges, SolverRiverAgent._root(rep, oop_seat),
                                           timings, river_log)
            river_ctx.walked = len(river_records)
            self._river._ctx = river_ctx
            ctx.fallback = True
            log["river_resolve"] = river_log
            return self._river_fallback_decision(obs, start, log, timings)
        t = time.perf_counter()
        rid = leaf.tree.find(ctx.river_path)
        node = leaf.tree.nodes[rid]
        if node.kind != DECISION or node.player != me:
            raise AssertionError("joint river tree is not at the agent's decision")
        i = self._hand_index(game, me, obs.hole_cards)
        probs = ctx.profile["river"][(leaf_id, rid)][k, i]
        label = self.rng.choices(node.actions, weights=probs.tolist())[0]
        ctx.river_path.append(label)
        ctx.river_walked += 1
        action = SolverRiverAgent._engine_action(label, obs, leaf.tree.config.effective_stack)
        obs.legal.validate(action)
        timings["query"] = 1000 * (time.perf_counter() - t)
        return self._record(obs, ctx, "joint-turn-river", label, action, node.actions, probs, start, timings, log,
                            {"street": "river", "turn_path": list(ctx.turn_path), "river_card": format_cards([obs.board[4]]),
                             "river_card_index": int(k), "river_path": list(ctx.river_path[:-1]), "hand_index": i})

    def _river_fallback_decision(self, obs, start, log, timings=None) -> Action:
        before = len(self._river.decisions)
        action = self._river.act(obs)
        record = self._river.decisions[before] if len(self._river.decisions) > before else {}
        record.update({"source": "river-fallback (independent river solve)", "joint_strategy_in_force": False,
                       "fallbacks": log["fallbacks"], "early_street_policy": self.policy.version,
                       "agent": self.name, "scope": self.scope})
        if "river_resolve" in log:
            record["river_resolve"] = log["river_resolve"]
        if timings:
            record.setdefault("latency_ms", {}).update({f"joint_{k}": v for k, v in timings.items()})
        self.decisions.append(record)
        return action

    # -------------------------------------------------------------- ranges
    def _turn_ranges(self, obs: Observation, rep: PublicReplay, me: int, oop_seat: int):
        board = tuple(obs.board[:4])
        hands = every_hand()
        candidates = hands[~np.isin(hands, np.asarray(board)).any(axis=1)]
        strengths: dict[int, np.ndarray] = {}
        model = (f"{self.policy.version} category likelihoods, preflop and flop actions" if self.blueprint is None
                 else "blueprint-v0 average-strategy likelihoods of the preflop and flop actions (bucketed hands)")
        ranges, trace = {}, {"prior": f"uniform over the {len(candidates):,} hands avoiding the turn board",
                             "model": model, "players": []}
        posterior, steps = {}, {}
        for player in (0, 1):
            seat = oop_seat if player == 0 else 1 - oop_seat
            logw = None
            if self.blueprint is not None:
                from pokerlab.plo.blueprint import OutOfTree
                try:
                    logw, steps[player] = self.blueprint.log_likelihood(obs.history, obs.button, seat, board,
                                                                        candidates, before=TURN)
                except OutOfTree as exc:               # line outside the blueprint tree: baseline model, logged
                    trace["model"] = f"baseline-v1 category likelihoods (blueprint out of tree: {exc})"
            if logw is None:
                logw, steps[player] = posterior_log_weights(self.policy, rep.decisions, seat, board, candidates,
                                                            strengths, before=TURN)
            w = np.exp(logw - logw.max())
            posterior[player] = (candidates, w / w.sum())
        ranges, info = sample_ranges(posterior, self.settings.range_samples, (self.seed, obs.hand_id), me,
                                     obs.hole_cards)
        for player in (0, 1):
            trace["players"].append({"tree_player": ["OOP", "IP"][player],
                                     "seat": oop_seat if player == 0 else 1 - oop_seat,
                                     "steps": steps[player], **info[player]})
        return ranges, trace

    def _reweighted_turn(self, ctx: _JointContext) -> dict:
        ranges = {p: (h, w.copy()) for p, (h, w) in ctx.ranges.items()}
        tree = ctx.game.turn_tree
        node = tree.nodes[tree.root]
        for label in ctx.turn_path:
            a = node.actions.index(label)
            ranges[node.player][1][:] *= np.maximum(ctx.profile["turn"][node.id][:, a], self.settings.eps)
            node = tree.nodes[node.children[a]]
        return ranges

    def _joint_ranges_at_river(self, ctx: _JointContext, leaf_id: int, k: int) -> dict:
        """Ranges implied by the joint solution along the actual turn and river path (floored)."""
        game = ctx.game
        ranges = self._reweighted_turn(ctx)
        tree = game.leaves[leaf_id].tree
        node = tree.nodes[tree.root]
        for label in ctx.river_path:
            a = node.actions.index(label)
            probs = ctx.profile["river"][(leaf_id, node.id)][k, :, a]
            ranges[node.player][1][:] *= np.maximum(probs, self.settings.eps)
            node = tree.nodes[node.children[a]]
        out = {}
        for p in (0, 1):
            hands, weights = ranges[p]
            live = game.masks[p][k] > 0                # drop hands holding the river card
            out[p] = (hands[live], weights[live])
        return out

    # --------------------------------------------------------------- solve
    @staticmethod
    def _root(rep: PublicReplay, oop_seat: int, street: int) -> dict:
        state = rep.state
        tree_seat = (oop_seat, 1 - oop_seat)
        actions = [d for d in rep.decisions if d.street == street]
        cap = min(rep.street_start[street][1])
        return {"commit": [min(state.committed_street[s], cap) for s in tree_seat],
                "actor": tree_seat.index(state.to_act), "current_bet": min(state.current_bet, cap),
                "last_increment": state.last_full_raise,
                "raises": sum(d.action is ActionType.RAISE for d in actions),
                "checked": any(d.action is ActionType.CHECK and d.seat == oop_seat for d in actions)}

    def _solve(self, obs, rep, oop_seat, me, ranges, timings, log, reason, root=None) -> _JointContext:
        s = self.settings
        trace = None
        if ranges is None:
            t = time.perf_counter()
            ranges, trace = self._turn_ranges(obs, rep, me, oop_seat)
            timings["ranges"] = timings.get("ranges", 0.0) + 1000 * (time.perf_counter() - t)
        pot, stacks_by_seat = rep.street_start[TURN]
        stacks = [stacks_by_seat[oop_seat], stacks_by_seat[1 - oop_seat]]
        spec = joint_spec({"board": format_cards(obs.board[:4]), "big_blind": obs.big_blind, "pot": pot,
                           "stacks": stacks}, ranges, s, root)
        t = time.perf_counter()
        game, profile, workers = solve_joint(spec, s, self.seed)
        timings["solve"] = timings.get("solve", 0.0) + 1000 * (time.perf_counter() - t)
        solve = {"reason": reason, "id": f"{game.fingerprint[:16]}@{s.iterations}", "fingerprint": game.fingerprint,
                 "algorithm": s.algorithm, "iterations": s.iterations, "workers": workers,
                 "showdown": game.description["showdown"], "pot": pot, "stacks": stacks,
                 "abstraction": game.description["abstraction"], "turn_root": spec.get("root"),
                 "nodes": game.description["nodes"], "range_sizes": [game.size(0), game.size(1)],
                 "river_cards": game.description["river_cards"], "solved_at_hand": obs.hand_id}
        if trace is not None:
            solve["range_update"] = trace
        if s.measure_exploitability:
            t = time.perf_counter()
            metrics = evaluate_turn_profile(game, profile)
            solve["exploitability_pct_pot_in_sampled_game"] = metrics["exploitability_pct_pot"]
            timings["exploitability_diagnostic"] = timings.get("exploitability_diagnostic", 0.0) + \
                1000 * (time.perf_counter() - t)
        log.setdefault("new_solves", []).append(solve)
        ctx = _JointContext(obs.hand_id, game, profile, ranges, solve)
        self._ctx = ctx
        return ctx

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _hand_index(game: TurnRiverGame, player: int, hole_cards) -> int:
        own = np.sort(np.asarray(hole_cards))
        hits = np.flatnonzero((np.sort(game.hands[player], axis=1) == own).all(axis=1))
        if len(hits) != 1:
            raise AssertionError("own hand is not in the solved range")
        return int(hits[0])

    def _record(self, obs, ctx, source, label, action, actions, probs, start, timings, log, lookup) -> Action:
        timings["total_decision"] = 1000 * (time.perf_counter() - start) - timings.get("exploitability_diagnostic", 0.0)
        self.decisions.append({
            "hand_id": obs.hand_id, "seat": obs.seat, "street": obs.street, "source": source,
            "joint_strategy_in_force": True, "early_street_policy": self.policy.version,
            "joint_solve_id": ctx.solve["id"], "joint_solves_this_decision": log.get("new_solves", []),
            "strategy_lookup": lookup, "label": label, "action": [action.type.value, action.to],
            "probabilities": dict(zip(actions, map(float, probs))), "fallbacks": log["fallbacks"],
            "latency_ms": timings, "scope": self.scope})
        return action
