"""Command line for the PLO module.

    python -m pokerlab.plo status
    python -m pokerlab.plo solve-river CONFIG --output DIR [--iterations N] [--resume CKPT]
    python -m pokerlab.plo solve-turn CONFIG --output DIR [--iterations N] [--resume CKPT] [--spliced-baseline]
    python -m pokerlab.plo evaluate CONFIG --output REPORT.json
    python -m pokerlab.plo simulate CONFIG --output DIR
    python -m pokerlab.plo query CONFIG CHECKPOINT [--history check,bet:660] [--hand AsKdQh2c]

Outputs are never overwritten: pick a new path for every run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from pokerlab.plo.evaluate import evaluate_match, evaluate_river, load_json, solver_config
from pokerlab.plo.resources import Meter, environment
from pokerlab.plo.status import format_table
from pokerlab.plo.subgame.cfr import CFRSolver, evaluate_profile
from pokerlab.plo.subgame.instance import plo_river_instance
from pokerlab.plo.subgame.policy import SubgamePolicy
from pokerlab.plo.subgame.reference import solve_sequence_form


def _resolve(path: str, base: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    return base / candidate


def _subgame_spec(cfg: dict, base: Path) -> dict:
    spec = cfg.get("subgame", cfg)
    return load_json(_resolve(spec, base)) if isinstance(spec, str) else spec


def _fresh_dir(path: str) -> Path:
    out = Path(path)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"refusing to overwrite: {out} exists and is not empty")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_json(path: Path, data: dict) -> None:
    if path.exists():
        raise SystemExit(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(partial, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_solve_river(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    cfg = load_json(config_path)
    spec = _subgame_spec(cfg, config_path.parent)
    options = dict(cfg.get("solver", {}))
    for key in ("algorithm", "seed"):
        if getattr(args, key) is not None:
            if args.resume:
                raise SystemExit(f"--{key} cannot be combined with --resume: the checkpoint's config is used")
            options[key] = getattr(args, key)
    iterations = int(args.iterations if args.iterations is not None else options.get("iterations", 1000))
    if iterations < 1:
        raise SystemExit("--iterations must be at least 1")
    out = _fresh_dir(args.output)
    _write_json(out / "config.json", {"subgame": spec, "solver": options, "iterations": iterations,
                                      "resume": args.resume, "source_config": str(config_path)})
    with Meter() as meter:
        with Meter() as build:
            inst = plo_river_instance(spec)
        if args.resume:
            solver = CFRSolver.load_checkpoint(args.resume, inst)
        else:
            solver = CFRSolver(inst, solver_config(options))
        start_iteration = solver.iteration
        elapsed_before = solver.elapsed
        target = start_iteration + iterations
        eval_every = int(args.eval_every or max(1, iterations // 10))
        trajectory = []

        def callback(s: CFRSolver) -> None:
            done = s.iteration - start_iteration
            if done % eval_every == 0 or s.iteration == target:
                ex = evaluate_profile(inst, s.average_profile())
                trajectory.append({"iteration": s.iteration, "solve_seconds": round(s.elapsed, 3),
                                   "exploitability_chips": ex["exploitability_chips"],
                                   "exploitability_pct_pot": ex["exploitability_pct_pot"]})
                print(f"iter {s.iteration:>7}  exploitability {ex['exploitability_pct_pot']:.5f}% pot  "
                      f"({ex['exploitability_chips']:.4f} chips)  solve {s.elapsed:.1f}s", flush=True)
            if args.checkpoint_every and done % args.checkpoint_every == 0 and s.iteration != target:
                s.save_checkpoint(out / f"checkpoint-{s.iteration}.npz")

        solver.run(iterations, callback)
        checkpoint = solver.save_checkpoint(out / "checkpoint.npz")
        final = evaluate_profile(inst, solver.average_profile())
        current = evaluate_profile(inst, solver.current_profile())
        lp = None
        if max(inst.size(0), inst.size(1)) <= args.lp_limit:
            sol = solve_sequence_form(inst)
            lp = {"value0": sol["value0"], "value0_dual": sol["value0_dual"],
                  "solver_value0_minus_lp": final["value"][0] - sol["value0"]}
        policy = SubgamePolicy.from_solver(solver)
        root = policy.frequencies(())
    run = meter.report()
    solve_this_run = solver.elapsed - elapsed_before
    report = {
        "schema": "pokerlab.plo.river-solve/1",
        "subgame": inst.description, "fingerprint": inst.fingerprint,
        "solver": {**solver.config.__dict__, "iterations_total": solver.iteration,
                   "iterations_this_run": iterations, "resumed_from_iteration": start_iteration,
                   "resumed_from": args.resume},
        "average_strategy": final, "current_strategy": current, "lp_check": lp,
        "root_frequencies_oop": root, "trajectory": trajectory,
        "iteration_definition": (
            "one iteration = a full-width traversal updating player 0, then one updating player 1 "
            "(alternating updates), then DCFR discounting if selected; es-mccfr: one sampled "
            "traversal per player. Exploitability is reported for the average strategy "
            "('average_strategy') and separately for the last iterate ('current_strategy')."),
        "timing": {"build_s": round(build.wall, 3), "solve_s_this_run": round(solve_this_run, 3),
                   "solve_s_per_iteration": round(solve_this_run / max(1, iterations), 6),
                   "wall_s_total": run["wall_s"], "cpu_s_total": run["cpu_s"],
                   "scope": ("build_s: ranges, hand ranking, showdown precomputation and tree; "
                             "solve_s: CFR iterations only (exploitability checks, checkpoint "
                             "writing and LP excluded); wall_s_total: the whole command")},
        "memory": {"solver_arrays_and_showdown_mib": round(solver.memory_bytes() / 2**20, 2),
                   "process_peak_mib": run["peak_mib"], "peak_source": run["source"],
                   "scope": ("process_peak_mib: OS peak working set of the whole Python process "
                             "over the run (interpreter, NumPy, ranks, showdown index, regrets, "
                             "cumulative strategy and evaluation temporaries); "
                             "solver_arrays_and_showdown_mib: regrets + cumulative strategy + "
                             "showdown structures only")},
        "checkpoint": {"path": str(checkpoint), "sha256": _sha256(checkpoint),
                       "contents": "regrets, cumulative strategy, iteration, RNG state, config, fingerprint"},
        "units": "chips from the start of the river; % pot relative to the starting pot",
        "scope": ("Exact exploitability for these ranges and this pot-limit bet abstraction only; "
                  "not a full-game or off-tree guarantee."),
        "environment": environment(),
    }
    _write_json(out / "report.json", report)
    print(f"final: {final['exploitability_pct_pot']:.5f}% pot after {solver.iteration} iterations; "
          f"report {out / 'report.json'}")


def cmd_solve_turn(args: argparse.Namespace) -> None:
    from pokerlab.plo.subgame.turn import (
        TurnRiverSolver, evaluate_turn_profile, save_average_strategy, turn_frequencies, turn_river_game,
    )
    from pokerlab.plo.subgame.turn_reference import solve_turn_sequence_form

    config_path = Path(args.config)
    spec = load_json(config_path)
    options = dict(spec.get("solver", {}))
    for key in ("algorithm", "seed"):
        if getattr(args, key) is not None:
            if args.resume:
                raise SystemExit(f"--{key} cannot be combined with --resume: the checkpoint's config is used")
            options[key] = getattr(args, key)
    iterations = int(args.iterations if args.iterations is not None else options.get("iterations", 500))
    if iterations < 1:
        raise SystemExit("--iterations must be at least 1")
    out = _fresh_dir(args.output)
    _write_json(out / "config.json", {"subgame": spec, "solver": options, "iterations": iterations,
                                      "resume": args.resume, "source_config": str(config_path)})
    started_environment = environment()          # git state of the code this run executes
    with Meter() as meter:
        with Meter() as build:
            game = turn_river_game(spec)
        solver = (TurnRiverSolver.load_checkpoint(args.resume, game, workers=args.workers) if args.resume
                  else TurnRiverSolver(game, solver_config(options), workers=args.workers))
        start_iteration, elapsed_before = solver.iteration, solver.elapsed
        target = start_iteration + iterations
        eval_every = int(args.eval_every or max(1, iterations // 10))
        trajectory, eval_seconds = [], 0.0
        preflight = _turn_memory_preflight(solver)
        if not preflight["fits"]:
            raise SystemExit(f"estimated peak {preflight['estimated_peak_mib']} MiB exceeds the safe budget "
                             f"{preflight['safe_mib']} MiB (available minus {preflight['reserve_mib']} MiB)")
        run_started = time.perf_counter()
        limit_s = None if args.max_minutes is None else 60.0 * args.max_minutes
        stop = {"reason": "iteration target reached"}

        def should_stop(s: TurnRiverSolver) -> bool:
            if limit_s is not None and time.perf_counter() - run_started >= limit_s and s.iteration < target:
                stop["reason"] = f"wall-clock limit of {args.max_minutes} minutes reached"
                return True
            return False

        def callback(s: TurnRiverSolver) -> None:
            nonlocal eval_seconds
            done = s.iteration - start_iteration
            near_limit = limit_s is not None and time.perf_counter() - run_started >= limit_s
            if s.iteration % eval_every == 0 or s.iteration == target or near_limit:
                with Meter() as m:
                    ex = evaluate_turn_profile(game, s.average_profile())
                eval_seconds += m.wall
                trajectory.append({"iteration": s.iteration, "solve_seconds": round(s.elapsed, 3),
                                   "exploitability_chips": ex["exploitability_chips"],
                                   "exploitability_pct_pot": ex["exploitability_pct_pot"]})
                print(f"iter {s.iteration:>6}  exploitability {ex['exploitability_pct_pot']:.5f}% pot  "
                      f"solve {s.elapsed:.1f}s", flush=True)
            if args.checkpoint_every and done % args.checkpoint_every == 0 and s.iteration != target:
                s.save_checkpoint(out / f"checkpoint-{s.iteration}.npz")

        solver.run(iterations, callback, should_stop)
        if trajectory and trajectory[-1]["iteration"] != solver.iteration or not trajectory:
            callback_final = evaluate_turn_profile(game, solver.average_profile())
            trajectory.append({"iteration": solver.iteration, "solve_seconds": round(solver.elapsed, 3),
                               "exploitability_chips": callback_final["exploitability_chips"],
                               "exploitability_pct_pot": callback_final["exploitability_pct_pot"]})
        checkpoint = solver.save_checkpoint(out / "checkpoint.npz")
        average = solver.average_profile()
        final = evaluate_turn_profile(game, average)
        current = evaluate_turn_profile(game, solver.current_profile())
        strategy_file = save_average_strategy(game, average, out / "average_strategy.npz")
        lp = None
        if max(game.size(0), game.size(1)) <= args.lp_limit:
            with Meter() as m:
                sol = solve_turn_sequence_form(game)
            lp = {"value0": sol["value0"], "value0_dual": sol["value0_dual"],
                  "solver_value0_minus_lp": final["value"][0] - sol["value0"],
                  "lp_profile_exploitability_chips": evaluate_turn_profile(game, sol["profile"])[
                      "exploitability_chips"],
                  "variables_per_player": sol["variables"], "seconds": round(m.wall, 2)}
        spliced = None
        if args.spliced_baseline:
            with Meter() as m:
                helper = TurnRiverSolver(game, solver_config(options))
                rivers = helper.solve_rivers_with_prior_ranges(iterations)
                turn_only = TurnRiverSolver(game, solver_config(options), frozen_river=rivers)
                turn_only.run(iterations)
                metrics = evaluate_turn_profile(game, {"turn": turn_only.average_profile()["turn"],
                                                       "river": rivers})
            spliced = {"method": ("every river subgame solved on its own with the turn-start ranges "
                                  "(masked by the river card) for the same number of iterations, then the "
                                  "turn strategy optimised against those frozen river strategies"),
                       "exploitability_pct_pot": metrics["exploitability_pct_pot"],
                       "value": metrics["value"], "seconds": round(m.wall, 2)}
    run = meter.report()
    solve_this_run = solver.elapsed - elapsed_before
    report = {
        "schema": "pokerlab.plo.turn-river-solve/1",
        "subgame": game.description, "fingerprint": game.fingerprint,
        "solver": {**solver.config.__dict__, "iterations_total": solver.iteration,
                   "iterations_this_run": iterations, "resumed_from_iteration": start_iteration,
                   "resumed_from": args.resume, "workers": solver.workers,
                   "iterations_done_this_run": solver.iteration - start_iteration,
                   "stop_condition": {"iteration_target": target, "max_minutes": args.max_minutes,
                                      "stopped_because": stop["reason"]},
                   "memory_preflight": preflight,
                   "workers_meaning": ("threads over river-card blocks inside the showdown kernel; "
                                       "results are bitwise identical for any value")},
        "average_strategy": final, "current_strategy": current, "lp_check": lp,
        "spliced_baseline": spliced, "turn_frequencies": turn_frequencies(game, average),
        "trajectory": trajectory,
        "iteration_definition": ("one iteration = a full-width traversal of the whole turn+river game "
                                 "updating player 0, then one updating player 1 (all river cards "
                                 "enumerated, batched), then DCFR discounting if selected"),
        "timing": {"build_s": round(build.wall, 3), "solve_s_this_run": round(solve_this_run, 3),
                   "solve_s_per_iteration": round(solve_this_run / max(1, solver.iteration - start_iteration), 6),
                   "exploitability_checks_s": round(eval_seconds, 3),
                   "wall_s_total": run["wall_s"], "cpu_s_total": run["cpu_s"],
                   "scope": ("build_s: ranges, per-river-card hand ranking and showdown structures, trees; "
                             "solve_s: CFR iterations only")},
        "memory": {"by_category_mib": {k: round(v / 2**20, 2) for k, v in solver.memory().items()},
                   "solver_arrays_and_showdown_mib": round(solver.memory_bytes() / 2**20, 2),
                   "process_peak_mib": run["peak_mib"], "peak_source": run["source"],
                   "processes": 1,
                   "scope": ("by_category_mib: arrays held at the end of the run (temporaries excluded); "
                             "process_peak_mib: OS peak working set of this single process (worker threads share it)")},
        "checkpoint": {"path": str(checkpoint), "sha256": _sha256(checkpoint)},
        "average_strategy_file": {"path": str(strategy_file), "sha256": _sha256(strategy_file)},
        "units": "chips from the start of the turn; % pot relative to the starting pot",
        "scope": ("Exploitability is exact for this turn subgame only: the given ranges, board, pot, "
                  "stacks, the abstraction and raise caps above, all river cards enumerated. It says "
                  "nothing about flop/preflop play or the full game."),
        "environment": {**started_environment, "report_written": environment()["timestamp"],
                        "captured": "at the start of the run"},
    }
    _write_json(out / "report.json", report)
    print(f"final: {final['exploitability_pct_pot']:.5f}% pot after {solver.iteration} iterations "
          f"({stop['reason']}); report {out / 'report.json'}")


def _turn_memory_preflight(solver) -> dict:
    """End-of-run peak estimate against the host's existing safe budget (available RAM minus 2 GiB).

    Measured on the 1,485-hand game: the process peak was 2.52x the arrays held by the solver
    (average and current profiles are copied for evaluation and saving); 2.6x + 300 MiB is used.
    """
    import psutil
    from pokerlab.solver.resources import HOST_RESERVE_MB
    held = solver.memory_bytes() / 2**20
    estimate = 2.6 * held + 300.0
    available = psutil.virtual_memory().available / 2**20
    safe = available - HOST_RESERVE_MB
    return {"held_arrays_mib": round(held, 1), "estimated_peak_mib": round(estimate, 1),
            "available_mib": round(available, 1), "reserve_mib": HOST_RESERVE_MB, "safe_mib": round(safe, 1),
            "fits": estimate <= safe,
            "rule": "estimated peak = 2.6 x held solver arrays + 300 MiB <= available RAM - 2048 MiB"}


def cmd_evaluate(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    cfg = load_json(config_path)
    kind = cfg.get("kind")
    if kind == "match":
        if args.decision_log:
            log_path = Path(args.decision_log)
            if log_path.exists():
                raise SystemExit(f"refusing to overwrite {log_path}")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as log:
                report = evaluate_match(cfg, on_decision=lambda rec: log.write(json.dumps(rec) + "\n"))
            report["decision_log"] = {"path": str(log_path), "sha256": _sha256(log_path)}
        else:
            report = evaluate_match(cfg)
    elif kind == "river":
        inst = plo_river_instance(_subgame_spec(cfg, config_path.parent))
        solver = CFRSolver.load_checkpoint(_resolve(cfg["checkpoint"], config_path.parent), inst)
        report = evaluate_river(inst, solver, tuple(cfg.get("opponents", (
            "check_call", "uniform", "aggressive", "check_fold"))))
    else:
        raise SystemExit("config 'kind' must be 'match' or 'river'")
    report["config"] = str(config_path)
    _write_json(Path(args.output), report)
    _print_summary(report)


def cmd_query(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    inst = plo_river_instance(_subgame_spec(load_json(config_path), config_path.parent))
    policy = SubgamePolicy.from_solver(CFRSolver.load_checkpoint(args.checkpoint, inst))
    history = [h for h in args.history.split(",") if h] if args.history else []
    nid = policy.node(history)
    node = inst.tree.nodes[nid]
    print(f"node {nid}: history {history or '(root)'}; player {'OOP' if node.player == 0 else 'IP'} "
          f"to act; actions {list(node.actions)}")
    answer = policy.query(history, args.hand) if args.hand else policy.frequencies(history)
    print(json.dumps(answer, indent=2))


def cmd_simulate(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    cfg = load_json(config_path)
    out = _fresh_dir(args.output)
    log_path = out / "hands.jsonl"
    decision_path = out / "decisions.jsonl"
    with open(log_path, "w", encoding="utf-8") as log, open(decision_path, "w", encoding="utf-8") as dlog:
        report = evaluate_match(cfg, on_hand=lambda rec: log.write(json.dumps(rec) + "\n"),
                                on_decision=lambda rec: dlog.write(json.dumps(rec) + "\n"))
    report["config"] = str(config_path)
    report["hand_log"] = {"path": str(log_path), "sha256": _sha256(log_path),
                          "contents": "simulator ground truth incl. every hole card; "
                                      "for training data, never an agent input"}
    report["decision_log"] = {"path": str(decision_path), "sha256": _sha256(decision_path),
                              "contents": "per-decision records of agents that keep one "
                                          "(policy source, range updates, solve config, latency)"}
    _write_json(out / "summary.json", report)
    _print_summary(report)


def _print_summary(report: dict) -> None:
    if report["schema"].startswith("pokerlab.plo.match"):
        print(f"{report['players']} players, {report['format']}, {report['stack_mode']}, "
              f"{report['hands_played']} hands, {report['resources']['wall_s']}s")
        for r in report["results"]:
            if "bb_per_100" in r:
                print(f"  {r['agent']['name']:<16} {r['bb_per_100']:+9.2f} bb/100  "
                      f"(SE {r['se_bb_per_100']:.2f}, n={r['hands']})")
            summary = r.get("decision_summary")
            if summary and summary["river_solves"]:
                latency = summary["river_decision_latency_ms"]
                print(f"    river solves {summary['river_solves']}, river decision latency "
                      f"median {latency['median']:.0f} ms / p95 {latency['p95']:.0f} ms")
    else:
        ex = report["exact_metrics"]
        print(f"river exploitability {ex['exploitability_pct_pot']:.5f}% pot")
        for v in report["versus_fixed_bots"]:
            print(f"  hero {v['hero_seat']} vs {v['opponent']:<11} value {v['hero_value_chips']:.2f} chips "
                  f"(BR {v['best_response_value_chips']:.2f})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pokerlab.plo")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="list implemented / missing modules")
    solve = sub.add_parser("solve-river", help="solve a heads-up PLO4 river subgame")
    solve.add_argument("config")
    solve.add_argument("--output", required=True)
    solve.add_argument("--iterations", type=int)
    solve.add_argument("--algorithm")
    solve.add_argument("--seed", type=int)
    solve.add_argument("--resume")
    solve.add_argument("--checkpoint-every", type=int, default=0)
    solve.add_argument("--eval-every", type=int, default=0)
    solve.add_argument("--lp-limit", type=int, default=12,
                       help="run the sequence-form LP check when both ranges are at most this size")
    turn = sub.add_parser("solve-turn", help="jointly solve a heads-up PLO4 turn + river subgame")
    turn.add_argument("config")
    turn.add_argument("--output", required=True)
    turn.add_argument("--iterations", type=int)
    turn.add_argument("--algorithm")
    turn.add_argument("--seed", type=int)
    turn.add_argument("--resume")
    turn.add_argument("--checkpoint-every", type=int, default=0)
    turn.add_argument("--eval-every", type=int, default=0)
    turn.add_argument("--lp-limit", type=int, default=5,
                      help="run the joint sequence-form LP when both ranges are at most this size")
    turn.add_argument("--max-minutes", type=float,
                      help="stop this run after this many wall-clock minutes (checked after each iteration)")
    turn.add_argument("--workers", type=int, default=1,
                      help="threads over river-card blocks in the inclusion-exclusion showdown kernel")
    turn.add_argument("--spliced-baseline", action="store_true",
                      help="also measure the spliced shortcut (independent rivers + turn) for comparison")
    evaluate = sub.add_parser("evaluate", help="match or river-subgame evaluation report")
    evaluate.add_argument("config")
    evaluate.add_argument("--output", required=True)
    evaluate.add_argument("--decision-log", help="JSONL file for per-decision records (match only)")
    simulate = sub.add_parser("simulate", help="generate a simulator hand log plus summary")
    simulate.add_argument("config")
    simulate.add_argument("--output", required=True)
    query = sub.add_parser("query", help="look up a solved river strategy")
    query.add_argument("config", help="the river subgame config that was solved")
    query.add_argument("checkpoint")
    query.add_argument("--history", default="", help="comma-separated actions, e.g. check,bet:660")
    query.add_argument("--hand", help="own hole cards, e.g. AsKdQh2c; omit for range frequencies")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(format_table())
    elif args.command == "solve-river":
        cmd_solve_river(args)
    elif args.command == "solve-turn":
        cmd_solve_turn(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "query":
        cmd_query(args)
    else:
        cmd_simulate(args)


if __name__ == "__main__":
    main(sys.argv[1:])
