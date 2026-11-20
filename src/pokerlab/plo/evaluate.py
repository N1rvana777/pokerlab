"""Independent evaluation entry points.

* ``evaluate_match``: agents play the full PLO4 engine.  ``format="duplicate"``
  (fixed-root stacks only) replays each deal with the agents rotated through
  every seat so card luck largely cancels; ``format="session"`` runs one
  session in reset or carry mode.  Results are linear net chips, reported as
  bb/100 with standard errors from independent blocks.
* ``evaluate_river``: a solved HU river subgame is checked exactly
  (exploitability, optional LP value) and scored against fixed subgame bots.

Beating random or rule bots is a functional / local-capability check only.
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np

from pokerlab.plo.agents import make_agent
from pokerlab.plo.engine import RakeRule, TableRules, deal_hand
from pokerlab.plo.resources import Meter, environment
from pokerlab.plo.session import SessionConfig, hand_record, hand_seed, play_hand, run_session
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile, response_value
from pokerlab.plo.subgame.instance import SubgameInstance, plo_river_instance
from pokerlab.plo.subgame.reference import solve_sequence_form
from pokerlab.plo.subgame.tree import DECISION

UNITS = ("bb/100 = mean linear net chips per hand / big blind x 100 (mbb/hand = 10 x bb/100); "
         "se = standard error, ci95 = normal 95% interval, sd_block = standard deviation of block "
         "totals; rake only if rules.rake is set (default none)")


def rules_from_config(cfg: dict) -> TableRules:
    r = dict(cfg.get("rules", {}))
    rake = r.pop("rake", None)
    return TableRules(small_blind=int(r.get("small_blind", 50)), big_blind=int(r.get("big_blind", 100)),
                      ante=int(r.get("ante", 0)), rake=RakeRule(**rake) if rake else None,
                      antes_count_for_pot_limit=bool(r.get("antes_count_for_pot_limit", True)))


def stacks_from_config(cfg: dict, big_blind: int) -> tuple[int, ...]:
    if "starting_stacks" in cfg:
        stacks = [int(s) for s in cfg["starting_stacks"]]
    elif "starting_stacks_bb" in cfg:
        stacks = [int(round(s * big_blind)) for s in cfg["starting_stacks_bb"]]
    else:
        stacks = [int(round(cfg.get("stack_bb", 100) * big_blind))] * int(cfg["players"])
    if "players" in cfg and len(stacks) != int(cfg["players"]):
        raise ValueError("players does not match the number of starting stacks")
    return tuple(stacks)


def block_summary(blocks: np.ndarray, hands_per_block: int, big_blind: int) -> dict:
    """bb/100 with a standard error from independent block totals."""
    blocks = np.asarray(blocks, dtype=np.float64)
    hands = len(blocks) * hands_per_block
    mean = blocks.sum() / hands if hands else float("nan")
    se = (blocks.std(ddof=1) / math.sqrt(len(blocks)) / hands_per_block
          if len(blocks) > 1 else float("nan"))
    scale = 100.0 / big_blind
    return {"hands": int(hands), "blocks": int(len(blocks)), "net_chips": float(blocks.sum()),
            "bb_per_100": mean * scale, "se_bb_per_100": se * scale,
            "ci95_bb_per_100": [(mean - 1.96 * se) * scale, (mean + 1.96 * se) * scale],
            "mbb_per_hand": mean * 1000.0 / big_blind,
            "sd_block_chips": float(blocks.std(ddof=1)) if len(blocks) > 1 else float("nan")}


def run_duplicate(rules: TableRules, stacks: tuple[int, ...], agent_specs: list[dict], deals: int,
                  seed: int, on_hand: Callable[[dict], None] | None = None,
                  on_decisions: Callable[[int, int, list], None] | None = None) -> np.ndarray:
    """Net chips per (deal, agent).

    Each rotation r is a separate match played by fresh agents built from ``agent_specs``, so no
    agent sees a deal, its board or its showdown before playing it again.  For deal d the base
    seating is a seeded random permutation, shifted by r, so every agent plays every seat's cards
    once per deal while the agents' relative seat order varies from deal to deal.
    ``on_decisions(agent, rotation, records)`` receives the decision logs of agents that keep one.
    """
    n = len(stacks)
    blocks = np.zeros((deals, n))
    seatings = [random.Random(hand_seed(seed + 1, d)).sample(range(n), n) for d in range(deals)]
    for r in range(n):
        agents = [make_agent(spec) for spec in agent_specs]
        for d in range(deals):
            seat_agent = [seatings[d][(seat - r) % n] for seat in range(n)]
            state = deal_hand(rules, stacks, d % n, random.Random(hand_seed(seed, d)), hand_id=d)
            result = play_hand(state, [agents[a] for a in seat_agent])
            summary = state.public_summary()
            for seat, a in enumerate(seat_agent):
                blocks[d, a] += result.net[seat]
                agents[a].end_hand(summary, seat, tuple(seat_agent))
            if on_hand is not None:
                on_hand(hand_record(state, seat_agent) | {"rotation": r})
        if on_decisions is not None:
            for a, agent in enumerate(agents):
                if getattr(agent, "decisions", None):
                    on_decisions(a, r, agent.decisions)
    return blocks


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    v = np.asarray(values, dtype=np.float64)
    return {"n": int(len(v)), "mean": float(v.mean()), "median": float(np.median(v)),
            "p95": float(np.percentile(v, 95)), "max": float(v.max())}


def _is_fallback(record: dict) -> bool:
    return str(record["source"]).startswith("river-fallback")


def summarize_decisions(records: list[dict]) -> dict:
    """Counts by policy source, solve diagnostics and decision latencies."""
    river = [r for r in records if r["source"] == "river-solver"]
    solves = [r for r in river if "solve" in r]
    joint = [r for r in records if r["source"] == "joint-turn-river"]
    fallback = [r for r in records if _is_fallback(r)]
    early = [r for r in records if r["source"] not in ("river-solver", "joint-turn-river") and not _is_fallback(r)]
    out = {
        "decisions_by_source": dict(Counter(r["source"] for r in records)),
        "river_solves": len(solves),
        "resolve_reasons": dict(Counter(r.get("resolve_reason") for r in solves)),
        "river_decision_latency_ms": _stats([r["latency_ms"]["total_decision"] for r in river]),
        "river_solve_latency_ms": _stats([r["latency_ms"]["solve"] for r in solves]),
        "river_range_latency_ms": _stats([r["latency_ms"]["ranges"] for r in solves
                                          if "ranges" in r["latency_ms"]]),
        "solve_exploitability_pct_pot": _stats([r["solve"]["exploitability_pct_pot"] for r in solves
                                                if "exploitability_pct_pot" in r["solve"]]),
        "early_street_latency_ms": _stats([r["latency_ms"]["total_decision"] for r in early]),
    }
    if joint or fallback:
        joint_solves = [s for r in joint for s in r.get("joint_solves_this_decision", [])]
        out["joint_turn_river"] = {
            "decisions_by_street": dict(Counter({2: "turn", 3: "river"}[r["street"]] for r in joint)),
            "joint_solves": len(joint_solves),
            "solve_reasons": dict(Counter("off-tree turn action" if s["reason"].startswith("off-tree")
                                          else s["reason"] for s in joint_solves)),
            "river_decisions_read_from_the_turn_solve": sum(1 for r in joint if r["street"] == 3
                                                            and not r.get("joint_solves_this_decision")),
            "fallback_decisions": len(fallback),
            "fallback_kinds": dict(Counter(f["kind"] for r in joint + fallback for f in r.get("fallbacks", []))),
            "decision_latency_ms": _stats([r["latency_ms"]["total_decision"] for r in joint]),
            "solve_latency_ms": _stats([r["latency_ms"]["solve"] for r in joint if "solve" in r["latency_ms"]]),
            "solve_exploitability_pct_pot_in_sampled_game": _stats(
                [s["exploitability_pct_pot_in_sampled_game"] for s in joint_solves
                 if "exploitability_pct_pot_in_sampled_game" in s]),
            "range_sizes_per_solve": [s["range_sizes"] for s in joint_solves],
        }
    return out


def evaluate_match(cfg: dict, on_hand: Callable[[dict], None] | None = None,
                   on_decision: Callable[[dict], None] | None = None) -> dict:
    rules = rules_from_config(cfg)
    stacks = stacks_from_config(cfg, rules.big_blind)
    n = len(stacks)
    agents = [make_agent(spec) for spec in cfg["agents"]]
    if len(agents) != n:
        raise ValueError("need one agent spec per player")
    fmt = cfg.get("format", "duplicate")
    mode = cfg.get("stack_mode", "reset")
    seed = int(cfg.get("seed", 0))
    caveats = ["Opponents are fixed baseline bots; results are functional checks, "
               "not evidence of professional strength, GTO play or real profit."]
    decisions: dict[int, list] = {}

    def collect(agent: int, rotation: int, records: list) -> None:
        for record in records:
            record = {"agent": agent, "rotation": rotation, **record}
            decisions.setdefault(agent, []).append(record)
            if on_decision is not None:
                on_decision(record)

    with Meter() as meter:
        if fmt == "duplicate":
            if mode != "reset":
                raise ValueError("duplicate format needs stack_mode='reset' (fixed root)")
            deals = int(cfg.get("deals", 1000))
            blocks = run_duplicate(rules, stacks, cfg["agents"], deals, seed, on_hand, collect)
            results = [block_summary(blocks[:, a], n, rules.big_blind) for a in range(n)]
            se_method = ("block = one deal played once in every seat rotation; each rotation is a "
                         "separate match with fresh agents; exact for memoryless agents, "
                         "approximate if agents adapt within a rotation")
            hands_played = deals * n
            extra = {"deals": deals}
        elif fmt == "session":
            session = run_session(SessionConfig(
                rules, stacks, mode, cfg.get("bust_policy", "rebuy"), int(cfg.get("hands", 1000)),
                seed, int(cfg.get("button_start", 0))), agents, on_hand)
            block = n if mode == "reset" else int(cfg.get("batch_hands", 100))
            results = []
            for lg in session.ledgers:
                nets = np.asarray(lg.hand_nets, dtype=np.float64)
                k = len(nets) // block
                summary = block_summary(nets[:k * block].reshape(k, block).sum(axis=1), block,
                                        rules.big_blind) if k else {"hands": len(nets)}
                summary.update({"hands_total": len(nets), "rebuys": lg.rebuys,
                                "rebuy_chips": lg.rebuy_chips, "final_stack": lg.stack,
                                "active_at_end": lg.active})
                results.append(summary)
            se_method = ("block = one orbit (button visits every seat)" if mode == "reset" else
                         f"batch means over {block}-hand batches; approximate because carried "
                         "stacks make hands dependent")
            hands_played = session.hands_played
            extra = {"stop_reason": session.stop_reason, "rake_total": session.rake}
            if mode == "carry":
                caveats.append("Carry mode: results depend on stack trajectories and bust policy.")
        else:
            raise ValueError("format must be 'duplicate' or 'session'")
    if fmt == "session":
        for a, agent in enumerate(agents):
            if getattr(agent, "decisions", None):
                collect(a, 0, agent.decisions)
    for a, (r, agent) in enumerate(zip(results, agents)):
        r["agent"] = agent.describe()
        if a in decisions:
            r["decision_summary"] = summarize_decisions(decisions[a])
        if getattr(agent, "range_model_caveat", None):
            caveats.append(agent.range_model_caveat)
    net_total = sum(r.get("net_chips", 0.0) for r in results)
    return {
        "schema": "pokerlab.plo.match-report/1",
        "rules": rules.describe(), "players": n,
        "starting_stacks_chips": list(stacks),
        "starting_stacks_bb": [s / rules.big_blind for s in stacks],
        "stack_mode": mode, "bust_policy": cfg.get("bust_policy", "rebuy") if mode == "carry" else None,
        "format": fmt, "seed": seed, "hands_played": hands_played, **extra,
        "depth": {
            "starting_stacks_bb": [s / rules.big_blind for s in stacks],
            "environment_support": ("engine and session accept any positive integer stack for 2-8 "
                                    "players in reset or carry mode; this run used the stacks above"),
            "strategy_trained_or_validated_at": [agent.describe()["depth_validation"] for agent in agents],
        },
        "units": UNITS, "se_method": se_method, "results": results,
        "checks": {"engine_chip_conservation": "asserted at every settlement",
                   "sum_of_block_nets_chips": net_total},
        "resources": meter.report(), "environment": environment(), "caveats": caveats,
    }


# ----------------------------------------------------------------- river bots
def bot_profile(inst: SubgameInstance, kind: str, player: int) -> dict[int, np.ndarray]:
    """Fixed strategies on the subgame tree (same action for every hand)."""
    profile = {}
    for nid in inst.tree.decision_nodes(player):
        node = inst.tree.nodes[nid]
        probs = np.zeros(len(node.actions))
        aggressive = [k for k, a in enumerate(node.actions) if a.startswith(("bet:", "raise:"))]
        if kind == "uniform":
            probs[:] = 1.0 / len(probs)
        elif kind == "check_call":
            probs[node.actions.index("check" if "check" in node.actions else "call")] = 1.0
        elif kind == "aggressive":
            target = aggressive[-1] if aggressive else node.actions.index(
                "call" if "call" in node.actions else "check")
            probs[target] = 1.0
        elif kind == "check_fold":
            probs[node.actions.index("check" if "check" in node.actions else "fold")] = 1.0
        else:
            raise ValueError(f"unknown subgame bot {kind!r}")
        profile[nid] = np.tile(probs, (inst.size(player), 1))
    return profile


def evaluate_river(inst: SubgameInstance, solver: CFRSolver, opponents=("check_call", "uniform",
                                                                        "aggressive", "check_fold"),
                   lp_limit: int = 12) -> dict:
    profile = solver.average_profile()
    with Meter() as meter:
        exact = evaluate_profile(inst, profile)
        lp = None
        if max(inst.size(0), inst.size(1)) <= lp_limit:
            sol = solve_sequence_form(inst)
            lp = {"value0": sol["value0"], "value0_dual": sol["value0_dual"],
                  "solver_value0_minus_lp": exact["value"][0] - sol["value0"],
                  "lp_profile_exploitability_chips": evaluate_profile(inst, sol["profile"])[
                      "exploitability_chips"]}
        versus = []
        for kind in opponents:
            for hero in (0, 1):
                bot = bot_profile(inst, kind, 1 - hero)
                mixed = {nid: (profile[nid] if inst.tree.nodes[nid].player == hero else bot[nid])
                         for nid in profile}
                r = response_value(inst, mixed, hero)
                versus.append({
                    "opponent": kind, "hero_seat": ["OOP", "IP"][hero],
                    "hero_value_chips": r["value"], "best_response_value_chips": r["best_response_value"],
                    "hero_minus_selfplay_value_chips": r["value"] - exact["value"][hero],
                    "unexploited_gap_chips": r["gap"],
                    "hero_value_bb": r["value"] / inst.big_blind})
    return {
        "schema": "pokerlab.plo.river-eval/1", "subgame": inst.description,
        "solver": {"algorithm": solver.config.algorithm, "iterations": solver.iteration,
                   "strategy": "average"},
        "exact_metrics": exact, "lp_check": lp, "versus_fixed_bots": versus,
        "units": ("chips from the start of the river; constant-sum (values of both seats sum "
                  "to the starting pot); % pot relative to the starting pot"),
        "interpretation": ("Exploitability is exact for these ranges and this bet abstraction only. "
                           "Values vs fixed bots are exact expectations, not samples; beating them "
                           "is not evidence of overall strength. hero_minus_selfplay_value compares "
                           "against the solver profile playing itself (an approximate equilibrium "
                           "with the exploitability above), not against an exact equilibrium."),
        "resources": meter.report(), "environment": environment(),
    }


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def solver_config(cfg: dict) -> SolverConfig:
    allowed = {"algorithm", "alpha", "beta", "gamma", "linear", "seed"}
    return SolverConfig(**{k: v for k, v in cfg.items() if k in allowed})
