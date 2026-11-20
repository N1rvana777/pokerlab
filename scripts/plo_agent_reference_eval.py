"""Actual-agent strategy error on tiny reference games, through the agents' own range and solve code.

For every private hand of every player in a reference game, the agent's procedure runs as it does
in play: ``sample_ranges`` (seed ``[seed, HAND_ID, player]``; the draws do not depend on the agent's
own cards; the own hand is appended with weight 1, one draw's weight, when no draw picked it), the
agent's spec and solve, then the strategy lookup for that hand.  In the reference game every opponent
action is in the tree, so the agent keeps its first solve's strategy at all of its later nodes; the
profile assembled from these lookups is therefore exactly what the agent plays.  It is evaluated in
the reference game with exact best responses.

Reported separately:
  * k = N control: ``range_samples = 0`` keeps every reference hand at its own weight, so every
    private hand sees the same game and the profile is one solve's profile;
  * the earlier hybrid: sampled hands use the shared sampled solve, every other hand uses the exact
    reference strategy.  It is NOT the agent's behaviour and is shown only to compare.

    python scripts/plo_agent_reference_eval.py --output outputs/plo/v6/agent-reference
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from pokerlab.plo.evaluate import load_json
from pokerlab.plo.resources import environment, peak_memory_mib
from pokerlab.plo.river_agent import RiverSettings, river_spec, sample_ranges, solve_river
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile
from pokerlab.plo.subgame.instance import _chips, plo_river_instance
from pokerlab.plo.subgame.reference import solve_sequence_form
from pokerlab.plo.subgame.turn import TurnRiverSolver, evaluate_turn_profile, turn_river_game
from pokerlab.plo.subgame.turn_reference import solve_turn_sequence_form
from pokerlab.plo.turn_agent import TurnRiverSettings, joint_spec, solve_joint

HAND_ID = 0                       # one public situation: the same hand id for every private hand
RIVER_GAMES = ["examples/plo/river_tiny_lp.json", "examples/plo/river_blockers_tiny.json"]
TURN_GAMES = ["examples/plo/turn_tiny_lp.json"]


def find(hands: np.ndarray, hand) -> int:
    hits = np.flatnonzero((np.sort(hands, axis=1) == np.sort(np.asarray(hand))).all(axis=1))
    assert len(hits) == 1
    return int(hits[0])


def losses(metrics: dict, value0: float, pot: float) -> dict:
    br0, br1 = metrics["best_response_value"]
    return {"player0_strategy": 100 * (value0 - (pot - br1)) / pot,
            "player1_strategy": 100 * ((pot - value0) - (pot - br0)) / pot}


def agent_profile(kind, ref, base, settings, seed):
    """Strategy the agent plays with every private hand; plus the shared sampled game for the hybrid."""
    posterior = {p: (ref.hands[p], ref.weights[p]) for p in (0, 1)}
    solve = (lambda spec: solve_river(spec, settings, seed)) if kind == "river" else \
        (lambda spec: solve_joint(spec, settings, seed)[:2])
    make = (lambda r: river_spec(base, r, settings)) if kind == "river" else (lambda r: joint_spec(base, r, settings))
    shared_ranges, shared_info = sample_ranges(posterior, settings.range_samples, (seed, HAND_ID), None, None)
    shared_game, shared_profile = solve(make(shared_ranges))
    same_tree = (shared_game.tree.summary() == ref.tree.summary()) if kind == "river" else         (shared_game.nodes_summary() == ref.nodes_summary())
    assert same_tree, "the agent's tree differs from the reference tree; profiles cannot be compared"
    profile = _empty_like(kind, ref)
    stats = {"solves": 1, "own_hand_added": [0, 0], "shared_unique_hands": [i["unique_hands"] for i in shared_info],
             "shared_posterior_mass": [i["posterior_mass_of_sampled_hands"] for i in shared_info]}
    for p in (0, 1):
        for i, hand in enumerate(ref.hands[p]):
            ranges, info = sample_ranges(posterior, settings.range_samples, (seed, HAND_ID), p, hand)
            if info[p]["own_hand_added"]:
                game, prof = solve(make(ranges))
                stats["solves"] += 1
                stats["own_hand_added"][p] += 1
            else:                                        # same game as the shared one: same deterministic solve
                game, prof = shared_game, shared_profile
            _copy_rows(kind, profile, prof, p, i, find(game.hands[p], hand), ref)
    return profile, shared_game, shared_profile, stats


def _empty_like(kind, ref):
    if kind == "river":
        return {nid: np.zeros((ref.size(ref.tree.nodes[nid].player), len(ref.tree.nodes[nid].children)))
                for nid in ref.tree.decision_nodes()}
    solver = TurnRiverSolver(ref)
    return {"turn": {k: np.zeros_like(v) for k, v in solver.turn_regret.items()},
            "river": {k: np.zeros_like(v) for k, v in solver.river_regret.items()}}


def _copy_rows(kind, dest, src, p, i, j, ref):
    if kind == "river":
        for nid, strat in src.items():
            if ref.tree.nodes[nid].player == p:
                dest[nid][i] = strat[j]
        return
    for nid, strat in src["turn"].items():
        if ref.turn_tree.nodes[nid].player == p:
            dest["turn"][nid][i] = strat[j]
    for (leaf, rid), strat in src["river"].items():
        if ref.leaves[leaf].tree.nodes[rid].player == p:
            dest["river"][(leaf, rid)][:, i] = strat[:, j]


def hybrid(kind, ref, shared_game, shared_profile, exact):
    out = {k: v.copy() for k, v in exact.items()} if kind == "river" else \
        {s: {k: v.copy() for k, v in exact[s].items()} for s in ("turn", "river")}
    for p in (0, 1):
        for j, hand in enumerate(shared_game.hands[p]):
            _copy_rows(kind, out, shared_profile, p, find(ref.hands[p], hand), j, ref)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--k", type=int, nargs="*", default=[4, 8, 150, 0])
    parser.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3])
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    report = {"schema": "pokerlab.plo.agent-reference-eval/1", "hand_id": HAND_ID, "games": []}
    for kind, path in [("river", g) for g in RIVER_GAMES] + [("turn", g) for g in TURN_GAMES]:
        spec = load_json(path)
        bb = int(spec.get("big_blind", 100))
        if kind == "river":
            ref = plo_river_instance(spec)
            lp = solve_sequence_form(ref)
            exact_solver = CFRSolver(ref, SolverConfig("dcfr"))
            exact_solver.run(3000)
            exact = exact_solver.average_profile()
            evaluate = lambda prof: evaluate_profile(ref, prof)
            base = {"board": spec["board"], "big_blind": bb, "pot": ref.pot, "stacks": _chips(spec, "stacks", bb)}
            agent_defaults = {"iterations": 200, "bet_sizes": tuple(spec.get("bet_sizes", RiverSettings.bet_sizes)),
                              "raise_sizes": tuple(spec.get("raise_sizes", RiverSettings.raise_sizes)),
                              "include_min_raise": spec.get("include_min_raise", True),
                              "include_max_raise": spec.get("include_max_raise", True),
                              "max_raises": spec.get("max_raises", 2)}
            make_settings = lambda k: RiverSettings(range_samples=k, **agent_defaults)
            agent_name = "river_solver (river_agent.sample_ranges / river_spec / solve_river)"
        else:
            ref = turn_river_game(spec)
            lp = solve_turn_sequence_form(ref)
            exact_solver = TurnRiverSolver(ref)
            exact_solver.run(500)
            exact = exact_solver.average_profile()
            evaluate = lambda prof: evaluate_turn_profile(ref, prof)
            base = {"board": spec["board"], "big_blind": bb, "pot": ref.pot, "stacks": _chips(spec, "stacks", bb)}
            agent_defaults = {"iterations": 100, "turn_max_raises": spec.get("turn_max_raises", 1),
                              "river_max_raises": spec.get("river_max_raises", 1), "showdown": "dense",
                              "bet_sizes": tuple(spec.get("bet_sizes", TurnRiverSettings.bet_sizes)),
                              "raise_sizes": tuple(spec.get("raise_sizes", TurnRiverSettings.raise_sizes)),
                              "include_min_raise": spec.get("include_min_raise", True),
                              "include_max_raise": spec.get("include_max_raise", True)}
            make_settings = lambda k: TurnRiverSettings(range_samples=k, **agent_defaults)
            agent_name = "turn_river_solver (river_agent.sample_ranges / turn_agent.joint_spec / solve_joint)"
        ref_metrics = evaluate(exact)
        game_row = {"game": path, "kind": kind, "agent": agent_name, "range_sizes": [ref.size(0), ref.size(1)],
                    "reference": {"lp_value0": lp["value0"], "exact_solver_exploitability_pct_pot":
                                  ref_metrics["exploitability_pct_pot"], "exact_solver_value0": ref_metrics["value"][0]},
                    "agent_settings": {k: list(v) if isinstance(v, tuple) else v for k, v in agent_defaults.items()},
                    "runs": []}
        print(f"== {path}: ranges {game_row['range_sizes']}, exact {ref_metrics['exploitability_pct_pot']:.5f}% pot",
              flush=True)
        for k in args.k:
            for seed in (args.seeds if k else args.seeds[:1]):
                t = time.perf_counter()
                settings = make_settings(k)
                profile, shared_game, shared_profile, stats = agent_profile(kind, ref, base, settings, seed)
                m_agent = evaluate(profile)
                m_hybrid = evaluate(hybrid(kind, ref, shared_game, shared_profile, exact))
                m_shared = (evaluate_profile(shared_game, shared_profile) if kind == "river"
                            else evaluate_turn_profile(shared_game, shared_profile))
                row = {"k": k if k else "N (no sampling)", "seed": seed, **stats,
                       "agent_exploitability_pct_pot": m_agent["exploitability_pct_pot"],
                       "agent_losses_pct_pot": losses(m_agent, lp["value0"], ref.pot),
                       "hybrid_exploitability_pct_pot": m_hybrid["exploitability_pct_pot"],
                       "shared_sampled_game_in_sample_pct_pot": m_shared["exploitability_pct_pot"],
                       "seconds": round(time.perf_counter() - t, 1)}
                game_row["runs"].append(row)
                print(f"   k={row['k']!s:>15} seed={seed}: agent {row['agent_exploitability_pct_pot']:8.4f}%  "
                      f"hybrid {row['hybrid_exploitability_pct_pot']:8.4f}%  in-sample {row['shared_sampled_game_in_sample_pct_pot']:.4f}%  "
                      f"solves {stats['solves']} own-added {stats['own_hand_added']}", flush=True)
        report["games"].append(game_row)
    report["memory"] = peak_memory_mib()
    report["environment"] = environment()
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out / 'report.json'}")


if __name__ == "__main__":
    main()
