"""Controlled turn-start positions for the joint turn + river agent, with checks and full decision logs.

Every scenario fixes the hole cards, the runout and the preflop/flop line (button raises to 3bb,
big blind calls; flop big blind checks, button bets 2/3 pot, big blind calls), so the agent's
first decision is on the turn of a known position.  The opponent then plays a scripted policy:

* passive          checks/calls (only in-tree actions): turn and river come from one joint solve;
* off_tree_turn    opens the turn with min bet + 7 chips: the joint game is re-solved on the turn;
* off_tree_river   opens the river with min bet + 7 chips: independent river fallback, logged.

For every joint decision the script re-reads the stored joint solution and checks that the logged
probabilities are exactly that solution's entry for (node, river card, hand).

    python scripts/plo_turn_agent_demo.py --output outputs/plo/v5/turn-agent-controlled
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_plo_turn_agent import OffTree, Passive, RUNOUT, controlled_hand  # noqa: E402

from pokerlab.plo.cards import format_cards  # noqa: E402
from pokerlab.plo.engine import RIVER, TURN  # noqa: E402
from pokerlab.plo.evaluate import summarize_decisions  # noqa: E402
from pokerlab.plo.resources import environment, peak_memory_mib  # noqa: E402
from pokerlab.plo.turn_agent import JointTurnRiverAgent  # noqa: E402

SCENARIOS = {"passive": lambda: Passive(), "off_tree_turn": lambda: OffTree(TURN),
             "off_tree_river": lambda: OffTree(RIVER)}


def check(agent: JointTurnRiverAgent, decisions: list[dict]) -> list[dict]:
    """Logged probabilities vs the stored joint solution, per joint decision."""
    ctx, out = agent._ctx, []
    for d in decisions:
        if d["source"] != "joint-turn-river" or d["joint_solve_id"] != ctx.solve["id"]:
            continue
        look = d["strategy_lookup"]
        if look["street"] == "turn":
            expected = ctx.profile["turn"][ctx.game.turn_tree.find(look["turn_path"])][look["hand_index"]]
        else:
            leaf = ctx.game.turn_tree.find(look["turn_path"])
            rid = ctx.game.leaves[leaf].tree.find(look["river_path"])
            expected = ctx.profile["river"][(leaf, rid)][look["river_card_index"], look["hand_index"]]
        out.append({"street": look["street"], "matches_stored_solution": bool(
            np.array_equal(np.array(list(d["probabilities"].values())), expected))})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--range-samples", type=int, default=40)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    settings = {"range_samples": args.range_samples, "iterations": args.iterations, "workers": args.workers}
    report = {"schema": "pokerlab.plo.turn-agent-controlled/1", "settings": settings,
              "position": {"hero": "AsKsQdJd", "villain": "9c9d8c7h", "runout": format_cards(RUNOUT),
                           "line": "preflop button 3bb raise, big blind call; flop check, 2/3 pot bet, call; "
                                   "stacks 100bb, blinds 50/100"},
              "scenarios": []}
    with (out / "decisions.jsonl").open("w", encoding="utf-8") as log:
        for name, villain in SCENARIOS.items():
            for hero_is_button in (False, True):
                agent = JointTurnRiverAgent(seed=3, turn_river=settings)
                t = time.perf_counter()
                state = controlled_hand(agent, villain(), hero_is_button=hero_is_button)
                wall = time.perf_counter() - t
                decisions = [d for d in agent.decisions if d["street"] >= TURN]
                for d in agent.decisions:
                    log.write(json.dumps({"scenario": name, "hero_is_button": hero_is_button, **d}, default=str) + "\n")
                joint_ids = {d["joint_solve_id"] for d in decisions if d["source"] == "joint-turn-river"}
                rivers = [d for d in decisions if d["street"] == RIVER]
                row = {"scenario": name, "hero": "button (IP)" if hero_is_button else "big blind (OOP)",
                       "decisions": [{"street": {TURN: "turn", RIVER: "river"}[d["street"]], "source": d["source"],
                                      "label": d.get("label"), "joint_solve_id": d.get("joint_solve_id"),
                                      "joint_strategy_in_force": d.get("joint_strategy_in_force"),
                                      "fallbacks": [f["kind"] for f in d.get("fallbacks", [])],
                                      "probabilities": d.get("probabilities")} for d in decisions],
                       "joint_solves_used": sorted(joint_ids),
                       "river_from_same_joint_solve_as_turn": bool(rivers) and all(
                           r["source"] == "joint-turn-river" and r["joint_solve_id"] in joint_ids for r in rivers),
                       "probability_checks": check(agent, decisions),
                       "summary": summarize_decisions(agent.decisions), "hero_net_chips": state.result.net[0],
                       "wall_s": round(wall, 1)}
                report["scenarios"].append(row)
                print(name, row["hero"], [(d["street"], d["source"], d["label"], d["fallbacks"]) for d in row["decisions"]],
                      "same solve on river:", row["river_from_same_joint_solve_as_turn"],
                      "checks:", [c["matches_stored_solution"] for c in row["probability_checks"]],
                      f"{wall:.0f}s", flush=True)
    report["memory"] = peak_memory_mib()
    report["environment"] = environment()
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out / 'report.json'}")


if __name__ == "__main__":
    main()
