"""Write a turn + river config whose ranges come from the baseline-v1 posterior after a fixed line.

Public line (seat 0 = big blind, out of position; seat 1 = button): preflop button raise, big
blind call; flop big blind check, button bet, big blind call.  The posterior is uniform over the
hands avoiding the 4 turn cards, times baseline-v1's category likelihood of each action.

Range choice is explicit and reported in the config:
  --top N       the N hands with the highest posterior weight per player, posterior weights kept
                (renormalised); the covered posterior mass is written as ``coverage``;
  --sample N    N seeded multinomial draws per player, counts as weights (as in turn_small.json).

    python scripts/plo_turn_ranges.py --top 600 --stacks-bb 10 --output examples/plo/turn_top600.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from pokerlab.plo.baseline import BaselinePolicy, every_hand
from pokerlab.plo.cards import format_cards, parse_cards
from pokerlab.plo.engine import ActionType
from pokerlab.plo.public import PublicDecision
from pokerlab.plo.river_agent import posterior_log_weights

LINE = [(0, 1, ActionType.RAISE, True, True), (0, 0, ActionType.CALL, True, True),
        (1, 0, ActionType.CHECK, False, True), (1, 1, ActionType.BET, False, True),
        (1, 0, ActionType.CALL, True, True)]
LINE_TEXT = ("preflop button raise / big blind call; flop big blind check, button bet, big blind call. "
             "Player 0 = big blind (out of position).")


def posterior(board: tuple[int, ...]) -> tuple[np.ndarray, list[np.ndarray]]:
    hands = every_hand()
    candidates = hands[~np.isin(hands, np.asarray(board)).any(axis=1)]
    decisions = [PublicDecision(street, seat, action, 0, facing, can_raise, 0, 0)
                 for street, seat, action, facing, can_raise in LINE]
    policy, out = BaselinePolicy(), []
    for seat in (0, 1):
        logw, _ = posterior_log_weights(policy, decisions, seat, board, candidates)
        w = np.exp(logw - logw.max())
        out.append(w / w.sum())
    return candidates, out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", default="Ks 9h 7d 4c")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--top", type=int)
    group.add_argument("--sample", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pot-bb", type=float, default=10)
    parser.add_argument("--stacks-bb", type=float, default=10)
    parser.add_argument("--turn-max-raises", type=int, default=1)
    parser.add_argument("--river-max-raises", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--showdown", default="auto")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    board = tuple(parse_cards(args.board))
    candidates, weights = posterior(board)
    ranges, coverage = [], []
    for player in (0, 1):
        w = weights[player]
        if args.top:
            idx = np.sort(np.argsort(-w, kind="stable")[:args.top])
            ranges.append({"hands": [format_cards(h) for h in candidates[idx]],
                           "weights": (w[idx] / w[idx].sum()).tolist()})
            coverage.append(float(w[idx].sum()))
        else:
            rng = np.random.default_rng([args.seed, player])
            idx, counts = np.unique(rng.choice(len(w), size=args.sample, p=w), return_counts=True)
            ranges.append({"hands": [format_cards(h) for h in candidates[idx]], "weights": counts.tolist()})
            coverage.append(float(w[idx].sum()))
    method = (f"top {args.top} hands by posterior weight per player, posterior weights renormalised"
              if args.top else f"{args.sample} seeded multinomial draws per player (seed {args.seed}), counts as weights")
    config = {"name": out.stem, "board": args.board, "big_blind": 100, "pot_bb": args.pot_bb,
              "stacks_bb": [args.stacks_bb, args.stacks_bb],
              "turn_max_raises": args.turn_max_raises, "river_max_raises": args.river_max_raises,
              "river_cards": "all", "showdown": args.showdown,
              "solver": {"algorithm": "dcfr", "iterations": args.iterations},
              "range_source": f"baseline-v1 posterior after: {LINE_TEXT} Range: {method}.",
              "range_coverage_posterior_mass": coverage,
              "ranges": ranges}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(config, indent=1), encoding="utf-8")
    print(f"wrote {out}: hands {[len(r['hands']) for r in ranges]}, posterior mass covered "
          f"{[round(c, 4) for c in coverage]}")


if __name__ == "__main__":
    main()
