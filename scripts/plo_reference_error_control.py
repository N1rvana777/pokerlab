"""Where does the sampled-strategy error on the reference range come from?  One fixed problem.

Problem: the budget-diagnostics reference game for the paired_flush board (seed 7, 2,000 baseline-v1
posterior draws per player, counts as weights, default four-size tree with two raises).

  A  Solve the reference game once (DCFR, 500 iterations) and save its average strategy.  An existing
     file is reused after checking the game fingerprint.
  B  k = N control.  Every reference hand, with its own weight, goes through exactly the export /
     mapping / evaluation path of the diagnostics (``extend_profile`` + ``evaluate_profile``):
       B1  the saved reference strategy evaluated directly;
       B2  the same strategy passed through ``extend_profile`` (sampled game = reference game);
       B3  both instance paths (reference: showdown "auto"; sampled: showdown "dense") solved for 50
           iterations from scratch and compared bit for bit.
  C  Decomposition at k = 150 draws and 200 iterations, the agent's budget, with the diagnostics' seed:
       C0  in-sample exploitability of the sampled solve;
       C1  mapping only: exact reference strategies for the sampled hands, nearest-rank copies for the rest;
       C2  sampling only: sampled-solve strategies for the sampled hands, exact reference strategies for
           every other hand;
       C3  both (the number the diagnostics reported).
     Each case also reports, per player, how much that player's strategy loses against a best responder
     relative to the reference value (the two losses add up to NashConv).

    python scripts/plo_reference_error_control.py --output outputs/plo/v5/refctl
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

from pokerlab.plo.cards import parse_cards  # noqa: E402
from pokerlab.plo.evaluator import plo_rank_batch  # noqa: E402
from pokerlab.plo.resources import environment, peak_memory_mib  # noqa: E402
from pokerlab.plo.subgame.cfr import CFRSolver, SolverConfig, evaluate_profile  # noqa: E402
from pokerlab.plo.subgame.instance import plo_river_instance  # noqa: E402

BOARD_NAME, SEED, DRAWS = "paired_flush", 7, 2000


def save_profile(path: Path, profile: dict, fingerprint: str, iterations: int) -> None:
    np.savez_compressed(path, fingerprint=np.array(fingerprint), iterations=np.array(iterations),
                        **{f"node_{nid}": strat for nid, strat in profile.items()})


def load_profile(path: Path, fingerprint: str) -> tuple[dict, int]:
    data = np.load(path)
    if str(data["fingerprint"]) != fingerprint:
        raise SystemExit(f"{path} belongs to a different reference game")
    return ({int(k[5:]): data[k] for k in data.files if k.startswith("node_")}, int(data["iterations"]))


def hand_index(instance, player: int) -> dict:
    return {tuple(sorted(h)): i for i, h in enumerate(instance.hands[player].tolist())}


def losses(metrics: dict, value0: float, pot: float) -> dict:
    """Loss of each player's strategy against a best responder, % of the pot (sums to NashConv)."""
    br0, br1 = metrics["best_response_value"]
    return {"player0_strategy": 100 * (value0 - (pot - br1)) / pot,
            "player1_strategy": 100 * ((pot - value0) - (pot - br0)) / pot}


def summarise(name: str, metrics: dict, value0: float, pot: float) -> dict:
    row = {"case": name, "exploitability_pct_pot": metrics["exploitability_pct_pot"],
           "loss_pct_pot": losses(metrics, value0, pot), "value0": metrics["value"][0]}
    print(f"{name:<44} exploitability {row['exploitability_pct_pot']:8.4f}% pot  "
          f"losses P0 {row['loss_pct_pot']['player0_strategy']:7.3f}  P1 {row['loss_pct_pot']['player1_strategy']:7.3f}",
          flush=True)
    return row


def first_nodes(reference) -> dict:
    """First decision node of each player (root for OOP, after the check for IP)."""
    nodes = {}
    for nid in reference.tree.decision_nodes():
        nodes.setdefault(reference.tree.nodes[nid].player, nid)
    return nodes


def source_index(sampled, reference) -> dict:
    """Which sampled hand each reference hand copies, read back through extend_profile itself."""
    nodes = first_nodes(reference)
    fake = {nid: np.arange(sampled.size(p), dtype=np.float64)[:, None] for p, nid in nodes.items()}
    ext = extend_profile(sampled, reference, fake)
    return {p: ext[nid][:, 0].astype(np.int64) for p, nid in nodes.items()}


def mapping_stats(sampled, reference, sigma) -> list[dict]:
    """How the extension rule assigns strategies, and how far the copies are from each hand's own strategy."""
    board = parse_cards(reference.description["board"])
    src = source_index(sampled, reference)
    nodes = first_nodes(reference)
    ref_of_sample = [np.array([hand_index(reference, p)[tuple(sorted(h))] for h in sampled.hands[p].tolist()])
                     for p in (0, 1)]
    out = []
    for p in (0, 1):
        r_keys = plo_rank_batch(reference.hands[p], board)
        s_keys = plo_rank_batch(sampled.hands[p], board)
        in_sample = np.isin(np.arange(reference.size(p)), ref_of_sample[p])
        copied = ~in_sample
        same_key = s_keys[src[p]] == r_keys
        other_cat = (s_keys[src[p]] >> 20) != (r_keys >> 20)
        w = reference.weights[p]
        own = sigma[nodes[p]]                                   # each hand's exact strategy at the node
        copy = sigma[nodes[p]][ref_of_sample[p][src[p]]]       # exact strategy of the hand it copies
        tv = 0.5 * np.abs(own - copy).sum(axis=1)
        out.append({"player": p, "reference_hands": int(reference.size(p)), "sampled_hands": int(sampled.size(p)),
                    "reference_hands_in_sample": int(in_sample.sum()),
                    "reference_weight_in_sample": float(w[in_sample].sum() / w.sum()),
                    "copied_hands": int(copied.sum()),
                    "copied_with_identical_rank_key": int((copied & same_key).sum()),
                    "copied_from_other_category": int((copied & other_cat).sum()),
                    "first_node": nodes[p],
                    "first_node_weighted_tv_copy_vs_own_exact": float((w[copied] * tv[copied]).sum() / w[copied].sum()),
                    "first_node_weighted_tv_copy_vs_own_exact_same_rank_key":
                        float((w[copied & same_key] * tv[copied & same_key]).sum() / max(w[copied & same_key].sum(), 1e-300))})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--reference-profile", help="saved reference strategy to reuse")
    parser.add_argument("--reference-iterations", type=int, default=500)
    parser.add_argument("--k", type=int, default=150)
    parser.add_argument("--iterations", type=int, default=200)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    board = BOARDS[BOARD_NAME]
    started = time.perf_counter()
    ref_ranges = reference_ranges(board, DRAWS, SEED)
    reference = plo_river_instance(spec(board, ref_ranges))
    pot = float(reference.pot)
    report = {"schema": "pokerlab.plo.reference-error-control/1",
              "problem": {"board_name": BOARD_NAME, "board": board, "seed": SEED, "reference_draws": DRAWS,
                          "reference_range_sizes": [reference.size(0), reference.size(1)],
                          "tree": reference.tree.summary(), "showdown": reference.description["showdown"],
                          "fingerprint": reference.fingerprint},
              "extension_rule": "unsampled reference hands copy the strategy of the sampled hand with the nearest "
                                "river rank key; sampled hands keep their own strategy (scripts/plo_budget_diagnostics.py)"}

    # A. reference strategy (reused when available)
    source = Path(args.reference_profile) if args.reference_profile else None
    if source and source.exists():
        sigma, iters = load_profile(source, reference.fingerprint)
        report["reference_solve"] = {"reused": source.as_posix(), "iterations": iters}
    else:
        t = time.perf_counter()
        solver = CFRSolver(reference, SolverConfig("dcfr"))
        solver.run(args.reference_iterations)
        sigma, iters = solver.average_profile(), args.reference_iterations
        path = out / f"reference-dcfr{iters}.npz"
        save_profile(path, sigma, reference.fingerprint, iters)
        report["reference_solve"] = {"saved": path.as_posix(), "iterations": iters,
                                     "solve_s": round(time.perf_counter() - t, 1)}
    ref_metrics = evaluate_profile(reference, sigma)
    value0 = ref_metrics["value"][0]
    report["reference_solve"]["value0"] = value0
    rows = [summarise("B1 reference strategy, direct", ref_metrics, value0, pot)]

    # B. k = N control through the same adapter
    identity = plo_river_instance(spec(board, ref_ranges, "dense"))
    adapted = extend_profile(identity, reference, sigma)
    max_diff = max(float(np.abs(adapted[n] - sigma[n]).max()) for n in sigma)
    rows.append(summarise("B2 reference strategy through extend_profile", evaluate_profile(reference, adapted),
                          value0, pot))
    a, b = CFRSolver(reference, SolverConfig("dcfr")), CFRSolver(identity, SolverConfig("dcfr"))
    a.run(50)
    b.run(50)
    pa, pb = a.average_profile(), extend_profile(identity, reference, b.average_profile())
    bitwise = all(np.array_equal(pa[n], pb[n]) for n in pa)
    report["k_equals_n_control"] = {
        "identity_instance_showdown": identity.description["showdown"],
        "same_fingerprint_as_reference": identity.fingerprint == reference.fingerprint,
        "adapter_max_abs_strategy_change": max_diff,
        "fresh_50_iteration_solves_bitwise_equal_after_adapter": bitwise}
    print("k=N adapter max |change|", max_diff, "| fresh 50-iteration solves bitwise equal:", bitwise, flush=True)

    # C. decomposition at the agent's budget
    sub = subsample(ref_ranges, args.k, SEED)
    sampled = plo_river_instance(spec(board, sub, "dense"))
    solver = CFRSolver(sampled, SolverConfig("dcfr"))
    t = time.perf_counter()
    solver.run(args.iterations)
    sigma_s = solver.average_profile()
    report["sampled_solve"] = {"k": args.k, "iterations": args.iterations,
                               "sampled_range_sizes": [sampled.size(0), sampled.size(1)],
                               "solve_s": round(time.perf_counter() - t, 2),
                               "mapping": mapping_stats(sampled, reference, sigma)}
    in_sample = evaluate_profile(sampled, sigma_s)
    report["c0_in_sample_exploitability_pct_pot"] = in_sample["exploitability_pct_pot"]
    print(f"C0 in-sample exploitability {in_sample['exploitability_pct_pot']:.4f}% pot", flush=True)
    # exact reference strategies of the sampled hands, in the sampled game's hand order
    ref_rows = [np.array([hand_index(reference, p)[tuple(sorted(h))] for h in sampled.hands[p].tolist()])
                for p in (0, 1)]
    sigma_star_on_sample = {n: s[ref_rows[reference.tree.nodes[n].player]] for n, s in sigma.items()}
    rows.append(summarise("C1 mapping only (exact strategies of sampled hands)",
                          evaluate_profile(reference, extend_profile(sampled, reference, sigma_star_on_sample)),
                          value0, pot))
    hybrid = {}
    for n, s in sigma.items():
        p = reference.tree.nodes[n].player
        hybrid[n] = s.copy()
        hybrid[n][ref_rows[p]] = sigma_s[n]
    rows.append(summarise("C2 sampling only (others exact)", evaluate_profile(reference, hybrid), value0, pot))
    rows.append(summarise("C3 sampling + mapping (diagnostics)",
                          evaluate_profile(reference, extend_profile(sampled, reference, sigma_s)), value0, pot))
    report["cases"] = rows
    report["wall_s"] = round(time.perf_counter() - started, 1)
    report["memory"] = peak_memory_mib()
    report["environment"] = environment()
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out / 'report.json'}")


if __name__ == "__main__":
    main()
