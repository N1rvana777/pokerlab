"""Bounded decision-budget diagnosis for heads-up PLO4 river solving.

Fixed reference problems (board, pot, stacks, the default four-size abstraction) are
solved under different iteration budgets and different range-sample sizes.  Two errors
are kept apart:

* in-sample exploitability: NashConv/2 of the sampled game's own average strategy,
  measured inside that sampled game;
* reference-game error: the sampled game's strategy only covers sampled hands, so it
  is first extended to every reference hand by an explicit rule (copy the strategy of
  the sampled hand with the nearest river rank key; hands that are in the sample keep
  their own strategy), then evaluated by exact best response in the reference game.
  The number therefore measures "sampling + this extension rule", not the sampled
  strategy alone.

The reference game is itself declared explicitly: both players' ranges are a seeded
multinomial sample (counts as weights) from a baseline-v1 posterior after a fixed public
line.  It is a stand-in for the full posterior, kept dense-solvable on purpose.

Each configuration runs in its own subprocess so that peak memory is per configuration.

    python scripts/plo_budget_diagnostics.py --output outputs/plo/diagnostics/budget.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from pokerlab.plo.baseline import BaselinePolicy, every_hand
from pokerlab.plo.cards import format_cards, parse_cards
from pokerlab.plo.engine import ActionType
from pokerlab.plo.evaluator import plo_rank_batch
from pokerlab.plo.public import PublicDecision
from pokerlab.plo.resources import environment, peak_memory_mib
from pokerlab.plo.river_agent import posterior_log_weights
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile
from pokerlab.plo.subgame.instance import plo_river_instance

BOARDS = {"paired_flush": "Ah 8h 8d 5c 2h", "dry_rainbow": "Ks 9h 7d 4c 2s"}
ABSTRACTION = {"bet_sizes": ["1/3", "1/2", "2/3", "1"], "raise_sizes": ["1/3", "1/2", "2/3", "1"],
               "include_min_raise": True, "include_max_raise": True, "max_raises": 2, "min_bet": 100}
POT, STACK, BB = 2000, 8000, 100
# Public line before the river (seat 0 = out of position / big blind, seat 1 = button):
# preflop button raises, big blind calls; flop check, bet, call; turn check, check.
LINE = [(0, 1, ActionType.RAISE, True, True), (0, 0, ActionType.CALL, True, True),
        (1, 0, ActionType.CHECK, False, True), (1, 1, ActionType.BET, False, True),
        (1, 0, ActionType.CALL, True, True), (2, 0, ActionType.CHECK, False, True),
        (2, 1, ActionType.CHECK, False, True)]


def reference_ranges(board: str, draws: int, seed: int) -> list[dict]:
    cards = parse_cards(board)
    hands = every_hand()
    candidates = hands[~np.isin(hands, np.asarray(cards)).any(axis=1)]
    decisions = [PublicDecision(street, seat, action, 0, facing, can_raise, 0, 0)
                 for street, seat, action, facing, can_raise in LINE]
    policy = BaselinePolicy()
    ranges = []
    for seat in (0, 1):
        logw, _ = posterior_log_weights(policy, decisions, seat, cards, candidates)
        w = np.exp(logw - logw.max())
        rng = np.random.default_rng([seed, seat])
        idx, counts = np.unique(rng.choice(len(candidates), size=draws, p=w / w.sum()), return_counts=True)
        ranges.append({"hands": [format_cards(h) for h in candidates[idx]], "weights": counts.tolist()})
    return ranges


def spec(board: str, ranges: list[dict], showdown: str = "auto") -> dict:
    return {"board": board, "big_blind": BB, "pot": POT, "stacks": [STACK, STACK], "ranges": ranges,
            **ABSTRACTION, "showdown": showdown}


def subsample(ranges: list[dict], k: int, seed: int) -> list[dict]:
    out = []
    for player, r in enumerate(ranges):
        w = np.asarray(r["weights"], dtype=float)
        rng = np.random.default_rng([seed, 99, player])
        idx, counts = np.unique(rng.choice(len(w), size=k, p=w / w.sum()), return_counts=True)
        out.append({"hands": [r["hands"][i] for i in idx], "weights": counts.tolist()})
    return out


def extend_profile(sampled, reference, profile) -> dict:
    """Nearest-river-rank extension of a sampled strategy to every reference hand."""
    board = parse_cards(reference.description["board"])
    mapping = []
    for p in (0, 1):
        s_keys = plo_rank_batch(sampled.hands[p], board)
        r_keys = plo_rank_batch(reference.hands[p], board)
        order = np.argsort(s_keys, kind="stable")
        sorted_keys = s_keys[order]
        pos = np.clip(np.searchsorted(sorted_keys, r_keys), 0, len(sorted_keys) - 1)
        left = np.clip(pos - 1, 0, len(sorted_keys) - 1)
        nearest = np.where(np.abs(sorted_keys[left] - r_keys) <= np.abs(sorted_keys[pos] - r_keys), left, pos)
        idx = order[nearest]
        exact = {tuple(sorted(h)): i for i, h in enumerate(sampled.hands[p].tolist())}
        for row, h in enumerate(reference.hands[p].tolist()):
            hit = exact.get(tuple(sorted(h)))
            if hit is not None:
                idx[row] = hit
        mapping.append(idx)
    out = {}
    for nid, strat in profile.items():
        player = reference.tree.nodes[nid].player
        out[nid] = strat[mapping[player]]
    return out


def worker(task: dict) -> dict:
    t0 = time.perf_counter()
    ref_ranges = reference_ranges(task["board"], task["reference_draws"], task["seed"])
    reference = plo_river_instance(spec(task["board"], ref_ranges))
    t_build_ref = time.perf_counter() - t0
    result = {"task": task, "reference_range_sizes": [reference.size(0), reference.size(1)],
              "tree": reference.tree.summary()}
    if task["kind"] == "iterations":
        solver = CFRSolver(reference, SolverConfig("dcfr"))
        trajectory, done = [], 0
        for target in task["iterations"]:
            t = time.perf_counter()
            solver.run(target - done)
            done = target
            solve_s = time.perf_counter() - t
            t = time.perf_counter()
            metrics = evaluate_profile(reference, solver.average_profile())
            trajectory.append({"iterations": target, "solve_s_cumulative": round(solver.elapsed, 3),
                               "best_response_eval_s": round(time.perf_counter() - t, 3),
                               "exploitability_pct_pot": metrics["exploitability_pct_pot"]})
        result.update({"build_reference_s": round(t_build_ref, 3), "trajectory": trajectory})
    else:
        sampled = plo_river_instance(spec(task["board"], subsample(ref_ranges, task["k"], task["seed"]), "dense"))
        t = time.perf_counter()
        solver = CFRSolver(sampled, SolverConfig("dcfr"))
        solver.run(task["iterations"])
        solve_s = time.perf_counter() - t
        in_sample = evaluate_profile(sampled, solver.average_profile())
        t = time.perf_counter()
        extended = extend_profile(sampled, reference, solver.average_profile())
        reference_error = evaluate_profile(reference, extended)
        result.update({"sampled_range_sizes": [sampled.size(0), sampled.size(1)],
                       "solve_s": round(solve_s, 3),
                       "in_sample_exploitability_pct_pot": in_sample["exploitability_pct_pot"],
                       "reference_exploitability_of_extended_pct_pot": reference_error["exploitability_pct_pot"],
                       "reference_eval_s": round(time.perf_counter() - t, 3)})
    result["memory"] = peak_memory_mib()
    result["wall_s"] = round(time.perf_counter() - t0, 3)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--worker")
    parser.add_argument("--reference-draws", type=int, default=2000)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.loads(args.worker))))
        return
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    tasks = []
    for name, board in BOARDS.items():
        tasks.append({"kind": "iterations", "board_name": name, "board": board, "seed": 7,
                      "reference_draws": args.reference_draws, "iterations": [50, 100, 200, 500]})
        for k in (50, 150, 400):
            for iterations in (100, 200, 500):
                tasks.append({"kind": "sample", "board_name": name, "board": board, "seed": 7,
                              "reference_draws": args.reference_draws, "k": k, "iterations": iterations})
    results = []
    for task in tasks:
        proc = subprocess.run([sys.executable, __file__, "--worker", json.dumps(task)],
                              capture_output=True, text=True, check=True)
        results.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        r = results[-1]
        label = (f"{task['board_name']} reference iterations" if task["kind"] == "iterations"
                 else f"{task['board_name']} k={task['k']} it={task['iterations']}")
        print(label, json.dumps({k: v for k, v in r.items() if k not in ("task", "tree", "memory")})[:400],
              f"peak {r['memory']['peak_mib']:.0f} MiB", flush=True)
    report = {"schema": "pokerlab.plo.budget-diagnostics/1", "pot": POT, "stacks": [STACK, STACK],
              "big_blind": BB, "abstraction": ABSTRACTION, "boards": BOARDS,
              "public_line": [[s, seat, a.value, f, c] for s, seat, a, f, c in LINE],
              "reference_game": (f"each player's range = {args.reference_draws} seeded multinomial draws "
                                 "from the baseline-v1 posterior after the public line (counts as weights)"),
              "extension_rule": ("unsampled reference hands copy the strategy of the sampled hand with "
                                 "the nearest river rank key; sampled hands keep their own strategy"),
              "results": results, "environment": environment()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
