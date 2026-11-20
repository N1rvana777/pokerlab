import json

import pytest

from pokerlab.plo.__main__ import main

TINY = {"board": "Ks9h7d4c2s", "pot_bb": 10, "stacks_bb": [30, 30], "big_blind": 100,
        "ranges": [{"sample": 6, "seed": 1}, {"sample": 6, "seed": 2}],
        "bet_sizes": [0.5, 1.0], "raise_sizes": [1.0], "max_raises": 2,
        "solver": {"algorithm": "dcfr", "iterations": 60, "seed": 0}}


def test_solve_resume_and_evaluate_river(tmp_path, capsys):
    config = tmp_path / "tiny.json"
    config.write_text(json.dumps(TINY))
    main(["solve-river", str(config), "--output", str(tmp_path / "run1"), "--eval-every", "30"])
    first = json.loads((tmp_path / "run1" / "report.json").read_text())
    assert first["solver"]["iterations_total"] == 60
    assert [t["iteration"] for t in first["trajectory"]] == [30, 60]
    assert first["lp_check"] is not None and first["average_strategy"]["exploitability_chips"] >= -1e-9
    assert first["memory"]["process_peak_mib"] is None or first["memory"]["process_peak_mib"] > 0
    with pytest.raises(SystemExit):
        main(["solve-river", str(config), "--output", str(tmp_path / "run1")])
    with pytest.raises(SystemExit):
        main(["solve-river", str(config), "--output", str(tmp_path / "zero"), "--iterations", "0"])

    main(["solve-river", str(config), "--output", str(tmp_path / "run2"), "--iterations", "40",
          "--resume", str(tmp_path / "run1" / "checkpoint.npz")])
    second = json.loads((tmp_path / "run2" / "report.json").read_text())
    assert second["solver"]["iterations_total"] == 100
    assert second["solver"]["resumed_from_iteration"] == 60

    evaluation = tmp_path / "eval.json"
    evaluation.write_text(json.dumps({"kind": "river", "subgame": str(config),
                                      "checkpoint": str(tmp_path / "run2" / "checkpoint.npz")}))
    main(["evaluate", str(evaluation), "--output", str(tmp_path / "river-eval.json")])
    report = json.loads((tmp_path / "river-eval.json").read_text())
    assert len(report["versus_fixed_bots"]) == 8
    assert report["lp_check"]["solver_value0_minus_lp"] == pytest.approx(0.0, abs=5.0)
    for row in report["versus_fixed_bots"]:
        assert row["best_response_value_chips"] >= row["hero_value_chips"] - 1e-9
    assert "exploitability" in capsys.readouterr().out

    from pokerlab.plo.subgame.instance import plo_river_instance
    hand = plo_river_instance(TINY).labels[1][0]
    main(["query", str(config), str(tmp_path / "run2" / "checkpoint.npz"), "--history", "check", "--hand", hand])
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["player"] == 1 and sum(payload["actions"].values()) == pytest.approx(1.0)


def test_match_and_simulation_reports(tmp_path):
    match = tmp_path / "match.json"
    match.write_text(json.dumps({
        "kind": "match", "players": 2, "starting_stacks_bb": [100, 100], "format": "duplicate",
        "deals": 20, "seed": 1, "agents": [{"type": "rule"}, {"type": "random", "seed": 2}]}))
    main(["evaluate", str(match), "--output", str(tmp_path / "match-report.json")])
    report = json.loads((tmp_path / "match-report.json").read_text())
    assert report["hands_played"] == 40 and len(report["results"]) == 2
    assert sum(r["net_chips"] for r in report["results"]) == 0
    assert report["rules"]["game"] == "PLO4" and report["stack_mode"] == "reset"
    assert {"wall_s", "cpu_s", "peak_mib"} <= set(report["resources"])

    session = tmp_path / "session.json"
    session.write_text(json.dumps({
        "kind": "match", "players": 6, "starting_stacks_bb": [100, 40, 250, 100, 60, 20],
        "format": "session", "stack_mode": "carry", "bust_policy": "rebuy", "hands": 30,
        "batch_hands": 10, "seed": 3,
        "agents": [{"type": "rule"}, {"type": "random", "seed": 1}, {"type": "calling_station"},
                   {"type": "random", "seed": 2}, {"type": "rule"}, {"type": "calling_station"}]}))
    main(["simulate", str(session), "--output", str(tmp_path / "sim")])
    summary = json.loads((tmp_path / "sim" / "summary.json").read_text())
    lines = (tmp_path / "sim" / "hands.jsonl").read_text().splitlines()
    assert len(lines) == summary["hands_played"] == 30
    first = json.loads(lines[0])
    assert len(first["hole_cards"]) == 6 and first["starting_stacks"] == [10000, 4000, 25000, 10000, 6000, 2000]


def test_status_lists_missing_modules(capsys):
    main(["status"])
    out = capsys.readouterr().out
    assert "blueprint" in out and "not implemented" in out and "opponent model" in out
