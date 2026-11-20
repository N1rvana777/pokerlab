"""How far is the blueprint's turn/river strategy from a local equilibrium on its own ranges?

One public line of the blueprint game (20bb; preflop button raises to 3bb, big blind calls; flop big
blind checks, button bets pot, big blind calls) on a fixed flop and turn.  Both players' turn ranges are
the blueprint's own Bayes posterior (``BlueprintPolicy.log_likelihood``), represented by seeded draws.
The turn + river subgame with the blueprint's postflop action abstraction is then:
  * solved exactly with the joint turn + river solver (the search component);
  * played with the blueprint's bucketed turn and river strategies, mapped to every hand of the ranges
    (turn bucket on the turn board, river bucket on each river card), and evaluated in the same subgame.
Both are reported as exploitability in that subgame; the gap is what decision-time search can recover.

    python scripts/plo_blueprint_local_check.py --checkpoint outputs/plo/v6/blueprint-v0/checkpoint.npz \
        --output outputs/plo/v6/blueprint-local-check
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from pokerlab.plo.baseline import every_hand
from pokerlab.plo.blueprint import RIVER, TURN, BlueprintPolicy, coarse_hand_buckets
from pokerlab.plo.cards import format_cards, parse_cards
from pokerlab.plo.engine import ActionRecord, ActionType
from pokerlab.plo.resources import environment, peak_memory_mib
from pokerlab.plo.river_agent import sample_ranges
from pokerlab.plo.subgame.cfr import SolverConfig
from pokerlab.plo.subgame.tree import SHOWDOWN
from pokerlab.plo.subgame.turn import TurnRiverSolver, evaluate_turn_profile, turn_river_game

BUTTON = 0                 # seat 0 = button / small blind, seat 1 = big blind (blueprint tree player 0)
LINE = [(0, 0, ActionType.RAISE, 300), (0, 1, ActionType.CALL, 300),
        (1, 1, ActionType.CHECK, 0), (1, 0, ActionType.BET, 600), (1, 1, ActionType.CALL, 600)]


def history():
    return [ActionRecord(street, seat, kind, 0, to, False, False) for street, seat, kind, to in LINE]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--board", default="Ks 9h 7d 4c")
    parser.add_argument("--draws", type=int, default=300)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    started = environment()
    policy = BlueprintPolicy.load(args.checkpoint)
    game_bp = policy.game
    board = tuple(parse_cards(args.board))
    hands = every_hand()
    candidates = hands[~np.isin(hands, np.asarray(board)).any(axis=1)]
    # turn position in the blueprint tree after the line
    steps, key, node, street = policy.walk(history(), BUTTON, TURN)
    assert street == TURN and node.id == 0, "the line must end at the start of the turn"
    turn_cfg = game_bp.trees[key].config
    # blueprint posterior for both tree players (0 = big blind = seat 1)
    posterior, traces = {}, {}
    for tree_player, seat in ((0, 1), (1, 0)):
        logw, trace = policy.log_likelihood(history(), BUTTON, seat, board, candidates, before=TURN)
        w = np.exp(logw - logw.max())
        posterior[tree_player] = (candidates, w / w.sum())
        traces[tree_player] = trace
    ranges, info = sample_ranges(posterior, args.draws, (args.seed, 0), None, None)
    s = game_bp.spec.postflop
    spec = {"board": args.board, "big_blind": game_bp.spec.big_blind, "pot": turn_cfg.pot,
            "stacks": [turn_cfg.effective_stack, turn_cfg.effective_stack],
            "ranges": [{"hands": [format_cards(h) for h in ranges[p][0]], "weights": ranges[p][1].tolist()}
                       for p in (0, 1)],
            "bet_sizes": list(s.bet_sizes), "raise_sizes": list(s.raise_sizes),
            "include_min_raise": s.include_min_raise, "include_max_raise": s.include_max_raise,
            "turn_max_raises": s.max_raises, "river_max_raises": s.max_raises, "min_bet": game_bp.spec.big_blind,
            "river_cards": "all"}
    game = turn_river_game(spec)
    assert [n.actions for n in game.turn_tree.nodes] == [n.actions for n in game_bp.trees[key].nodes]
    # exact local solve
    t = time.perf_counter()
    solver = TurnRiverSolver(game, SolverConfig("dcfr"))
    solver.run(args.iterations)
    exact = evaluate_turn_profile(game, solver.average_profile())
    exact_s = time.perf_counter() - t
    # blueprint strategy mapped to every hand
    turn_b = [coarse_hand_buckets(policy.buckets, TURN, board, game.hands[p]) for p in (0, 1)]
    river_b = [np.stack([coarse_hand_buckets(policy.buckets, RIVER, board + (int(c),), game.hands[p])
                         for c in game.river_cards]) for p in (0, 1)]
    prof, untrained = {"turn": {}, "river": {}}, 0
    for nid in game.turn_tree.decision_nodes():
        n = game.turn_tree.nodes[nid]
        k = (key, nid)
        if k in policy.trainer.strategy_sum:
            prof["turn"][nid] = policy.trainer.average(*k)[turn_b[n.player]]
        else:
            untrained += 1
            prof["turn"][nid] = np.full((game.size(n.player), len(n.children)), 1.0 / len(n.children))
    for leaf_id, leaf in game.leaves.items():
        if leaf.tree is None:
            continue
        rkey = game_bp.next_street(key, game_bp.trees[key].nodes[leaf_id])
        assert [x.actions for x in game_bp.trees[rkey].nodes] == [x.actions for x in leaf.tree.nodes]
        for rid in leaf.tree.decision_nodes():
            n = leaf.tree.nodes[rid]
            k = (rkey, rid)
            if k in policy.trainer.strategy_sum:
                table = policy.trainer.average(*k)
                prof["river"][(leaf_id, rid)] = table[river_b[n.player]]
            else:
                untrained += 1
                prof["river"][(leaf_id, rid)] = np.full((len(game.river_cards), game.size(n.player), len(n.children)),
                                                        1.0 / len(n.children))
    bp = evaluate_turn_profile(game, prof)
    report = {"schema": "pokerlab.plo.blueprint-local-check/1", "checkpoint": args.checkpoint,
              "blueprint_iterations": policy.trainer.iteration, "board": args.board,
              "line": [[st, seat, kind.value, to] for st, seat, kind, to in LINE],
              "turn_pot": turn_cfg.pot, "turn_stack": turn_cfg.effective_stack,
              "range_model": "blueprint posterior of the preflop and flop actions", "range_draws": args.draws,
              "range_info": info, "range_trace": traces, "range_sizes": [game.size(0), game.size(1)],
              "nodes": game.nodes_summary(), "untrained_blueprint_nodes": untrained,
              "exact_local_solve": {"iterations": args.iterations, "seconds": round(exact_s, 1),
                                    "exploitability_pct_pot": exact["exploitability_pct_pot"], "value0": exact["value"][0]},
              "blueprint_strategy_in_subgame": {"exploitability_pct_pot": bp["exploitability_pct_pot"],
                                                "value0": bp["value"][0],
                                                "best_response_value": bp["best_response_value"]},
              "memory": peak_memory_mib(), "environment": started,
              "scope": ("one public line and board of the 20bb blueprint game; ranges are draws from the blueprint's "
                        "own posterior; says nothing about other lines or the full game")}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"exact local {exact['exploitability_pct_pot']:.4f}% pot, blueprint {bp['exploitability_pct_pot']:.3f}% pot "
          f"(ranges {report['range_sizes']}, untrained nodes {untrained}); report {out / 'report.json'}")


if __name__ == "__main__":
    main()
