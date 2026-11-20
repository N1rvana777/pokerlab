"""Hand abstraction v1 measured in the original reference games (best response and exploitability).

River (one board per call; reference ranges as in plo_budget_diagnostics: 2,000 baseline-v1 posterior
draws per player after a fixed public line, default four-size tree with two raises):
  exact      full per-hand DCFR (500 iterations; a saved solution is reused after a fingerprint check);
  old_map    the earlier rank mapping: k=150 sampled solve (200 iterations) + nearest-river-rank copy,
             and the same mapping applied to the exact strategies of the sampled hands;
  rank       one bucket per distinct river rank, solved with strategy tying (showdown rank, no blockers);
  eq_only    equal-mass equity bins (same count as v1), tied;
  v1         equity x blocker-to-strong x blocker-to-weak buckets, tied.
Every abstract strategy is expanded to all hands and evaluated in the original game.

Turn (one config and one mode per call): a tied joint turn + river solve, evaluated in the original
turn game at a fixed iteration schedule; the exact reference comes from ``solve-turn`` reports.

    python scripts/plo_abstraction_eval.py river --board paired_flush --output outputs/plo/v6/abs-river-paired
    python scripts/plo_abstraction_eval.py turn --config examples/plo/turn_sample1500.json --mode v1 \
        --iterations 200 --workers 4 --output outputs/plo/v6/abs-turn1500-v1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plo_budget_diagnostics import BOARDS, extend_profile, reference_ranges, spec, subsample  # noqa: E402
from plo_reference_error_control import load_profile, save_profile  # noqa: E402

from pokerlab.plo.abstraction import (  # noqa: E402
    TiedRiverSolver, TiedTurnRiverSolver, perfect_recall_holds, river_buckets, turn_abstraction,
)
from pokerlab.plo.evaluate import load_json  # noqa: E402
from pokerlab.plo.resources import environment, peak_memory_mib  # noqa: E402
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile  # noqa: E402
from pokerlab.plo.subgame.instance import plo_river_instance  # noqa: E402
from pokerlab.plo.subgame.turn import evaluate_turn_profile, turn_river_game  # noqa: E402

HELD_OUT = {"connected_flush_draw": "Jd Td 8d 4s 2c"}      # not used for any choice below
ALL_BOARDS = {**BOARDS, **HELD_OUT}
SEED, DRAWS = 7, 2000


def losses(metrics: dict, value0: float, pot: float) -> dict:
    br0, br1 = metrics["best_response_value"]
    return {"player0_strategy": 100 * (value0 - (pot - br1)) / pot,
            "player1_strategy": 100 * ((pot - value0) - (pot - br0)) / pot}


def river(args) -> dict:
    board = ALL_BOARDS[args.board]
    ref_ranges = reference_ranges(board, DRAWS, SEED)
    # Inclusion-exclusion showdown: same game, ~13x faster than dense matrices at ~1,950 hands on one core.
    inst = plo_river_instance(spec(board, ref_ranges, "inclusion_exclusion"))
    pot = float(inst.pot)
    out = Path(args.output)
    report = {"schema": "pokerlab.plo.abstraction-eval-river/1", "board_name": args.board, "board": board,
              "held_out": args.board in HELD_OUT, "reference_range_sizes": [inst.size(0), inst.size(1)],
              "tree": inst.tree.summary(), "iterations": args.iterations, "rows": []}

    def solve_and_eval(name, solver, extra):
        t = time.perf_counter()
        solver.run(args.iterations)
        solve_s = time.perf_counter() - t
        t = time.perf_counter()
        m = evaluate_profile(inst, solver.average_profile())
        row = {"variant": name, "exploitability_pct_pot": m["exploitability_pct_pot"],
               "loss_pct_pot": losses(m, value0, pot), "solve_s": round(solve_s, 1),
               "s_per_iteration": round(solve_s / args.iterations, 4), "eval_s": round(time.perf_counter() - t, 1),
               "regret_and_average_strategy_mib": round(sum(a.nbytes for d in (solver.regret, solver.strategy_sum)
                                                            for a in d.values()) / 2**20, 2), **extra}
        report["rows"].append(row)
        print(f"{args.board:<22} {name:<26} {row['exploitability_pct_pot']:9.4f}% pot  "
              f"{row['s_per_iteration']:.3f} s/it  arrays {row['regret_and_average_strategy_mib']} MiB", flush=True)
        return row

    # exact reference (reused when saved)
    saved = Path(args.reference_profile) if args.reference_profile else out / f"reference-dcfr{args.iterations}.npz"
    if saved.exists():
        exact_profile, iters = load_profile(saved, inst.fingerprint)
        m = evaluate_profile(inst, exact_profile)
        value0 = m["value"][0]
        report["rows"].append({"variant": "exact", "reused": saved.as_posix(), "iterations": iters,
                               "exploitability_pct_pot": m["exploitability_pct_pot"],
                               "loss_pct_pot": losses(m, value0, pot)})
        print(f"{args.board:<22} exact (reused)             {m['exploitability_pct_pot']:9.4f}% pot", flush=True)
    else:
        solver = CFRSolver(inst, SolverConfig("dcfr"))
        value0 = 0.0
        t = time.perf_counter()
        solver.run(args.iterations)
        solve_s = time.perf_counter() - t
        exact_profile = solver.average_profile()
        m = evaluate_profile(inst, exact_profile)
        value0 = m["value"][0]
        out.mkdir(parents=True, exist_ok=True)
        save_profile(saved, exact_profile, inst.fingerprint, args.iterations)
        report["rows"].append({"variant": "exact", "saved": saved.as_posix(), "exploitability_pct_pot":
                               m["exploitability_pct_pot"], "loss_pct_pot": losses(m, value0, pot),
                               "solve_s": round(solve_s, 1), "s_per_iteration": round(solve_s / args.iterations, 4),
                               "regret_and_average_strategy_mib": round(sum(a.nbytes for d in (solver.regret, solver.strategy_sum)
                                                                            for a in d.values()) / 2**20, 2)})
        print(f"{args.board:<22} exact                      {m['exploitability_pct_pot']:9.4f}% pot", flush=True)
    report["reference_value0"] = value0

    # old rank mapping (as in the diagnostics): k=150 draws, 200 iterations, nearest river rank
    sub = subsample(ref_ranges, 150, SEED)
    sampled = plo_river_instance(spec(board, sub, "dense"))
    s = CFRSolver(sampled, SolverConfig("dcfr"))
    s.run(200)
    m = evaluate_profile(inst, extend_profile(sampled, inst, s.average_profile()))
    report["rows"].append({"variant": "old_map: k=150 sampled solve + nearest rank", "exploitability_pct_pot":
                           m["exploitability_pct_pot"], "loss_pct_pot": losses(m, value0, pot)})
    find = {p: {tuple(sorted(h)): i for i, h in enumerate(inst.hands[p].tolist())} for p in (0, 1)}
    rows = [np.array([find[p][tuple(sorted(h))] for h in sampled.hands[p].tolist()]) for p in (0, 1)]
    exact_on_sample = {n: v[rows[inst.tree.nodes[n].player]] for n, v in exact_profile.items()}
    m1 = evaluate_profile(inst, extend_profile(sampled, inst, exact_on_sample))
    report["rows"].append({"variant": "old_map: exact strategies of sampled hands + nearest rank",
                           "exploitability_pct_pot": m1["exploitability_pct_pot"], "loss_pct_pot": losses(m1, value0, pot)})
    print(f"{args.board:<22} old_map (sampled / exact)  {m['exploitability_pct_pot']:9.4f}% / "
          f"{m1['exploitability_pct_pot']:.4f}% pot", flush=True)

    for mode, q in [("rank", None)] + [(m_, q_) for q_ in args.q_eq for m_ in ("eq_only", "v1")]:
        t = time.perf_counter()
        buckets = tuple(river_buckets(inst, p, mode, q_eq=q or 16) for p in (0, 1))
        build_s = time.perf_counter() - t
        name = mode if q is None else f"{mode} (q_eq={q})"
        solve_and_eval(name, TiedRiverSolver(inst, buckets, SolverConfig("dcfr")),
                       {"buckets": [b.count for b in buckets],
                        "buckets_used": [int(len(np.unique(b.ids))) for b in buckets],
                        "abstraction_build_s": round(build_s, 2), "perfect_recall": "yes (one street, one bucket per hand)"})
    report["memory"] = peak_memory_mib()
    report["environment"] = environment()
    return report


def turn(args) -> dict:
    cfg = load_json(args.config)
    game = turn_river_game(cfg)
    t = time.perf_counter()
    ab = turn_abstraction(game, args.mode, q_turn=args.q_turn, q_river=args.q_river)
    build_s = time.perf_counter() - t
    solver = TiedTurnRiverSolver(game, ab, SolverConfig("dcfr"), workers=args.workers)
    trajectory, eval_s = [], 0.0

    def callback(s):
        nonlocal eval_s
        if s.iteration % args.eval_every == 0 or s.iteration == args.iterations:
            t0 = time.perf_counter()
            m = evaluate_turn_profile(game, s.average_profile())
            eval_s += time.perf_counter() - t0
            trajectory.append({"iteration": s.iteration, "solve_seconds": round(s.elapsed, 1),
                               "exploitability_pct_pot": m["exploitability_pct_pot"],
                               "value0": m["value"][0], "best_response_value": m["best_response_value"]})
            print(f"{args.mode} iter {s.iteration:>4}  {m['exploitability_pct_pot']:.4f}% pot  solve {s.elapsed:.0f}s",
                  flush=True)

    started_env = environment()
    solver.run(args.iterations, callback)
    return {"schema": "pokerlab.plo.abstraction-eval-turn/1", "config": args.config, "mode": args.mode,
            "q_turn": args.q_turn, "q_river": args.q_river, "range_sizes": [game.size(0), game.size(1)],
            "nodes": game.nodes_summary(), "abstraction_size": ab.size(), "edges": ab.edges,
            "perfect_recall": perfect_recall_holds(ab, game), "abstraction_build_s": round(build_s, 2),
            "iterations": solver.iteration, "workers": solver.workers, "trajectory": trajectory,
            "solve_s": round(solver.elapsed, 1), "s_per_iteration": round(solver.elapsed / solver.iteration, 3),
            "eval_s": round(eval_s, 1), "memory_by_category_mib": {k: round(v / 2**20, 2) for k, v in solver.memory().items()},
            "memory": peak_memory_mib(), "environment": started_env}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("river")
    r.add_argument("--board", required=True, choices=sorted(ALL_BOARDS))
    r.add_argument("--iterations", type=int, default=500)
    r.add_argument("--q-eq", type=int, nargs="*", default=[8, 16])
    r.add_argument("--reference-profile")
    r.add_argument("--output", required=True)
    t = sub.add_parser("turn")
    t.add_argument("--config", required=True)
    t.add_argument("--mode", default="v1", choices=["v1", "eq_only"])
    t.add_argument("--q-turn", type=int, default=8)
    t.add_argument("--q-river", type=int, default=4)
    t.add_argument("--iterations", type=int, default=200)
    t.add_argument("--eval-every", type=int, default=50)
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if (out / "report.json").exists():
        raise SystemExit(f"refusing to overwrite {out / 'report.json'}")
    report = river(args) if args.cmd == "river" else turn(args)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out / 'report.json'}")


if __name__ == "__main__":
    main()
