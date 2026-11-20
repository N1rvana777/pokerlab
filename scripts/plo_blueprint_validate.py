"""Check the blueprint's external-sampling MCCFR against the exact full-width solvers.

With identity buckets (every hand, and on the river every river card, is its own information set) the
blueprint trainer is plain ES-MCCFR on the subgame, so its average strategy must converge in the
original game.  Two subgames reuse existing LP-checked instances:

  river  examples/plo/river_tiny_lp.json   (8 x 8 hands, one street)
  turn   examples/plo/turn_tiny_lp.json    (6 x 6 hands, turn tree + 48 sampled river cards + river trees)

For each, the trainer's tables are mapped onto the exact solver's node ids and evaluated with the exact
best responses (``evaluate_profile`` / ``evaluate_turn_profile``) at a few iteration counts.

    python scripts/plo_blueprint_validate.py --output outputs/plo/v6/blueprint-validate
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from pokerlab.plo.blueprint import (
    RIVER, TURN, BlueprintGame, BlueprintSpec, BlueprintTrainer, IdentityBuckets, StreetSizes,
)
from pokerlab.plo.cards import parse_cards
from pokerlab.plo.evaluate import load_json
from pokerlab.plo.resources import environment, peak_memory_mib
from pokerlab.plo.subgame.cfr import evaluate_profile
from pokerlab.plo.subgame.instance import _chips, plo_river_instance
from pokerlab.plo.subgame.reference import solve_sequence_form
from pokerlab.plo.subgame.tree import SHOWDOWN
from pokerlab.plo.subgame.turn import evaluate_turn_profile, turn_river_game
from pokerlab.plo.subgame.turn_reference import solve_turn_sequence_form


def sizes(spec: dict) -> StreetSizes:
    return StreetSizes(tuple(spec.get("bet_sizes", ("1/3", "1/2", "2/3", "1"))),
                       tuple(spec.get("raise_sizes", ("1/3", "1/2", "2/3", "1"))),
                       bool(spec.get("include_min_raise", True)), bool(spec.get("include_max_raise", True)),
                       int(spec.get("max_raises", 2)))


def table_or_uniform(trainer, key, nid, rows, actions):
    if (key, nid) in trainer.strategy_sum:
        return trainer.average(key, nid)
    return np.full((rows, actions), 1.0 / actions)


def river_profile(trainer, game, inst):
    key = game.root
    tree = game.trees[key]
    return {nid: table_or_uniform(trainer, key, nid, inst.size(tree.nodes[nid].player), len(tree.nodes[nid].children))
            for nid in tree.decision_nodes()}


def turn_profile(trainer, game, exact):
    key = game.root
    tree = game.trees[key]
    prof = {"turn": {}, "river": {}}
    for nid in tree.decision_nodes():
        node = tree.nodes[nid]
        prof["turn"][nid] = table_or_uniform(trainer, key, nid, exact.size(node.player), len(node.children))
    cards = len(exact.river_cards)
    for node in tree.nodes:
        if node.kind != SHOWDOWN:
            continue
        nxt = game.next_street(key, node)
        if nxt is None:
            continue
        rtree = game.trees[nxt]
        for rid in rtree.decision_nodes():
            rnode = rtree.nodes[rid]
            n = exact.size(rnode.player)
            arr = table_or_uniform(trainer, nxt, rid, cards * n, len(rnode.children))
            prof["river"][(node.id, rid)] = arr.reshape(cards, n, len(rnode.children))
    return prof


def run(kind: str, path: str, checkpoints: list[int], seed: int) -> dict:
    spec = load_json(path)
    bb = int(spec.get("big_blind", 100))
    stacks = _chips(spec, "stacks", bb)
    if kind == "river":
        exact = plo_river_instance(spec)
        lp = solve_sequence_form(exact)
        bspec = BlueprintSpec(big_blind=bb, small_blind=bb // 2, stack=int(min(stacks)), postflop=sizes(spec),
                              start_street=RIVER, board=tuple(parse_cards(spec["board"])), pot=exact.pot)
        buckets = IdentityBuckets(exact.hands)
        evaluate = lambda tr, g: evaluate_profile(exact, river_profile(tr, g, exact))
    else:
        exact = turn_river_game(spec)
        lp = solve_turn_sequence_form(exact)
        bspec = BlueprintSpec(big_blind=bb, small_blind=bb // 2, stack=exact.effective_stack, postflop=sizes(spec),
                              start_street=TURN, board=tuple(parse_cards(spec["board"])), pot=exact.pot,
                              turn_max_raises=int(spec.get("turn_max_raises", 1)),
                              river_max_raises=int(spec.get("river_max_raises", 1)))
        buckets = IdentityBuckets(exact.hands, river_cards=exact.river_cards)
        evaluate = lambda tr, g: evaluate_turn_profile(exact, turn_profile(tr, g, exact))
    game = BlueprintGame(bspec)
    trainer = BlueprintTrainer(game, buckets, ranges=((exact.hands[0], exact.weights[0]),
                                                      (exact.hands[1], exact.weights[1])), seed=seed)
    rows, done = [], 0
    for target in checkpoints:
        trainer.iterate(target - done)
        done = target
        m = evaluate(trainer, game)
        rows.append({"iterations": target, "seconds": round(trainer.elapsed, 1),
                     "exploitability_pct_pot": m["exploitability_pct_pot"],
                     "value0_minus_lp": m["value"][0] - lp["value0"]})
        print(f"{kind:<5} {target:>7} it  {m['exploitability_pct_pot']:8.4f}% pot  "
              f"value0-LP {rows[-1]['value0_minus_lp']:+.3f}  ({trainer.elapsed:.0f}s)", flush=True)
    return {"kind": kind, "game": path, "lp_value0": lp["value0"], "trajectory": rows, "trainer": trainer.stats(),
            "tree": game.build_all()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--river-checkpoints", type=int, nargs="*", default=[1000, 5000, 20000, 60000])
    parser.add_argument("--turn-checkpoints", type=int, nargs="*", default=[2000, 10000, 40000, 100000])
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    started = environment()
    t = time.perf_counter()
    report = {"schema": "pokerlab.plo.blueprint-validate/1",
              "runs": [run("river", "examples/plo/river_tiny_lp.json", args.river_checkpoints, args.seed),
                       run("turn", "examples/plo/turn_tiny_lp.json", args.turn_checkpoints, args.seed)],
              "wall_s": round(time.perf_counter() - t, 1), "memory": peak_memory_mib(), "environment": started}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out / 'report.json'}")


if __name__ == "__main__":
    main()
