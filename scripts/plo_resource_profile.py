"""Per-phase resource profile of the PLO solvers (each case in its own subprocess).

For every case the worker times the phases separately and reports, per phase, wall seconds,
process CPU seconds and their ratio (about the number of cores kept busy), plus the process
peak working set.  The cases are kept apart on purpose:

* river_full_reduced   full 178,365-hand ranges, 15-node pot-only tree (examples/plo/river_full_range.json)
* river_full_four      full ranges, 177-node default four-size tree, one raise
* river_dense_1500     1,500 x 1,500 sampled hands, 675-node default tree (dense matrices, BLAS)
* river_agent_150      150 x 150 sampled hands, 675-node tree, 200 iterations (the agent's budget)
* turn_small / turn_medium   joint turn + river games (examples/plo/turn_*.json)

The code has no GPU path; GPU use is therefore zero by construction (the report records the GPU
seen by nvidia-smi only as context).

    python scripts/plo_resource_profile.py --output outputs/plo/diagnostics/resources.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CASES = {
    "river_full_reduced": {"kind": "river", "config": "examples/plo/river_full_range.json", "iterations": 3},
    "river_full_four": {"kind": "river", "config": "examples/plo/river_full_range_four_sizes.json", "iterations": 2},
    "river_dense_1500": {"kind": "river", "config": "examples/plo/river_medium.json", "iterations": 20},
    "river_agent_150": {"kind": "river", "config": "examples/plo/river_small.json", "iterations": 200,
                        "override_ranges": [{"sample": 150, "seed": 31}, {"sample": 150, "seed": 32}]},
    "turn_small": {"kind": "turn", "config": "examples/plo/turn_small.json", "iterations": 20},
    "turn_medium": {"kind": "turn", "config": "examples/plo/turn_medium.json", "iterations": 5},
}


class Phase:
    def __init__(self, name: str, log: dict) -> None:
        self.name, self.log = name, log

    def __enter__(self):
        import psutil
        self.proc = psutil.Process()
        self.wall = time.perf_counter()
        t = self.proc.cpu_times()
        self.cpu = t.user + t.system
        return self

    def __exit__(self, *exc) -> None:
        t = self.proc.cpu_times()
        wall = time.perf_counter() - self.wall
        cpu = t.user + t.system - self.cpu
        self.log[self.name] = {"wall_s": round(wall, 3), "cpu_s": round(cpu, 3),
                               "cpu_per_wall": round(cpu / wall, 2) if wall > 0 else None}


def worker(name: str) -> dict:
    import numpy as np                       # noqa: F401  (loads BLAS before threadpool_info)
    import threadpoolctl

    from pokerlab.plo.evaluate import load_json
    from pokerlab.plo.resources import peak_memory_mib
    case = CASES[name]
    spec = load_json(case["config"])
    if "override_ranges" in case:
        spec = dict(spec, ranges=case["override_ranges"], showdown="dense")
    phases: dict = {}
    out = {"case": name, **case}
    if case["kind"] == "river":
        from pokerlab.plo.cards import parse_cards
        from pokerlab.plo.evaluator import plo_rank_batch
        from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile
        from pokerlab.plo.subgame.instance import build_range, plo_river_instance
        board = parse_cards(spec["board"])
        with Phase("ranges", phases):
            ranges = [build_range(r, board) for r in spec["ranges"]]
        with Phase("hand_ranking", phases):
            for hands, _ in ranges:
                plo_rank_batch(hands, board)
        with Phase("instance_build_total", phases):     # ranking again + showdown index + tree
            inst = plo_river_instance(spec)
        solver = CFRSolver(inst, SolverConfig("dcfr"))
        with Phase("cfr_iterations", phases):
            solver.run(case["iterations"])
        with Phase("best_response_eval", phases):
            metrics = evaluate_profile(inst, solver.average_profile())
        out.update({"tree": inst.tree.summary(), "range_sizes": [inst.size(0), inst.size(1)],
                    "showdown": inst.description["showdown"],
                    "exploitability_pct_pot_after": metrics["exploitability_pct_pot"],
                    "solver_arrays_mib": round(solver.memory_bytes() / 2**20, 1)})
    else:
        from pokerlab.plo.subgame.cfr import SolverConfig
        from pokerlab.plo.subgame.turn import TurnRiverSolver, evaluate_turn_profile, turn_river_game
        with Phase("game_build_total", phases):          # ranges, per-card ranking and matrices, trees
            game = turn_river_game(spec)
        solver = TurnRiverSolver(game, SolverConfig("dcfr"))
        with Phase("cfr_iterations", phases):
            solver.run(case["iterations"])
        with Phase("best_response_eval", phases):
            metrics = evaluate_turn_profile(game, solver.average_profile())
        out.update({"nodes": game.nodes_summary(), "range_sizes": [game.size(0), game.size(1)],
                    "exploitability_pct_pot_after": metrics["exploitability_pct_pot"],
                    "solver_arrays_mib": round(solver.memory_bytes() / 2**20, 1)})
    out["phases"] = phases
    out["per_iteration_wall_s"] = round(phases["cfr_iterations"]["wall_s"] / case["iterations"], 4)
    out["blas"] = [{k: v for k, v in info.items() if k in ("internal_api", "num_threads", "version")}
                   for info in threadpoolctl.threadpool_info()]
    out["memory"] = peak_memory_mib()
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--worker")
    parser.add_argument("--cases", nargs="*", default=list(CASES))
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker)))
        return
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    results = []
    for name in args.cases:
        proc = subprocess.run([sys.executable, __file__, "--worker", name], capture_output=True, text=True,
                              check=True)
        results.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        r = results[-1]
        print(name, json.dumps({"phases": r["phases"], "per_iteration_wall_s": r["per_iteration_wall_s"],
                                "peak_mib": round(r["memory"]["peak_mib"], 1)}), flush=True)
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu", "--format=csv"],
                         capture_output=True, text=True)
    from pokerlab.plo.resources import environment
    report = {"schema": "pokerlab.plo.resource-profile/1", "results": results,
              "gpu_seen": gpu.stdout.strip() if gpu.returncode == 0 else None,
              "gpu_used_by_solver": False,
              "note": ("cpu_per_wall ~ 1 means one busy core; above 1 means BLAS threads (dense matrix "
                       "products) are running in parallel. Each case ran alone in a fresh process."),
              "logical_cpus": os.cpu_count(), "environment": environment()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
