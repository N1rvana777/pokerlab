"""Clean per-iteration time and memory: exact vs abstraction solves, each in its own process.

Run on a quiet machine (the convergence runs overlap with each other, so their timings are not clean).

    python scripts/plo_abstraction_timing.py --output outputs/plo/v6/abs-timing.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

CASES = [
    {"kind": "turn", "config": "examples/plo/turn_sample1500.json", "mode": "exact", "iterations": 3, "workers": 4},
    {"kind": "turn", "config": "examples/plo/turn_sample1500.json", "mode": "eq_only", "iterations": 3, "workers": 4},
    {"kind": "turn", "config": "examples/plo/turn_sample1500.json", "mode": "v1", "iterations": 3, "workers": 4},
    {"kind": "river", "board": "paired_flush", "mode": "exact", "iterations": 20},
    {"kind": "river", "board": "paired_flush", "mode": "rank", "iterations": 20},
    {"kind": "river", "board": "paired_flush", "mode": "v1", "iterations": 20},
]


def worker(case: dict) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pokerlab.plo.abstraction import (
        TiedRiverSolver, TiedTurnRiverSolver, river_buckets, turn_abstraction,
    )
    from pokerlab.plo.evaluate import load_json
    from pokerlab.plo.resources import peak_memory_mib
    from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig
    from pokerlab.plo.subgame.turn import TurnRiverSolver, turn_river_game
    out = dict(case)
    t = time.perf_counter()
    if case["kind"] == "turn":
        game = turn_river_game(load_json(case["config"]))
        out["build_game_s"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        if case["mode"] == "exact":
            solver = TurnRiverSolver(game, SolverConfig("dcfr"), workers=case["workers"])
            out["abstraction_s"] = 0.0
        else:
            ab = turn_abstraction(game, case["mode"])
            out["abstraction_s"] = round(time.perf_counter() - t, 2)
            out["abstraction_size"] = ab.size()
            solver = TiedTurnRiverSolver(game, ab, SolverConfig("dcfr"), workers=case["workers"])
        solver.run(1)                                     # warm-up
        t = time.perf_counter()
        solver.run(case["iterations"])
        out["s_per_iteration"] = round((time.perf_counter() - t) / case["iterations"], 3)
        out["memory_by_category_mib"] = {k: round(v / 2**20, 1) for k, v in solver.memory().items()}
    else:
        from plo_budget_diagnostics import BOARDS, reference_ranges, spec
        from pokerlab.plo.subgame.instance import plo_river_instance
        inst = plo_river_instance(spec(BOARDS[case["board"]], reference_ranges(BOARDS[case["board"]], 2000, 7),
                                       "inclusion_exclusion"))
        out["build_game_s"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        if case["mode"] == "exact":
            solver = CFRSolver(inst, SolverConfig("dcfr"))
            out["abstraction_s"] = 0.0
        else:
            buckets = tuple(river_buckets(inst, p, case["mode"]) for p in (0, 1))
            out["abstraction_s"] = round(time.perf_counter() - t, 2)
            out["buckets"] = [b.count for b in buckets]
            solver = TiedRiverSolver(inst, buckets, SolverConfig("dcfr"))
        solver.run(1)
        t = time.perf_counter()
        solver.run(case["iterations"])
        out["s_per_iteration"] = round((time.perf_counter() - t) / case["iterations"], 4)
        out["regret_and_average_strategy_mib"] = round(
            sum(a.nbytes for d in (solver.regret, solver.strategy_sum) for a in d.values()) / 2**20, 2)
    out["peak_mib"] = round(peak_memory_mib()["peak_mib"], 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--worker")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.loads(args.worker))))
        return
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    from pokerlab.plo.resources import environment
    started = environment()
    rows = []
    for case in CASES:
        proc = subprocess.run([sys.executable, __file__, "--worker", json.dumps(case)], capture_output=True,
                              text=True, check=True, env={**__import__("os").environ, "OPENBLAS_NUM_THREADS": "1"})
        rows.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        print(json.dumps(rows[-1]), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": "pokerlab.plo.abstraction-timing/1", "rows": rows,
                               "note": "each case in a fresh process, OPENBLAS_NUM_THREADS=1, warm-up iteration excluded",
                               "environment": started}, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
