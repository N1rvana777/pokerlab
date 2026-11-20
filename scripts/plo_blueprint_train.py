"""Train the minimal four-street HU PLO4 blueprint (external-sampling MCCFR) with stop conditions.

Stops at ``--iterations`` total or after ``--max-minutes`` of this run, whichever comes first; saves
checkpoints, and reports the game and abstraction sizes, speed, table memory and how much the average
strategy still moves between checkpoints (full-game exploitability is not computable at this size).

    python scripts/plo_blueprint_train.py --iterations 150000 --max-minutes 40 \
        --checkpoint-every 25000 --output outputs/plo/v6/blueprint-v0
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from pokerlab.plo.blueprint import PREFLOP, BlueprintGame, BlueprintSpec, BlueprintTrainer, CoarseBuckets
from pokerlab.plo.resources import environment, peak_memory_mib


def snapshot(trainer: BlueprintTrainer) -> dict:
    return {k: trainer.average(*k) for k in trainer.strategy_sum}


def movement(before: dict, after: dict, trainer: BlueprintTrainer) -> dict:
    """Visit-weighted mean L1 change of the average strategy per street since the last checkpoint."""
    out = {}
    for street in range(4):
        num = den = 0.0
        for k, a in after.items():
            if trainer.game.street_of[k[0]] != street or k not in before:
                continue
            w = trainer.strategy_sum[k].sum(axis=1)
            num += float((w * np.abs(a - before[k]).sum(axis=1)).sum())
            den += float(w.sum())
        out[["preflop", "flop", "turn", "river"][street]] = num / den if den else None
    return out


def preflop_summary(trainer: BlueprintTrainer) -> dict:
    """Small blind's first action by preflop bucket (0 = weakest)."""
    game = trainer.game
    root = game.trees[game.root].nodes[0]
    k = (game.root, 0)
    if k not in trainer.strategy_sum:
        return {}
    avg = trainer.average(*k)
    return {"actions": list(root.actions), "by_bucket": [[round(float(x), 3) for x in row] for row in avg]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=150000)
    parser.add_argument("--max-minutes", type=float, default=40.0)
    parser.add_argument("--checkpoint-every", type=int, default=25000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resume")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    started_env = environment()
    t0 = time.perf_counter()
    game = BlueprintGame(BlueprintSpec())
    sizes = game.build_all()
    buckets = CoarseBuckets()
    trainer = BlueprintTrainer(game, buckets, seed=args.seed)
    if args.resume:
        trainer.load(args.resume)
    setup_s = time.perf_counter() - t0
    run_start, stop = time.perf_counter(), "iteration target reached"
    history, last = [], snapshot(trainer)
    while trainer.iteration < args.iterations:
        if time.perf_counter() - run_start >= 60 * args.max_minutes:
            stop = f"wall-clock limit of {args.max_minutes} minutes reached"
            break
        step = min(args.checkpoint_every - trainer.iteration % args.checkpoint_every, args.iterations - trainer.iteration)
        chunk_end = time.perf_counter() + 60 * args.max_minutes - (time.perf_counter() - run_start)
        trainer.iterate(step, callback=None)
        if trainer.iteration % args.checkpoint_every == 0 or trainer.iteration >= args.iterations:
            path = trainer.save(out / f"checkpoint-{trainer.iteration}.npz")
            now = snapshot(trainer)
            history.append({"iteration": trainer.iteration, "elapsed_s": round(trainer.elapsed, 1),
                            "strategy_movement_l1": movement(last, now, trainer), **trainer.stats(),
                            "checkpoint": path.as_posix()})
            last = now
            print(f"iter {trainer.iteration:>7}  {trainer.elapsed:7.0f}s  tables {len(trainer.regret)}  "
                  f"movement {history[-1]['strategy_movement_l1']}", flush=True)
        del chunk_end
    final = trainer.save(out / "checkpoint.npz")
    report = {"schema": "pokerlab.plo.blueprint-train/1", "spec": game.spec.describe(), "tree": sizes,
              "buckets": buckets.describe, "bucket_counts": buckets.sizes, "seed": args.seed,
              "resumed_from": args.resume, "stopped_because": stop, "iterations": trainer.iteration,
              "setup_s": round(setup_s, 2), "train_s": round(trainer.elapsed, 1),
              "ms_per_iteration": round(1000 * trainer.elapsed / max(trainer.iteration, 1), 2),
              "stats": trainer.stats(), "history": history, "preflop_small_blind_first_action": preflop_summary(trainer),
              "checkpoint": final.as_posix(), "memory": peak_memory_mib(), "environment": started_env,
              "algorithm": "external-sampling MCCFR, alternating players, linear weighting of regrets and "
                           "average strategy (opponent nodes), one sampled deal per iteration",
              "scope": "minimal blueprint: 20bb effective, limited sizes, coarse imperfect-recall abstraction; "
                       "no exploitability is claimed for the full game"}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"done: {trainer.iteration} iterations ({stop}); report {out / 'report.json'}")


if __name__ == "__main__":
    main()
