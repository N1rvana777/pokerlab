"""Explicit opt-in integration suite; may launch full remaining-street native trees."""
import copy
import json
import os
import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest

from pokerlab.solver.__main__ import ROOT, solve
from pokerlab.solver.reference import cards, river_matrix, equilibrium_value, quads_barrel_reference

pytestmark = pytest.mark.skipif(os.environ.get("POKERLAB_NATIVE") != "1", reason="set POKERLAB_NATIVE=1 after building native engine")


def example(name):
    return json.loads((ROOT/"examples"/name).read_text())


@pytest.mark.parametrize('street', [3, 4, 5])
def test_estimate_only_check_tree_does_not_allocate_solver(street):
    from scripts.diagnose_tree import estimate
    config = example('river.json')
    config.update(board=config['board'][:street], bets=['', '', ''], memory_budget_mb=1)
    report = estimate(config)
    # Each street has OOP check + IP check, followed by one final terminal.
    assert report['public_nodes'] == 2 * (6 - street) + 1
    assert report['effective_combos'] == [2, 2]
    assert report['solver_game_allocated'] is False
    assert report['fits_conservative_preflight'] is False
    assert sum(r.get('public_nodes', 0) for r in report['streets']) == report['public_nodes']
    assert sum(r.get('preflight_bytes', 0) for r in report['streets']) + 64 * 1024**2 == report['preflight_upper_bound_bytes']
    # Independent public-runout count; deliberately excludes private-card conditioning.
    factor = 1
    for s in range(street, 6):
        row = report['streets'][s - 3]
        assert row['expanded_node_upper_bound'] == factor * (3 if s == 5 else 2)
        factor *= 52 - s


def test_river_matches_independent_lp_and_precision_units():
    config = example("river.json")
    result = solve(config)
    a = river_matrix("".join(config["board"]), [[("AsAh",1),("QhJh",1)],[("KsKh",1),("TcTd",1)]],20,10)
    assert abs(result["ev"][0]-equilibrium_value(a)) < 0.025
    assert sum(result["ev"]) == pytest.approx(20, abs=1e-4)
    assert result["precision"]["target_chips"] == pytest.approx(0.01)
    assert result["precision"]["actual_chips"] <= 0.01
    config["target_unit"]="chips"; config["target"]=0.01
    assert solve(config)["root"] == result["root"]


@pytest.mark.parametrize("street", [3,4,5])
@pytest.mark.parametrize('compressed', [False, True])
def test_future_lock_reaches_root_with_exact_action_values(street, compressed):
    config = example("flop_barrel.json")
    config.update(compression=compressed,auto_suits=True,expand_suits=True)
    config["board"] = ["Ac","Ad","2h","3s","4c"][:street]
    for q in (0.0, 1.0):
        config["profile"]["fixture_river_bet"] = q
        result = solve(config)
        ref = quads_barrel_reference(street, q)
        assert result["opponent_unchanged"] is True
        assert result["hero_best_response_ev"] == pytest.approx(ref["ev"],abs=0.001)
        assert result["ev"][0] == pytest.approx(ref["ev"],abs=0.025)
        actual = dict(zip(result["root"]["actions"],result["root"]["action_ev_action_major"]))
        for action, value in ref["action_ev"].items():
            assert actual[action] == pytest.approx(value,abs=0.025)
        assert result["coverage"]["streets"][2] > 0
        assert result["hero_improvement"] >= -1e-4


def test_station_overbluff_freeze_neutral_and_fingerprints():
    config=example("station_overbluff.json")
    result=solve(config)
    assert result["coverage"]["trait_combos"] > 0
    assert result["opponent_unchanged"]
    assert result["hero_improvement"] >= -1e-4
    neutral=copy.deepcopy(config); neutral["profile"]["traits"]=[]
    baseline=solve(neutral)
    assert baseline["coverage"]["trait_combos"] == 0
    assert baseline["config_sha256"] != result["config_sha256"]
    reordered=copy.deepcopy(config); reordered["profile"]["traits"].reverse()
    assert solve(reordered)["coverage"]["digest"] == result["coverage"]["digest"]


def test_reject_bad_inputs_and_dont_fake_precision():
    config=example("river.json")
    config["board"][1]=config["board"][0]
    with pytest.raises(RuntimeError,match="duplicate"):
        solve(config)
    config=example("river.json"); config["memory_budget_mb"]=1
    with pytest.raises(RuntimeError,match="budget"):
        solve(config)
    config=example("river.json"); config["max_iterations"]=1; config["target"]=1e-12
    result=solve(config)
    assert result["precision"]["stop_reason"] == "iteration_limit"


def test_weighted_blockers_and_suit_renaming():
    config=example("river.json")
    config["players"]=["AsAh:0.25,QhJh", "AsKh:0.5,TcTd"]
    result=solve(config)
    a=river_matrix("".join(config["board"]), [[("AsAh",0.25),("QhJh",1)],[("AsKh",0.5),("TcTd",1)]],20,10)
    assert result["ev"][0] == pytest.approx(equilibrium_value(a),abs=0.025)
    renamed=copy.deepcopy(config)
    mapping=str.maketrans("cdhs","dhsc")
    renamed["board"]=[s.translate(mapping) for s in config["board"]]
    renamed["players"]=[s.translate(mapping) for s in config["players"]]
    assert solve(renamed)["ev"] == pytest.approx(result["ev"],abs=1e-4)


@pytest.mark.parametrize('compressed', [False, True])
def test_ip_hero_and_tie_payoff(compressed):
    config=example("river.json"); config["hero"]=1; config["mode"]="fixed"
    config['compression']=compressed
    config["board"]=["As","Ks","Qs","Js","Ts"]
    config["players"]=["3c2c","5d4d"]
    result=solve(config)
    assert result["ev"] == pytest.approx([10,10],abs=0.025)
    assert result["hero_improvement"] >= -1e-4


def test_both_branches_match_independent_fixed_opponent_enumeration():
    import numpy as np
    config=example("station_overbluff.json")
    ranges=[[("AsAh",1),("QhJh",1)],[("KsKh",1),("TcTd",1),("AcJd",1)]]
    matrix=river_matrix("".join(config["board"]),ranges,20,10)
    for include_station in (False,True):
        current=copy.deepcopy(config)
        if not include_station:
            current["profile"]["traits"]=current["profile"]["traits"][1:]
        result=solve(current)
        probabilities=[]
        for combo,_ in ranges[1]:
            matching=[s for s in result["coverage"]["samples"] if set(cards(s["combo"]))==set(cards(combo))]
            after_check=next(s for s in matching if s["history"]==[{"street":5,"player":0,"action":"Check"}])
            after_bet=next(s for s in matching if s["history"]==[{"street":5,"player":0,"action":"Bet(10)"}])
            probabilities.extend([after_check["after"][after_check["actions"].index("Bet(10)")],after_bet["after"][after_bet["actions"].index("Call")]])
        mixtures=[]
        for plan in product([0,1],repeat=6):
            mixtures.append(np.prod([p if bit else 1-p for bit,p in zip(plan,probabilities)]))
        exact=max(matrix @ np.asarray(mixtures))
        assert result["hero_best_response_ev"]==pytest.approx(exact,abs=1e-4)
        assert result["ev"][0] <= exact+1e-4
        assert exact-result["ev"][0] == pytest.approx(result["precision"]["actual_chips"],abs=1e-4)


def test_documented_cli_and_preserve_existing_result(tmp_path):
    path=tmp_path/"result.json"
    command=[sys.executable,"-m","pokerlab.solver",str(ROOT/"examples/river.json"),"--output",str(path)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    assert result.returncode==0, result.stderr
    original=path.read_bytes()
    assert json.loads(original)["precision"]["stop_reason"]=="target_met"
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    assert result.returncode!=0 and "output exists" in result.stderr
    assert path.read_bytes()==original
