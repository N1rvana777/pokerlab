"""Check the inclusion-exclusion showdown against exact sums on full PLO4 river ranges.

Both players hold every PLO4 hand that avoids the board (178,365 each).  A seeded,
non-uniform, sparse random reach vector is used for the opponent.  Modes:

    --rows N   N randomly chosen hands per player; exact sums over every opponent hand
    --full     every hand of both players; exact sums over every opponent hand (slow)

Always also runs the uniform-reach count check (every hand must see C(43,4) = 123,410
compatible opponent hands).  "Exact sums" are dense row-by-row computations with
bitmask card removal and integer rank comparison, chunked to bound memory; they share
no code with the inclusion-exclusion index.

    python scripts/plo_verify_showdown.py --rows 2000 --output outputs/plo/verify/showdown-rows.json
"""
from __future__ import annotations

import argparse
import json
import time
from math import comb
from pathlib import Path

import numpy as np

from pokerlab.plo.cards import all_hands, parse_cards
from pokerlab.plo.evaluator import plo_rank_batch
from pokerlab.plo.resources import environment, peak_memory_mib
from pokerlab.plo.subgame.showdown import InclusionExclusionShowdown, hand_masks


def exact_masses(rows: np.ndarray, masks: np.ndarray, strength: np.ndarray, opp_masks: np.ndarray,
                 opp_strength: np.ndarray, reach: np.ndarray, chunk: int = 128):
    compat = np.empty(len(rows))
    win = np.empty(len(rows))
    for start in range(0, len(rows), chunk):
        idx = rows[start:start + chunk]
        ok = (masks[idx, None] & opp_masks[None, :]) == 0
        s = strength[idx, None]
        compat[start:start + len(idx)] = ok @ reach
        win[start:start + len(idx)] = ((ok & (s > opp_strength[None, :])) @ reach
                                       + 0.5 * ((ok & (s == opp_strength[None, :])) @ reach))
    return compat, win


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rows", type=int)
    mode.add_argument("--full", action="store_true")
    parser.add_argument("--board", default="Ah 8h 8d 5c 2h")
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")

    start = time.perf_counter()
    board = parse_cards(args.board)
    hands = all_hands(4, board)
    strength = plo_rank_batch(hands, board)
    masks = hand_masks(hands)
    ie = InclusionExclusionShowdown(hands, strength, hands, strength)
    rng = np.random.default_rng(args.seed)
    n = len(hands)

    uniform_compat, _ = ie.masses(0, np.ones(n), need_win=False)
    count_check = {"expected": comb(52 - 9, 4),
                   "min": float(uniform_compat.min()), "max": float(uniform_compat.max())}

    results = []
    for player in (0, 1):
        reach = rng.random(n) ** 2 * (rng.random(n) < 0.7)
        rows = np.arange(n) if args.full else np.sort(rng.choice(n, size=args.rows, replace=False))
        t0 = time.perf_counter()
        compat_ie, win_ie = ie.masses(player, reach)
        t1 = time.perf_counter()
        compat_x, win_x = exact_masses(rows, masks, strength, masks, strength, reach)
        t2 = time.perf_counter()
        scale = float(reach.sum())
        results.append({
            "player": player, "rows_checked": int(len(rows)), "opponent_hands_per_row": n,
            "reach": "u^2 * Bernoulli(0.7), u ~ U[0,1), seeded",
            "max_abs_diff_compat": float(np.abs(compat_ie[rows] - compat_x).max()),
            "max_abs_diff_win": float(np.abs(win_ie[rows] - win_x).max()),
            "max_rel_diff_to_total_reach": float(max(np.abs(compat_ie[rows] - compat_x).max(),
                                                     np.abs(win_ie[rows] - win_x).max()) / scale),
            "inclusion_exclusion_s": round(t1 - t0, 3), "exact_s": round(t2 - t1, 3)})
        print(results[-1], flush=True)

    report = {"schema": "pokerlab.plo.verify-showdown/1", "board": args.board, "hands_per_player": n,
              "mode": "full" if args.full else f"rows={args.rows}", "seed": args.seed,
              "uniform_count_check": count_check, "results": results,
              "wall_s": round(time.perf_counter() - start, 1), "memory": peak_memory_mib(),
              "environment": environment()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
