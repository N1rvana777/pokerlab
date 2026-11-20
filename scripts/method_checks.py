"""Test principles against the Solver: same spot, one change to the opponent, compare what Hero does.

  python -X utf8 scripts/method_checks.py

Spots are the ranges copied from GTO Wizard under outputs/gtow-compare. Hands are grouped by equity against the
opponent's range at that node: weak under 33%, middle up to 66%, strong above. Output goes to a new file under
outputs/knowledge/hhp/methods/solver_runs; nothing is overwritten. Multiway claims cannot be tested: the engine is heads-up.
"""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from compare_reference import combo_weights, config_for  # noqa: E402
from pokerlab.coach import knowledge  # noqa: E402
from pokerlab.solver.workbench import SESSIONS, ROOT, inspect, new_job_dir, solve_cached  # noqa: E402

COMPARE = ROOT / 'outputs/gtow-compare'
TARGET = .02
STATION = {'check': 2, 'call': 6, 'bet': -3}
NIT = {'fold': 7, 'check': 2, 'bet': -3}
MANIAC = {'fold': -6, 'call': 3, 'bet': 6}


def spot(name):
    return json.loads((COMPARE / name / 'spot.json').read_text(encoding='utf-8'))


def solve(place, incentives=None, biased=1, overrides=None):
    config = config_for(spot(place), TARGET, 24, 4000)
    if incentives:
        config.update(mode='preview', hero=1 - biased, profile={'traits': [], 'incentives': incentives})
    if overrides:
        config.update(mode='locked', expand_suits=True, profile={'traits': [], 'overrides': overrides})
    return solve_cached(config, new_job_dir())


def groups(report, path, action):
    """Share of one action in each equity group at a node, and the combos behind it."""
    node = inspect(report, path, 'baseline', new_job_dir())
    player = node['players'][node['actor']]
    count = len(player['combos'])
    at = next(i for i, name in enumerate(node['actions']) if name.startswith(action))
    mass, took = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    for hand, (weight, equity) in enumerate(zip(combo_weights(player), player['equity'])):
        group = 0 if equity < .33 else 1 if equity < .66 else 2
        mass[group] += weight
        took[group] += weight * node['strategy_action_major'][at * count + hand]
    return {'weak': round(took[0] / mass[0] * 100, 1) if mass[0] else None, 'middle': round(took[1] / mass[1] * 100, 1) if mass[1] else None,
            'strong': round(took[2] / mass[2] * 100, 1) if mass[2] else None, 'overall': round(sum(took) / sum(mass) * 100, 1),
            'bluff_share': round(took[0] / sum(took) * 100, 1) if sum(took) else None, 'combos': round(sum(took), 1)}


def weak_locks(plain, chosen):
    """Lock OOP's weakest river hands at the root to one action; everything else stays free."""
    node = inspect(plain, [], 'baseline', new_job_dir())
    player = node['players'][0]
    index = next(i for i, name in enumerate(node['actions']) if name.startswith(chosen))
    share = [float(i == index) for i in range(len(node['actions']))]
    return [dict(path=[], combo=combo, probabilities=share) for combo, equity, weight in zip(player['combos'], player['equity'], combo_weights(player)) if equity < .33 and weight > 0]


def main():
    plain = solve('lock_river1')
    rows = []
    # A river, OOP (BB) to act, IP (BTN) biased.
    for name, incentives in (('plain', None), ('station', STATION), ('nit', NIT)):
        report = plain if incentives is None else solve('lock_river1', incentives, 1)
        rows.append({'test': 'river_oop_bet_vs_ip', 'opponent': name, 'bet': groups(report, [], 'Bet')})
    # The same river: what IP does when OOP's bets hold fewer or more bluffs.
    for name, chosen in (('plain', None), ('under_bluffs', 'Check'), ('over_bluffs', 'Bet')):
        report = plain if chosen is None else solve('lock_river1', overrides=weak_locks(plain, chosen))
        rows.append({'test': 'river_ip_vs_bet', 'opponent': name, 'bluffs_in_bet': groups(report, [], 'Bet')['bluff_share'], 'call': groups(report, [1], 'Call')})
    # A turn, OOP checks, IP (BTN) to act, OOP biased.
    base = solve('custom_turn1')
    for name, incentives in (('plain', None), ('station', STATION), ('maniac', MANIAC), ('passive', {'bet': -6})):
        report = base if incentives is None else solve('custom_turn1', incentives, 0)
        rows.append({'test': 'turn_ip_bet_vs_oop', 'opponent': name, 'bet': groups(report, [0], 'Bet')})
    SESSIONS.close()
    folder = knowledge.home() / 'methods' / 'solver_runs'
    folder.mkdir(exist_ok=True)
    out = folder / time.strftime('checks-%Y%m%d-%H%M%S.json')
    with out.open('x', encoding='utf-8') as stream:
        json.dump({'target_pot_pct': TARGET, 'groups': 'equity against the range at the node: weak <33%, middle <66%, strong', 'rows': rows}, stream, ensure_ascii=False, indent=1)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
